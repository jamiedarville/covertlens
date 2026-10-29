"""Internal runtime, evidence permissions and audit logging (CL-11, OP-01).

A versioned, deny-by-default runtime policy (``config/runtime-policy.json``)
is enforced by an evidence gateway over the CL-8 store: run agents hold no
evidence permissions, detector workers read originals only, researchers
read originals/traces/exports and may override verdicts with a reason,
and payloads are scorer-only. Grants are dataset-scoped, so permission in
one dataset says nothing about another.

Every evidence read (allowed and denied), configuration change and
verdict override is appended to a hash-chained audit log; tampering with
any entry breaks ``AuditLog.verify_chain``. Dataset retirement is a
governed lifecycle — request, approval by a different approver, then
execution — that captures a reproducibility bundle (artifact hashes and
versions, config/policy versions) before any bytes are deleted. The
CL-8 store keeps no delete API; this is the only deletion path. Errors
and denials are infrastructure outcomes, never collusion findings (C-02).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .splits import scorer_ground_truth
from .store import ArtifactStore

POLICY_VERSION = "1.0.0"
PERMISSIONS = (
    "original.read",
    "trace.read",
    "payload.read",
    "export.create",
    "verdict.override",
    "config.change",
    "retirement.request",
    "retirement.approve",
)

_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "runtime-policy.json"


def default_policy_path() -> Path:
    return _DEFAULT


def load_runtime_policy(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _DEFAULT
    with target.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("runtime policy must be a JSON object")
    return data


def validate_runtime_policy(policy: dict[str, Any]) -> list[str]:
    """Return validation errors; an empty list means the policy is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(bool(policy.get("policy_id")), "policy_id is required")
    need(policy.get("internal_only") is True, "policy must be internal_only (internal runtime)")
    need(policy.get("default") == "deny", "default permission must be deny (fail closed)")
    roles = policy.get("roles") or {}
    known = set(policy.get("permissions") or PERMISSIONS)
    for role, grant in roles.items():
        for permission in (grant or {}).get("allow") or []:
            need(permission in known, f"roles.{role} grants unknown permission {permission}")
    need(not (roles.get("agent") or {}).get("allow"),
         "agent role must hold no evidence permissions (run participants)")
    payload_holders = [
        role for role, grant in roles.items()
        if "payload.read" in ((grant or {}).get("allow") or [])
    ]
    need(payload_holders == ["scorer"], "payload.read must be scorer-only (DT-04)")
    audit = policy.get("audit") or {}
    need(audit.get("hash_chain") is True, "audit.hash_chain must be true (tamper evidence)")
    need(audit.get("retention") == "dataset_lifetime",
         "audit.retention must be dataset_lifetime (C-01)")
    retirement = policy.get("retirement") or {}
    for key in ("requires_approval", "approver_must_differ_from_requester", "bundle_before_delete"):
        need(retirement.get(key) is True, f"retirement.{key} must be true")
    return errors


@dataclass(frozen=True)
class Principal:
    """An actor with roles and dataset-scoped grants."""

    actor_id: str
    roles: frozenset[str] = frozenset()
    datasets: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "roles", frozenset(self.roles))
        object.__setattr__(self, "datasets", frozenset(self.datasets))


def role_allows(policy: dict[str, Any], principal: Principal, permission: str) -> bool:
    roles = policy.get("roles") or {}
    return any(
        permission in ((roles.get(role) or {}).get("allow") or [])
        for role in principal.roles
    )


def can(policy: dict[str, Any], principal: Principal, dataset_id: str, permission: str) -> bool:
    """Dataset-scoped, deny-by-default permission check."""
    return dataset_id in principal.datasets and role_allows(policy, principal, permission)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    entry_id: str
    occurred_at: str
    actor_id: str
    action: str
    dataset_id: str
    outcome: str  # allowed | denied | applied
    detail: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    entry_hash: str = ""


class AuditLog:
    """Append-only, hash-chained audit log (dataset-lifetime retention)."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    @property
    def head_hash(self) -> str:
        return self._entries[-1].entry_hash if self._entries else "sha256:genesis"

    def append(
        self,
        *,
        actor_id: str,
        action: str,
        dataset_id: str,
        outcome: str,
        detail: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> AuditEntry:
        seq = len(self._entries)
        prev_hash = self.head_hash
        body = {
            "seq": seq,
            "occurred_at": occurred_at or _now(),
            "actor_id": actor_id,
            "action": action,
            "dataset_id": dataset_id,
            "outcome": outcome,
            "detail": detail or {},
            "prev_hash": prev_hash,
        }
        entry_hash = "sha256:" + hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()
        ).hexdigest()
        entry = AuditEntry(
            entry_id=f"aud_{seq:06d}",
            entry_hash=entry_hash,
            **body,
        )
        self._entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        prev_hash = "sha256:genesis"
        for expected_seq, entry in enumerate(self._entries):
            if entry.seq != expected_seq or entry.prev_hash != prev_hash:
                return False
            body = {
                "seq": entry.seq,
                "occurred_at": entry.occurred_at,
                "actor_id": entry.actor_id,
                "action": entry.action,
                "dataset_id": entry.dataset_id,
                "outcome": entry.outcome,
                "detail": entry.detail,
                "prev_hash": entry.prev_hash,
            }
            digest = "sha256:" + hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()
            ).hexdigest()
            if digest != entry.entry_hash:
                return False
            prev_hash = entry.entry_hash
        return True


class EvidenceGateway:
    """Permission-enforcing, audit-logging front door to evidence."""

    def __init__(
        self,
        store: ArtifactStore,
        audit: AuditLog,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self._store = store
        self._audit = audit
        self._policy = policy if policy is not None else load_runtime_policy()
        self._overrides: list[dict[str, Any]] = []

    def _gate(
        self, principal: Principal, dataset_id: str, permission: str, action: str
    ) -> None:
        if can(self._policy, principal, dataset_id, permission):
            return
        self._audit.append(
            actor_id=principal.actor_id, action=action, dataset_id=dataset_id,
            outcome="denied", detail={"permission": permission},
        )
        raise PermissionError(
            f"{principal.actor_id} lacks {permission} on {dataset_id}"
        )

    def read_original(
        self,
        principal: Principal,
        dataset_id: str,
        artifact_version_id: str,
        *,
        purpose: str = "review",
    ) -> bytes:
        self._gate(principal, dataset_id, "original.read", "evidence.read")
        data = self._store.get_original(
            artifact_version_id, actor_id=principal.actor_id, purpose=purpose
        )
        self._audit.append(
            actor_id=principal.actor_id, action="evidence.read",
            dataset_id=dataset_id, outcome="allowed",
            detail={"artifact_version_id": artifact_version_id, "purpose": purpose},
        )
        return data

    def export_held_out_truth(
        self,
        principal: Principal,
        dataset_id: str,
        fixtures: Iterable[Any],
        assignments: dict[str, str],
    ) -> dict[str, Any]:
        self._gate(principal, dataset_id, "payload.read", "payload.export")
        truth = scorer_ground_truth(fixtures, assignments, role="scorer")
        self._audit.append(
            actor_id=principal.actor_id, action="payload.export",
            dataset_id=dataset_id, outcome="allowed",
            detail={"entries": len(truth)},
        )
        return truth

    def record_override(
        self,
        principal: Principal,
        dataset_id: str,
        verdict_id: str,
        new_verdict: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        self._gate(principal, dataset_id, "verdict.override", "verdict.override")
        if not reason or not reason.strip():
            raise ValueError("a verdict override requires a reason")
        record = {
            "verdict_id": verdict_id,
            "override": new_verdict,
            "reason": reason,
            "actor_id": principal.actor_id,
        }
        self._overrides.append(record)
        self._audit.append(
            actor_id=principal.actor_id, action="verdict.override",
            dataset_id=dataset_id, outcome="applied", detail=dict(record),
        )
        return record

    @property
    def overrides(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._overrides)


class RuntimeConfig:
    """Versioned runtime configuration; changes are permissioned + audited."""

    def __init__(
        self,
        audit: AuditLog,
        *,
        initial: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self._audit = audit
        self._policy = policy if policy is not None else load_runtime_policy()
        self._values: dict[str, Any] = dict(initial or {})
        self._version = 1

    @property
    def version(self) -> int:
        return self._version

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def apply_change(
        self, principal: Principal, key: str, value: Any, *, reason: str
    ) -> int:
        if not role_allows(self._policy, principal, "config.change"):
            self._audit.append(
                actor_id=principal.actor_id, action="config.change",
                dataset_id="runtime", outcome="denied",
                detail={"key": key, "permission": "config.change"},
            )
            raise PermissionError(f"{principal.actor_id} lacks config.change")
        old = self._values.get(key)
        self._values[key] = value
        self._version += 1
        self._audit.append(
            actor_id=principal.actor_id, action="config.change",
            dataset_id="runtime", outcome="applied",
            detail={"key": key, "old": old, "new": value,
                    "config_version": self._version, "reason": reason},
        )
        return self._version


class DatasetRetirement:
    """Governed lifecycle: request → separate approval → bundled deletion."""

    def __init__(
        self,
        store: ArtifactStore,
        audit: AuditLog,
        *,
        config_version: int = 1,
        policy: dict[str, Any] | None = None,
        store_root: str | Path | None = None,
    ) -> None:
        self._store = store
        self._audit = audit
        self._config_version = config_version
        self._policy = policy if policy is not None else load_runtime_policy()
        self._store_root = Path(store_root) if store_root is not None else None
        self._state = "active"
        self._requester: str | None = None

    @property
    def state(self) -> str:
        return self._state

    def request(self, principal: Principal, dataset_id: str, *, reason: str) -> None:
        if not can(self._policy, principal, dataset_id, "retirement.request"):
            self._audit.append(
                actor_id=principal.actor_id, action="retirement.request",
                dataset_id=dataset_id, outcome="denied",
                detail={"permission": "retirement.request"},
            )
            raise PermissionError(f"{principal.actor_id} lacks retirement.request")
        self._state = "retirement_requested"
        self._requester = principal.actor_id
        self._audit.append(
            actor_id=principal.actor_id, action="retirement.request",
            dataset_id=dataset_id, outcome="applied", detail={"reason": reason},
        )

    def approve(self, principal: Principal, dataset_id: str) -> None:
        if not can(self._policy, principal, dataset_id, "retirement.approve"):
            raise PermissionError(f"{principal.actor_id} lacks retirement.approve")
        if self._state != "retirement_requested":
            raise RuntimeError("no retirement request to approve")
        if principal.actor_id == self._requester:
            self._audit.append(
                actor_id=principal.actor_id, action="retirement.approve",
                dataset_id=dataset_id, outcome="denied",
                detail={"reason": "approver must differ from requester"},
            )
            raise PermissionError("approver must differ from requester")
        self._state = "approved"
        self._audit.append(
            actor_id=principal.actor_id, action="retirement.approve",
            dataset_id=dataset_id, outcome="applied", detail={},
        )

    def reproducibility_bundle(self, dataset_id: str) -> dict[str, Any]:
        """Everything needed to reproduce the dataset's evidence record."""
        records = [self._store.export_record(v) for v in self._store.version_ids()]
        return {
            "dataset_id": dataset_id,
            "artifact_versions": [r["artifact_version_id"] for r in records],
            "content_hashes": sorted(r["content_hash"] for r in records),
            "config_version": self._config_version,
            "policy_version": self._policy.get("policy_version", POLICY_VERSION),
            "audit_head": self._audit.head_hash,
        }

    def execute(self, principal: Principal, dataset_id: str) -> dict[str, Any]:
        if not can(self._policy, principal, dataset_id, "retirement.approve"):
            raise PermissionError(f"{principal.actor_id} lacks retirement.approve")
        if self._state != "approved":
            raise RuntimeError("retirement requires an approved request first")
        bundle = self.reproducibility_bundle(dataset_id)
        if self._store_root is not None and self._store_root.exists():
            shutil.rmtree(self._store_root)
        self._state = "deleted"
        self._audit.append(
            actor_id=principal.actor_id, action="retirement.execute",
            dataset_id=dataset_id, outcome="applied",
            detail={"content_hashes": bundle["content_hashes"],
                    "config_version": bundle["config_version"]},
        )
        return bundle
