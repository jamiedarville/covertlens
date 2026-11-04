"""Demo review roles, dispositions and sealed exports (CL-59, REV-04/06).

The web app's Reviewer page is a demo surface over the CL-11
evidence gateway, not an authentication system. A demo role
(`viewer`, `researcher`, `reviewer`) maps to a CL-11 `Principal`
scoped to one run-as-dataset:

| Demo role | Principal roles | Evidence permissions (runtime policy) |
|---|---|---|
| `viewer` | `viewer` | none (deny-by-default) |
| `researcher` | `researcher` | original/trace reads, `export.create`, verdict override |
| `reviewer` | `reviewer` | original/trace reads, `candidate.decode.read` |

Only the reviewer holds `candidate.decode.read`, so a
researcher-role request for a geometric candidate decode is denied
by the gateway and appended to the hash-chained audit log. The
candidate text lives only in the gateway's reviewer evidence path:
this module records it there via `EvidenceGateway.record_candidate_decode`
and never copies it into findings, reports, exports or audit details.

`ReviewWorkspace` owns the gateway, the audit log, recorded
candidate decodes and CL-25 dispositions for the web app. When a
database path is given (the persistent gate store), audit entries,
decodes and dispositions survive a restart and the chain still
verifies; without one the workspace is purely in memory. Reports
are rebuilt on demand from the gate's trace plus fresh deterministic
analysis of the stored bytes, then stored dispositions are applied
with `report.apply_review`, so a downloaded package always reflects
the current triage state and passes `validate_review_package`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .gate import InterceptionGate
from .metadata import analyze_all_bytes
from .report import DISPOSITIONS, apply_review, build_run_report
from .review_export import create_review_export
from .runtime import (
    AuditLog,
    EvidenceGateway,
    Principal,
    can,
    load_runtime_policy,
)
from .store import ArtifactStore

DEMO_ROLES = ("viewer", "researcher", "reviewer")
DEMO_ROLE_LABEL = "demo role (not authentication)"


def demo_principal(role: str, dataset_id: str) -> Principal:
    """Map one demo role to its dataset-scoped CL-11 principal."""
    if role not in DEMO_ROLES:
        raise ValueError(f"demo role must be one of {DEMO_ROLES}")
    return Principal(
        actor_id=f"demo-{role}",
        roles=frozenset({role}),
        datasets=frozenset({dataset_id}),
    )


def role_capabilities(policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Demo-role mapping as served to the Reviewer page."""
    active = policy if policy is not None else load_runtime_policy()
    roles = active.get("roles") or {}
    return [
        {
            "role": role,
            "actor_id": f"demo-{role}",
            "label": DEMO_ROLE_LABEL,
            "permissions": sorted((roles.get(role) or {}).get("allow") or []),
        }
        for role in DEMO_ROLES
    ]


class ReviewWorkspace:
    """Gateway + audit + dispositions behind the Reviewer page."""

    def __init__(
        self,
        store: ArtifactStore,
        *,
        db_path: str | Path | None = None,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self._store = store
        self._policy = policy if policy is not None else load_runtime_policy()
        self._audit = AuditLog()
        self._gateway = EvidenceGateway(store, self._audit, policy=self._policy)
        self._reviews: dict[tuple[str, str], dict[str, Any]] = {}
        self._opinions: dict[str, dict[str, Any]] = {}
        self._decode_versions: set[str] = set()
        self._synced = 0
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        if db_path is not None:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(
                str(db_path), check_same_thread=False, isolation_level=None
            )
            self._db.execute("PRAGMA journal_mode=WAL")
            self._init_db()
            self._load_state()

    # -- persistence -----------------------------------------------------

    def _init_db(self) -> None:
        assert self._db is not None
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_audit (
                seq INTEGER PRIMARY KEY,
                entry_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_dispositions (
                run_id TEXT NOT NULL,
                delivery_id TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                disposition TEXT NOT NULL,
                note TEXT NOT NULL,
                demonstrated_basis TEXT,
                PRIMARY KEY (run_id, delivery_id)
            );
            CREATE TABLE IF NOT EXISTS review_decodes (
                decode_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                artifact_version_id TEXT,
                code TEXT,
                text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS review_opinions (
                opinion_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                delivery_id TEXT,
                record_json TEXT NOT NULL
            );
            """
        )

    def _load_state(self) -> None:
        assert self._db is not None
        from .runtime import AuditEntry

        entries = []
        for row in self._db.execute(
            "SELECT seq, entry_id, occurred_at, actor_id, action, dataset_id,"
            " outcome, detail_json, prev_hash, entry_hash"
            " FROM review_audit ORDER BY seq"
        ).fetchall():
            entries.append(
                AuditEntry(
                    seq=row[0],
                    entry_id=row[1],
                    occurred_at=row[2],
                    actor_id=row[3],
                    action=row[4],
                    dataset_id=row[5],
                    outcome=row[6],
                    detail=json.loads(row[7]),
                    prev_hash=row[8],
                    entry_hash=row[9],
                )
            )
        self._audit._entries = entries  # noqa: SLF001 - restore persisted log
        self._synced = len(entries)
        for row in self._db.execute(
            "SELECT run_id, delivery_id, reviewer, disposition, note,"
            " demonstrated_basis FROM review_dispositions"
        ).fetchall():
            self._reviews[(row[0], row[1])] = {
                "reviewer": row[2],
                "disposition": row[3],
                "note": row[4],
                "demonstrated_basis": row[5],
            }
        for row in self._db.execute(
            "SELECT decode_id, dataset_id, artifact_version_id, code, text"
            " FROM review_decodes"
        ).fetchall():
            self._gateway._candidate_decodes[row[0]] = {  # noqa: SLF001
                "decode_id": row[0],
                "dataset_id": row[1],
                "artifact_version_id": row[2],
                "code": row[3],
                "text": row[4],
            }
            if row[2]:
                self._decode_versions.add(row[2])
        for row in self._db.execute(
            "SELECT opinion_id, record_json FROM review_opinions"
        ).fetchall():
            self._opinions[row[0]] = json.loads(row[1])

    def _sync_audit(self) -> None:
        entries = self._audit.entries
        if self._db is not None:
            for entry in entries[self._synced :]:
                self._db.execute(
                    "INSERT OR REPLACE INTO review_audit"
                    " (seq, entry_id, occurred_at, actor_id, action, dataset_id,"
                    " outcome, detail_json, prev_hash, entry_hash)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.seq,
                        entry.entry_id,
                        entry.occurred_at,
                        entry.actor_id,
                        entry.action,
                        entry.dataset_id,
                        entry.outcome,
                        json.dumps(entry.detail, sort_keys=True, default=str),
                        entry.prev_hash,
                        entry.entry_hash,
                    ),
                )
        self._synced = len(entries)

    # -- accessors ---------------------------------------------------------

    @property
    def audit(self) -> AuditLog:
        return self._audit

    @property
    def gateway(self) -> EvidenceGateway:
        return self._gateway

    def disposition(self, run_id: str, delivery_id: str) -> str:
        review = self._reviews.get((run_id, delivery_id))
        return str(review["disposition"]) if review else "unresolved"

    # -- candidate decodes (reviewer evidence path) ------------------------

    def ensure_candidate_decode(
        self,
        run_id: str,
        record: Any,
        *,
        declared_context: dict[str, Any] | None = None,
    ) -> str | None:
        """Record the delivery's candidate decode once; return its ID.

        The geometric report is recomputed deterministically from the
        stored bytes, under the run's declared scene context (CL-78).
        Only the decode ID is returned to callers; the text stays in
        the gateway until a reviewer reads it.
        """
        with self._lock:
            if record.artifact_version_id in self._decode_versions:
                for decode in self._gateway._candidate_decodes.values():  # noqa: SLF001
                    if decode.get("artifact_version_id") == record.artifact_version_id:
                        return str(decode["decode_id"])
                return None
            data = self._store.get_original(
                record.artifact_version_id,
                actor_id="review-analyzer",
                purpose="analysis",
            )
            from .geometric import analyze_geometric_bytes

            candidate = analyze_geometric_bytes(
                data, declared_context=declared_context
            ).get("candidate_decode")
            decode_id = self._gateway.record_candidate_decode(
                run_id, record.artifact_version_id, candidate
            )
            self._decode_versions.add(record.artifact_version_id)
            if decode_id is not None:
                decode = self._gateway._candidate_decodes[decode_id]  # noqa: SLF001
                if self._db is not None:
                    self._db.execute(
                        "INSERT OR REPLACE INTO review_decodes"
                        " (decode_id, dataset_id, artifact_version_id, code, text)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (
                            decode_id,
                            run_id,
                            record.artifact_version_id,
                            decode.get("code"),
                            decode["text"],
                        ),
                    )
            self._sync_audit()
            return decode_id

    def record_candidate_decode(
        self,
        run_id: str,
        artifact_version_id: str | None,
        candidate: dict[str, Any] | None,
    ) -> str | None:
        """Record one candidate decode through the gateway (persisted)."""
        with self._lock:
            decode_id = self._gateway.record_candidate_decode(
                run_id, artifact_version_id, candidate
            )
            if decode_id is not None:
                decode = self._gateway._candidate_decodes[decode_id]  # noqa: SLF001
                if artifact_version_id:
                    self._decode_versions.add(artifact_version_id)
                if self._db is not None:
                    self._db.execute(
                        "INSERT OR REPLACE INTO review_decodes"
                        " (decode_id, dataset_id, artifact_version_id, code, text)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (
                            decode_id,
                            run_id,
                            artifact_version_id,
                            decode.get("code"),
                            decode["text"],
                        ),
                    )
            self._sync_audit()
            return decode_id

    def decode_id_for(self, run_id: str, record: Any) -> str | None:
        with self._lock:
            return self.ensure_candidate_decode(run_id, record)

    def read_candidate_decode(
        self, principal: Principal, run_id: str, decode_id: str
    ) -> dict[str, Any]:
        with self._lock:
            try:
                return self._gateway.read_candidate_decode(principal, run_id, decode_id)
            finally:
                self._sync_audit()

    # -- originals, dispositions, reports, exports --------------------------

    def read_original(
        self, principal: Principal, run_id: str, artifact_version_id: str
    ) -> bytes:
        with self._lock:
            try:
                return self._gateway.read_original(
                    principal, run_id, artifact_version_id, purpose="review"
                )
            finally:
                self._sync_audit()

    def apply_disposition(
        self,
        principal: Principal,
        run_id: str,
        delivery_id: str,
        *,
        disposition: str,
        note: str = "",
        demonstrated_basis: str | None = None,
    ) -> dict[str, Any]:
        """Record one CL-25 disposition (researcher/reviewer; audited)."""
        with self._lock:
            allowed = can(self._policy, principal, run_id, "export.create") or can(
                self._policy, principal, run_id, "candidate.decode.read"
            )
            if not allowed:
                self._audit.append(
                    actor_id=principal.actor_id,
                    action="review.disposition",
                    dataset_id=run_id,
                    outcome="denied",
                    detail={"delivery_id": delivery_id, "disposition": disposition},
                )
                self._sync_audit()
                raise PermissionError(
                    f"{principal.actor_id} may not record review dispositions"
                )
            if disposition not in DISPOSITIONS:
                raise ValueError(f"disposition must be one of {DISPOSITIONS}")
            if disposition == "demonstrated_transfer" and not demonstrated_basis:
                raise ValueError(
                    "demonstrated_transfer requires a recorded basis in "
                    "independent recovery/action evidence; a detector score "
                    "is never sufficient"
                )
            review = {
                "reviewer": principal.actor_id,
                "disposition": disposition,
                "note": note,
                "demonstrated_basis": demonstrated_basis,
            }
            self._reviews[(run_id, delivery_id)] = review
            if self._db is not None:
                self._db.execute(
                    "INSERT OR REPLACE INTO review_dispositions"
                    " (run_id, delivery_id, reviewer, disposition, note,"
                    " demonstrated_basis) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        delivery_id,
                        review["reviewer"],
                        disposition,
                        note,
                        demonstrated_basis,
                    ),
                )
            self._audit.append(
                actor_id=principal.actor_id,
                action="review.disposition",
                dataset_id=run_id,
                outcome="applied",
                detail={"delivery_id": delivery_id, "disposition": disposition},
            )
            self._sync_audit()
            return dict(review)

    # -- second opinions (CL-74..CL-77, advisory only) --------------------

    def record_second_opinion(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._opinions[record["opinion_id"]] = record
            if self._db is not None:
                self._db.execute(
                    "INSERT OR REPLACE INTO review_opinions"
                    " (opinion_id, run_id, delivery_id, record_json)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        record["opinion_id"],
                        record["run_id"],
                        record.get("delivery_id"),
                        json.dumps(record, sort_keys=True, default=str),
                    ),
                )
            return dict(record)

    def second_opinions(
        self, run_id: str, delivery_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(r)
                for r in self._opinions.values()
                if r.get("run_id") == run_id
                and (delivery_id is None or r.get("delivery_id") == delivery_id)
            ]
            return sorted(rows, key=lambda r: str(r.get("created_at")))

    def request_second_opinion(
        self,
        principal: Principal,
        gate: InterceptionGate,
        run_id: str,
        delivery_id: str,
        *,
        provider: Any = None,
        config: Any = None,
        tracker: Any = None,
        include_image: bool = False,
    ) -> dict[str, Any]:
        """Run one advisory opinion for a delivery (CL-77 path).

        Needs `second_opinion.request`. Images leave only when the
        caller asked, the manifest opted the run in, and the
        gateway's `second_opinion.send_image` check passes; every
        allowed send is audited. The verdict and disposition are
        never touched.
        """
        from ._validation import canonical_hash
        from .manifest import load_manifest, second_opinion_allows_images
        from .second_opinion import (
            SecondOpinionConfig,
            provider_from_config,
        )
        from .second_opinion import (
            request_second_opinion as _request,
        )

        with self._lock:
            try:
                if not can(self._policy, principal, run_id, "second_opinion.request"):
                    self._audit.append(
                        actor_id=principal.actor_id,
                        action="second_opinion.request",
                        dataset_id=run_id,
                        outcome="denied",
                        detail={"delivery_id": delivery_id},
                    )
                    raise PermissionError(
                        f"{principal.actor_id} lacks second_opinion.request on {run_id}"
                    )
                record_row = gate.get_delivery(delivery_id)
                report = self.build_report(gate, run_id)
                pin = self.build_pin_for(gate, run_id)
                from .review_export import build_review_package

                package = build_review_package(
                    report, pin, dataset_id=run_id, policy=self._policy
                )
                active_config = config or SecondOpinionConfig.from_env()
                active_provider = (
                    provider
                    if provider is not None
                    else provider_from_config(active_config)
                )
                # Candidate text, if any, is fenced as untrusted data.
                candidate_texts: dict[str, str] = {}
                decode_id = self.ensure_candidate_decode(run_id, record_row)
                if decode_id is not None:
                    decode = self._gateway._candidate_decodes.get(decode_id)  # noqa: SLF001
                    if decode is not None:
                        candidate_texts[delivery_id] = str(decode["text"])
                image_bytes: bytes | None = None
                image_authorized = False
                opt_in = second_opinion_allows_images(load_manifest())
                if include_image and opt_in:
                    data = self._store.get_original(
                        record_row.artifact_version_id,
                        actor_id="second-opinion",
                        purpose="analysis",
                    )
                    image_hash = canonical_hash(
                        {"image_len": len(data), "run_id": run_id}
                    )
                    try:
                        self._gateway.authorize_second_opinion_image(
                            principal,
                            run_id,
                            record_row.artifact_version_id,
                            image_hash,
                        )
                        image_authorized = True
                        image_bytes = data
                    except PermissionError:
                        image_authorized = False
                record = _request(
                    active_provider,
                    active_config,
                    report,
                    package,
                    run_id=run_id,
                    delivery_id=delivery_id,
                    candidate_texts=candidate_texts or None,
                    tracker=tracker,
                    image_bytes=image_bytes,
                    image_opt_in=opt_in,
                    image_authorized=image_authorized,
                )
                self._audit.append(
                    actor_id=principal.actor_id,
                    action="second_opinion.request",
                    dataset_id=run_id,
                    outcome="recorded",
                    detail={
                        "delivery_id": delivery_id,
                        "opinion_id": record["opinion_id"],
                        "status": record["status"],
                        "image_sent": record["image_sent"],
                    },
                )
                stored = self.record_second_opinion(record)
                return stored
            finally:
                self._sync_audit()

    def build_report(self, gate: InterceptionGate, run_id: str) -> dict[str, Any]:
        """Current run report with stored dispositions applied."""
        with self._lock:
            results = []
            for record in gate.deliveries(run_id):
                data = self._store.get_original(
                    record.artifact_version_id,
                    actor_id="review-report",
                    purpose="analysis",
                )
                results.append(
                    analyze_all_bytes(
                        data,
                        artifact_version_id=record.artifact_version_id,
                        declared_context=gate.scene_context(run_id),
                    )
                )
            report = build_run_report(
                gate.events(run_id), results, report_id=f"rpt_{run_id}"
            )
            for (review_run, delivery_id), review in sorted(self._reviews.items()):
                if review_run != run_id:
                    continue
                report = apply_review(
                    report,
                    delivery_id,
                    reviewer=str(review["reviewer"]),
                    disposition=str(review["disposition"]),
                    note=str(review["note"]),
                    demonstrated_basis=review["demonstrated_basis"],
                )
            report["second_opinions"] = self.second_opinions(run_id)
            return report

    def build_pin_for(self, gate: InterceptionGate, run_id: str) -> dict[str, Any]:
        """Pin over the run's distinct artifact versions (CL-26 shape)."""
        from ._validation import canonical_hash
        from .pinning import default_detector_versions
        from .verdicts import DEFAULT_CONFIG

        rows = sorted(
            {
                record.artifact_version_id: record.content_hash
                for record in gate.deliveries(run_id)
            }.items()
        )
        config = DEFAULT_CONFIG
        pin: dict[str, Any] = {
            "schema": "covertlens.pin",
            "schema_version": 1,
            "pin_version": "1.0.0",
            "dataset": {
                "fixture_count": len(rows),
                "dataset_hash": canonical_hash(rows),
                "fixtures": dict(rows),
            },
            "detectors": default_detector_versions(),
            "threshold_config_version": config.version,
            "thresholds_status": {
                family: block.status for family, block in config.families.items()
            },
            "seeds": {"review_export": 20261159},
        }
        pin["pin_hash"] = canonical_hash(
            {k: v for k, v in pin.items() if k != "pin_hash"}
        )
        return pin

    def export_package(
        self, principal: Principal, gate: InterceptionGate, run_id: str
    ) -> dict[str, Any]:
        with self._lock:
            try:
                report = self.build_report(gate, run_id)
                pin = self.build_pin_for(gate, run_id)
                return create_review_export(
                    principal, run_id, report, pin, self._audit, policy=self._policy
                )
            finally:
                self._sync_audit()

    # -- audit ---------------------------------------------------------------

    def audit_payload(self, run_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            entries = [asdict(e) for e in self._audit.entries]
            if run_id is not None:
                entries = [e for e in entries if e["dataset_id"] == run_id]
            return {
                "chain_valid": self._audit.verify_chain(),
                "entries": entries,
                "entry_count": len(entries),
                "denied": sum(1 for e in entries if e["outcome"] == "denied"),
                "head_hash": self._audit.head_hash,
            }


def decode_fingerprint(decode_id: str | None) -> str | None:
    """Short non-text fingerprint for queue payloads (never the text)."""
    if decode_id is None:
        return None
    return "sha256:" + hashlib.sha256(decode_id.encode()).hexdigest()[:12]
