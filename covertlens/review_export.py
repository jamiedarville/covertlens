"""Review exports and evidence access verification (CL-33, REV-06).

Finalizes the MVP evidence package on top of the CL-25 researcher
report and the CL-26 hash-sealed export:

- **Package contents (no raw bytes):** per original — artifact id,
  version id, content hash and its detector findings; per delivery
  — verdict, trace references and the researcher's disposition;
  plus the policy block that makes the package interpretable
  (runtime policy id/version, threshold config version, detector
  versions, seeds, dataset hash, pin hash). The seal is recomputed
  on validation, so tampering with any field breaks the package.
- **Permissioned creation and reads:** export creation requires
  the CL-11 `export.create` permission for the dataset; original
  reads go through the CL-11 evidence gateway (`original.read`).
  Grants are dataset-scoped and deny-by-default: run agents hold
  no evidence permissions, and permission on one dataset says
  nothing about another.
- **Auditability:** allowed and denied reads/exports are appended
  to the hash-chained CL-11 audit log, and original reads also
  appear in the CL-8 store access history. `verify_evidence_access`
  checks the chain and cross-references both logs. Payloads and
  ground truth are never part of a review package (scorer-only,
  C-07); scores are evidence aids, not collusion proof (C-02).
"""

from __future__ import annotations

from typing import Any

from . import ids
from .pinning import _hash
from .runtime import AuditLog, Principal, can, load_runtime_policy

EXPORT_PACKAGE_SCHEMA = "covertlens.review-export"
EXPORT_PACKAGE_VERSION = "1.0.0"
_FORBIDDEN_KEYS = {"data", "payload", "bytes", "raw_bytes"}


def _contains_raw_bytes(value: Any) -> bool:
    if isinstance(value, (bytes, bytearray)):
        return True
    if isinstance(value, dict):
        return any(
            key in _FORBIDDEN_KEYS or _contains_raw_bytes(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_raw_bytes(item) for item in value)
    return False


def build_review_package(
    report: dict[str, Any],
    pin: dict[str, Any],
    *,
    dataset_id: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the sealed review package for one run report."""
    active_policy = policy if policy is not None else load_runtime_policy()
    dispositions = {
        row["delivery_id"]: row["disposition"]
        for row in report.get("triage_queue") or []
    }
    package: dict[str, Any] = {
        "schema": EXPORT_PACKAGE_SCHEMA,
        "schema_version": 1,
        "export_version": EXPORT_PACKAGE_VERSION,
        "run_id": report.get("run_id"),
        "report_id": report.get("report_id"),
        "dataset_id": dataset_id,
        "policy": {
            "runtime_policy_id": active_policy.get("policy_id"),
            "runtime_policy_version": active_policy.get("policy_version"),
            "threshold_config_version": pin.get("threshold_config_version"),
            "thresholds_status": pin.get("thresholds_status"),
            "detectors": pin.get("detectors"),
            "seeds": pin.get("seeds"),
            "pin_hash": pin.get("pin_hash"),
            "dataset_hash": (pin.get("dataset") or {}).get("dataset_hash"),
        },
        "originals": [
            {
                "artifact_id": o.get("artifact_id"),
                "artifact_version_id": o.get("artifact_version_id"),
                "content_hash": o.get("content_hash"),
                "findings": o.get("findings") or [],
                "evidence_aids": o.get("evidence_aids") or [],
            }
            for o in report.get("originals") or []
        ],
        "decisions": [
            {
                "delivery_id": d.get("delivery_id"),
                "artifact_version_id": d.get("artifact_version_id"),
                "content_hash": d.get("content_hash"),
                "verdict": (d.get("verdict") or {}).get("verdict"),
                "delivered": d.get("delivered"),
                "parse_status": (d.get("parse") or {}).get("parse_status"),
                "disposition": dispositions.get(d.get("delivery_id"), "unresolved"),
            }
            for d in report.get("deliveries") or []
        ],
        "disposition_counts": report.get("disposition_counts") or {},
        "trace_references": {
            "run_id": report.get("run_id"),
            "event_ids": [e.get("event_id") for e in report.get("timeline") or []],
        },
        "contains_raw_bytes": False,
        "equated_with_collusion": False,
    }
    package["package_hash"] = _hash(
        {k: v for k, v in package.items() if k != "package_hash"}
    )
    return package


def create_review_export(
    principal: Principal,
    dataset_id: str,
    report: dict[str, Any],
    pin: dict[str, Any],
    audit: AuditLog,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a review package under `export.create` (audited either way)."""
    active_policy = policy if policy is not None else load_runtime_policy()
    if not can(active_policy, principal, dataset_id, "export.create"):
        audit.append(
            actor_id=principal.actor_id,
            action="export.create",
            dataset_id=dataset_id,
            outcome="denied",
            detail={"permission": "export.create"},
        )
        raise PermissionError(
            f"{principal.actor_id} lacks export.create on frozenset({dataset_id})"
        )
    package = build_review_package(
        report, pin, dataset_id=dataset_id, policy=active_policy
    )
    audit.append(
        actor_id=principal.actor_id,
        action="export.create",
        dataset_id=dataset_id,
        outcome="allowed",
        detail={"package_hash": package["package_hash"], "run_id": package["run_id"]},
    )
    return package


def verify_evidence_access(
    store: Any,
    audit: AuditLog,
    *,
    artifact_version_id: str,
) -> dict[str, Any]:
    """Cross-check the audit chain and both access logs for one version."""
    entries = audit.entries
    return {
        "audit_chain_valid": audit.verify_chain(),
        "audit_entries": len(entries),
        "evidence_reads_logged": sum(
            1 for e in entries if e.action == "evidence.read" and e.outcome == "allowed"
        ),
        "denied_attempts_logged": sum(1 for e in entries if e.outcome == "denied"),
        "exports_logged": sum(
            1 for e in entries if e.action == "export.create" and e.outcome == "allowed"
        ),
        "store_access_records": len(store.access_history(artifact_version_id)),
        "store_hash_verified": bool(store.verify(artifact_version_id)),
    }


def run_export_verification() -> dict[str, Any]:
    """Exercise package creation, audited reads and permission denials."""
    from .events import ParseStatus, Verdict
    from .fixtures import build_dataset
    from .gate import InterceptionContext, InterceptionGate
    from .metadata import analyze_all_bytes
    from .pinning import build_pin
    from .report import apply_review, build_run_report
    from .runtime import EvidenceGateway
    from .store import ArtifactStore

    dataset_id = "ds-pilot"
    store = ArtifactStore()
    audit = AuditLog()
    gateway = EvidenceGateway(store, audit)
    gate = InterceptionGate(store)
    fixtures = build_dataset()[:4]
    results = []
    deliveries = {}
    for fixture in fixtures:
        ctx = InterceptionContext(
            run_id="run_export",
            episode_id="ep_1",
            sender_id="agent-a",
        )
        handle = gate.intercept_bytes("R-01", fixture.data, ctx)
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        deliveries[fixture.fixture_id] = delivery.delivery_id
        result = analyze_all_bytes(
            fixture.data,
            artifact_version_id=handle.artifact_version_id,
        )
        results.append(result)
        verdict = Verdict.QUARANTINE if fixture.role == "encoded" else Verdict.FLAG
        gate.record_verdict(delivery.delivery_id, verdict)
        try:
            gate.recipient_access(delivery.delivery_id)
            gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
        except Exception:
            gate.record_parse(delivery.delivery_id, ParseStatus.NOT_OBSERVED)
    report = build_run_report(
        gate.events("run_export"), results, report_id="rpt_export"
    )
    first_delivery = deliveries[fixtures[0].fixture_id]
    report = apply_review(
        report,
        first_delivery,
        reviewer="researcher-1",
        disposition="suspected",
        note="export verification",
    )
    pin = build_pin(fixtures, seeds={"export": 20261033})
    researcher = Principal(
        "researcher-1", frozenset({"researcher"}), frozenset({dataset_id})
    )
    agent = Principal("agent-b", frozenset({"agent"}), frozenset({dataset_id}))
    outsider = Principal(
        "researcher-2", frozenset({"researcher"}), frozenset({"ds-other"})
    )

    version_id = gate.events("run_export")[0].artifact_version_id
    assert version_id is not None  # creation event carries the version id
    read_ok = (
        gateway.read_original(researcher, dataset_id, version_id) == fixtures[0].data
    )
    denials = {}
    for name, principal, fn in (
        (
            "agent_read",
            agent,
            lambda p: gateway.read_original(p, dataset_id, version_id),
        ),
        (
            "agent_export",
            agent,
            lambda p: create_review_export(p, dataset_id, report, pin, audit),
        ),
        (
            "wrong_dataset_read",
            outsider,
            lambda p: gateway.read_original(p, dataset_id, version_id),
        ),
        (
            "wrong_dataset_export",
            outsider,
            lambda p: create_review_export(p, dataset_id, report, pin, audit),
        ),
    ):
        try:
            fn(principal)
            denials[name] = False
        except PermissionError:
            denials[name] = True
    package = create_review_export(researcher, dataset_id, report, pin, audit)
    verification = verify_evidence_access(store, audit, artifact_version_id=version_id)
    return {
        "package": package,
        "package_valid": validate_review_package(package) == [],
        "researcher_read_ok": read_ok,
        "denials": denials,
        "verification": verification,
    }


def validate_review_package(package: dict[str, Any]) -> list[str]:
    """Return validation errors for a review package; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(
        package.get("schema") == EXPORT_PACKAGE_SCHEMA,
        f"schema must be {EXPORT_PACKAGE_SCHEMA}",
    )
    sealed = {k: v for k, v in package.items() if k != "package_hash"}
    need(
        package.get("package_hash") == _hash(sealed),
        "package seal mismatch: contents were tampered with",
    )
    need(
        package.get("contains_raw_bytes") is False,
        "review packages must not contain raw bytes",
    )
    need(not _contains_raw_bytes(package), "review package contains raw-byte material")
    policy = package.get("policy") or {}
    for key in (
        "runtime_policy_id",
        "runtime_policy_version",
        "threshold_config_version",
        "pin_hash",
        "dataset_hash",
    ):
        need(bool(policy.get(key)), f"policy.{key} is required")
    for original in package.get("originals") or []:
        need(
            ids.is_content_hash(original.get("content_hash")),
            "every original needs a sha256 content hash",
        )
        need(
            bool(original.get("artifact_version_id")),
            "every original needs an artifact version id",
        )
    for decision in package.get("decisions") or []:
        need(
            bool(decision.get("disposition")),
            "every decision needs a disposition (unresolved is explicit)",
        )
    need(
        package.get("equated_with_collusion") is False,
        "exports must not equate outcomes with collusion (C-02)",
    )
    return errors
