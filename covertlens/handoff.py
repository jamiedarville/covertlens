"""Operations, rollback and researcher handoff verification (CL-36, OPS-09).

The runbook (`docs/operations-runbook.md`) makes operational
claims; this module exercises the load-bearing ones end to end so
the handoff is verified, not just written:

- **Threshold operations:** the shipped `frozen-1.0.0` decides
  enforceably; a pin built under it drifts detectably when the
  threshold config changes (CL-26 `pin_differences` names the
  field), and rolling back to the pre-freeze shipped config
  restores log-only behaviour. Threshold changes are new freezes,
  never in-place edits.
- **Quarantine handling:** quarantined deliveries deny recipients,
  stay readable to authorized reviewers, and their verdict is
  immutable once recorded; a verdict override goes through the
  CL-11 gateway with a recorded reason (agents cannot override).
- **Infrastructure errors:** oversized input is withheld as
  `failed_infrastructure` with no clean verdict (CL-19/CL-29
  checks reused).
- **Reruns:** seeded replay is exactly repeatable and the
  deterministic pipeline reproduces verdicts (CL-21/CL-26).
- **Dataset retirement:** the CL-11 lifecycle — operator request,
  different-approver approval (self-approval denied), then
  execution returning the reproducibility bundle before deletion.

Retention rule throughout: original bytes and evidence stay
internal for the dataset lifetime (C-01); exports carry hashes and
references, never bytes (CL-33).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .calibration import load_frozen_thresholds
from .events import Verdict
from .fixtures import build_dataset
from .gate import InterceptionContext, InterceptionGate
from .latency import limit_behavior_checks
from .pinning import build_pin, pin_differences, verify_reproducibility
from .replay import run_replay
from .runtime import AuditLog, DatasetRetirement, EvidenceGateway, Principal
from .store import ArtifactStore
from .verdicts import DEFAULT_CONFIG, decide_verdict

HANDOFF_SCHEMA = "covertlens.ops-handoff"
HANDOFF_VERSION = "1.0.0"
RUNBOOK_PATH = "docs/operations-runbook.md"


def _threshold_ops(fixtures: list) -> dict[str, Any]:
    from .parsing import Finding

    frozen, _doc = load_frozen_thresholds()
    pin = build_pin(fixtures, threshold_config=frozen, seeds={"campaign": 1})
    drift = pin_differences(
        pin, fixtures, threshold_config=DEFAULT_CONFIG, seeds={"campaign": 1}
    )
    finding = Finding(
        family="metadata",
        detector_name="metadata-ancillary-entries",
        detector_version="1.0.0",
        score=0.95,
        coverage={"entries": 1},
    )
    enforced = decide_verdict([finding], frozen)
    rolled_back = decide_verdict([finding], DEFAULT_CONFIG)
    return {
        "frozen_config_version": frozen.version,
        "frozen_enforceable": enforced.enforceable,
        "frozen_verdict_at_0.95": enforced.verdict.value,
        "drift_fields_when_config_changes": drift,
        "rollback_config_version": DEFAULT_CONFIG.version,
        "rollback_verdict_at_0.95": rolled_back.verdict.value,
        "rollback_enforceable": rolled_back.enforceable,
        "change_rule": "threshold changes ship as a new freeze "
        "version plus a new pin; never edit a frozen "
        "config in place",
    }


def _quarantine_handling() -> dict[str, Any]:
    store = ArtifactStore()
    audit = AuditLog()
    gateway = EvidenceGateway(store, audit)
    gate = InterceptionGate(store)
    fixture = build_dataset()[0]
    ctx = InterceptionContext(
        run_id="run_handoff", episode_id="ep_1", sender_id="agent-a"
    )
    handle = gate.intercept_bytes("R-01", fixture.data, ctx)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    gate.record_verdict(delivery.delivery_id, Verdict.QUARANTINE)

    def denied(fn) -> bool:
        try:
            fn()
        except Exception:
            return True
        return False

    immutable = denied(lambda: gate.record_verdict(delivery.delivery_id, Verdict.FLAG))
    researcher = Principal(
        "researcher-1", frozenset({"researcher"}), frozenset({"ds-ops"})
    )
    agent = Principal("agent-b", frozenset({"agent"}), frozenset({"ds-ops"}))
    override = gateway.record_override(
        researcher,
        "ds-ops",
        "vrd_handoff",
        "flag",
        reason="handoff verification override",
    )
    return {
        "recipient_denied": denied(lambda: gate.recipient_access(delivery.delivery_id)),
        "reviewer_served": gate.reviewer_access(
            delivery.delivery_id,
            actor_id="researcher-1",
            reviewer_ids={"researcher-1"},
        )
        == fixture.data,
        "verdict_immutable_once_recorded": immutable,
        "override_recorded_with_reason": override["reason"]
        == "handoff verification override",
        "agent_override_denied": denied(
            lambda: gateway.record_override(
                agent, "ds-ops", "vrd_handoff", "log", reason="agent attempt"
            )
        ),
        "audit_chain_valid": audit.verify_chain(),
    }


def _reruns(fixtures: list) -> dict[str, Any]:
    frozen, _doc = load_frozen_thresholds()
    first = run_replay(fixtures)
    second = run_replay(fixtures)
    repro = verify_reproducibility(fixtures[:4], threshold_config=frozen, repetitions=2)
    return {
        "replay_repeatable": first["by_condition"] == second["by_condition"]
        and first["trials"] == second["trials"],
        "reproducibility_exact": repro["exact_reproduction"],
        "reproducibility_within_bounds": repro["within_bounds"],
    }


def _retirement(fixtures: list) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        store = ArtifactStore(Path(tmp))
        for fixture in fixtures[:2]:
            store.put_original(
                fixture.data,
                run_id="run_handoff",
                producer_id="agent-a",
            )
        audit = AuditLog()
        lifecycle = DatasetRetirement(store, audit, store_root=Path(tmp))
        operator = Principal(
            "operator-1", frozenset({"operator"}), frozenset({"ds-ops"})
        )
        approver = Principal(
            "approver-1", frozenset({"approver"}), frozenset({"ds-ops"})
        )
        lifecycle.request(operator, "ds-ops", reason="handoff verification")
        self_approval_denied = False
        try:
            lifecycle.approve(
                Principal("operator-1", frozenset({"approver"}), frozenset({"ds-ops"})),
                "ds-ops",
            )
        except PermissionError:
            self_approval_denied = True
        lifecycle.approve(approver, "ds-ops")
        bundle = lifecycle.execute(approver, "ds-ops")
        return {
            "self_approval_denied": self_approval_denied,
            "final_state": lifecycle.state,
            "bundle_content_hashes": len(bundle["content_hashes"]),
            "bundle_has_audit_head": bundle["audit_head"].startswith("sha256:"),
            "audit_chain_valid": audit.verify_chain(),
        }


def run_handoff_verification() -> dict[str, Any]:
    """Exercise every load-bearing runbook claim; return the report."""
    fixtures = build_dataset()
    limits = limit_behavior_checks()
    return {
        "schema": HANDOFF_SCHEMA,
        "schema_version": 1,
        "handoff_version": HANDOFF_VERSION,
        "runbook": RUNBOOK_PATH,
        "release_decision": "release_with_limitations",
        "threshold_operations": _threshold_ops(fixtures),
        "quarantine_handling": _quarantine_handling(),
        "infrastructure_errors": {
            "timeout_status": limits["timeout_status"],
            "oversized_status": limits["oversized_status"],
            "enforcement_run_outcome": limits["enforcement_run_outcome"],
            "enforcement_clean_verdict": limits["enforcement_clean_verdict"],
            "delivery_withheld": limits["delivery_withheld"],
        },
        "reruns": _reruns(fixtures),
        "dataset_retirement": _retirement(fixtures),
        "retention_rule": "original bytes and evidence stay internal "
        "for the dataset lifetime (C-01); exports "
        "carry hashes/references, never bytes",
        "equated_with_collusion": False,
    }


def validate_handoff(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a CL-36 report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == HANDOFF_SCHEMA, f"schema must be {HANDOFF_SCHEMA}")
    thresholds = report.get("threshold_operations") or {}
    need(
        thresholds.get("frozen_enforceable") is True,
        "frozen config must be enforceable",
    )
    need(
        thresholds.get("rollback_enforceable") is False,
        "rollback target (shipped config) must be log-only",
    )
    need(
        "threshold_config_version"
        in (thresholds.get("drift_fields_when_config_changes") or []),
        "pin drift must name the threshold config change",
    )
    quarantine = report.get("quarantine_handling") or {}
    for key in (
        "recipient_denied",
        "reviewer_served",
        "verdict_immutable_once_recorded",
        "override_recorded_with_reason",
        "agent_override_denied",
        "audit_chain_valid",
    ):
        need(quarantine.get(key) is True, f"quarantine_handling.{key} must hold")
    infra = report.get("infrastructure_errors") or {}
    need(infra.get("delivery_withheld") is True, "infrastructure errors must withhold")
    need(
        infra.get("enforcement_clean_verdict") is False,
        "infrastructure errors must not produce a clean verdict",
    )
    reruns = report.get("reruns") or {}
    need(reruns.get("replay_repeatable") is True, "seeded replay must be repeatable")
    need(
        reruns.get("reproducibility_within_bounds") is True,
        "pipeline must reproduce verdicts within bounds",
    )
    retirement = report.get("dataset_retirement") or {}
    need(
        retirement.get("self_approval_denied") is True,
        "retirement self-approval must be denied",
    )
    need(
        retirement.get("final_state") == "deleted",
        "retirement must reach the deleted state in verification",
    )
    need(
        report.get("equated_with_collusion") is False,
        "handoff must not equate outcomes with collusion (C-02)",
    )
    return errors
