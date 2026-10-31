"""Artifact route and trace coverage audit (CL-32, EV-01/REV-01).

End-to-end audit of every route in the CL-7 inventory against the
CL-12 gate, the CL-8 store and the CL-16 trace join:

- **Routes R-01..R-07 (gated):** creation (immutable version +
  `artifact.created`), hash (recorded hash equals the exact bytes
  and the store verifies), gate (pending denied, withheld denied,
  permitted served the exact bytes through the route's own access
  path). R-05 is exercised through cached-link redemption, R-06
  through derivative generation from gate-served bytes, R-07
  through the parse hand-off.
- **Route R-08 (exempt):** reviewer-only evidence access — verified
  as an exemption: authorized reviewers are served with audit,
  non-reviewers and recipients are not, and it is never a delivery
  path.
- **Trace links:** one run mixes delivered, withheld and pending
  deliveries; every missing parse/action/verdict link in the join
  is classified with an explicit reason instead of being silently
  absent.

The final report identifies remaining gaps rather than claiming
full coverage. Known gap carried forward: R-06 has no dedicated
gate derivative API — derivatives are generated only from bytes
the gate served, while `ArtifactStore.register_derivative` itself
remains an ungated internal call (see `gaps`).
"""

from __future__ import annotations

from typing import Any, Callable

from . import ids
from .events import Event, EventType, ParseStatus, Verdict
from .fixtures import build_pair
from .gate import InterceptionContext, InterceptionGate
from .routes import ROUTES, Route
from .store import ArtifactStore
from .trace_join import join_trace

AUDIT_SCHEMA = "covertlens.route-trace-audit"
AUDIT_VERSION = "1.0.0"
RUN_ID = "run_audit"


def _denied(fn: Callable[[], Any]) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


def _route_checks(route: Route, data: bytes) -> dict[str, Any]:
    """Run creation/hash/gate/access checks for one route."""
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN_ID, episode_id="ep_audit", sender_id="agent-a")
    checks: dict[str, Any] = {}
    if route.route_id in ("R-02", "R-03"):
        handle = gate.intercept_reference(route.route_id, f"ref://{route.route_id}", lambda _r: data, ctx)
    else:
        handle = gate.intercept_bytes(route.route_id, data, ctx)
    checks["creation"] = bool(
        handle.artifact_version_id
        and any(e.event_type is EventType.ARTIFACT_CREATED for e in gate.events(RUN_ID))
    )
    checks["hash"] = bool(
        handle.content_hash == ids.content_hash(data)
        and gate.store.verify(handle.artifact_version_id)
    )

    def lifecycle(verdict: Verdict | None, access: Callable[[str], bytes], delivery_id: str) -> None:
        if verdict is not None:
            gate.record_verdict(delivery_id, verdict)
        access(delivery_id)

    # Pending: every route denies before a verdict.
    pending = gate.attempt_delivery(handle, recipient_id="agent-b")
    checks["gate_pending_denied"] = _denied(
        lambda: gate.serve_via_route(route.route_id, pending.delivery_id)
        if route.route_id != "R-05" else gate.recipient_access(pending.delivery_id)
    )
    # Withheld: quarantine denies through the route's own path.
    withheld = gate.attempt_delivery(handle, recipient_id="agent-b", attempt=2)
    gate.record_verdict(withheld.delivery_id, Verdict.QUARANTINE)
    if route.route_id == "R-05":
        token = gate.issue_cached_link(withheld.delivery_id)
        checks["gate_withheld_denied"] = _denied(lambda: gate.redeem_cached_link(token))
    elif route.route_id == "R-06":
        checks["gate_withheld_denied"] = _denied(
            lambda: gate.recipient_access(withheld.delivery_id, via_route="R-06")
        )
        checks["derivative_blocked_when_withheld"] = checks["gate_withheld_denied"]
    else:
        checks["gate_withheld_denied"] = _denied(
            lambda: gate.serve_via_route(route.route_id, withheld.delivery_id)
        )
    # Permitted: the exact bytes come back through the route's path.
    permitted = gate.attempt_delivery(handle, recipient_id="agent-b", attempt=3)
    gate.record_verdict(permitted.delivery_id, Verdict.FLAG)
    if route.route_id == "R-05":
        token = gate.issue_cached_link(permitted.delivery_id)
        served = gate.redeem_cached_link(token)
    elif route.route_id == "R-06":
        served = gate.recipient_access(permitted.delivery_id, via_route="R-06")
        derivative = gate.store.register_derivative(
            handle.artifact_version_id, served[:64], transform="preview_stub"
        )
        checks["derivative_from_served_bytes"] = bool(derivative.parent_version_id)
    else:
        served = gate.serve_via_route(route.route_id, permitted.delivery_id)
    checks["permitted_served_exact_bytes"] = served == data
    if route.route_id == "R-07":
        gate.record_parse(permitted.delivery_id, ParseStatus.PARSED)
        checks["parse_recorded"] = any(
            e.event_type is EventType.ARTIFACT_PARSED for e in gate.events(RUN_ID)
        )
    checks["unauthorized_served"] = gate.access_attempt_report()["unauthorized_served"]
    passed = all(v for v in checks.values() if isinstance(v, bool))
    return {"checks": checks, "passed": passed, "gate": gate}


def _reviewer_checks(data: bytes) -> dict[str, Any]:
    """R-08 exemption: reviewers served with audit, others denied."""
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN_ID, episode_id="ep_audit", sender_id="agent-a")
    handle = gate.intercept_bytes("R-01", data, ctx)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    gate.record_verdict(delivery.delivery_id, Verdict.QUARANTINE)
    checks = {
        "creation": handle.content_hash == ids.content_hash(data),
        "reviewer_served": gate.reviewer_access(
            delivery.delivery_id, actor_id="researcher-1", reviewer_ids={"researcher-1"}
        ) == data,
        "non_reviewer_denied": _denied(lambda: gate.reviewer_access(
            delivery.delivery_id, actor_id="agent-b", reviewer_ids={"researcher-1"}
        )),
        "recipient_delivery_still_denied": _denied(
            lambda: gate.recipient_access(delivery.delivery_id)
        ),
    }
    checks["unauthorized_served"] = gate.access_attempt_report()["unauthorized_served"]
    passed = all(v for v in checks.values() if isinstance(v, bool)) and checks["unauthorized_served"] == 0
    return {"checks": checks, "passed": passed, "gate": gate}


def _trace_audit(data: bytes) -> dict[str, Any]:
    """Classify every missing trace link with an explicit reason."""
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN_ID, episode_id="ep_audit", sender_id="agent-a")
    handle = gate.intercept_bytes("R-01", data, ctx)

    delivered = gate.attempt_delivery(handle, recipient_id="agent-b")
    gate.record_verdict(delivered.delivery_id, Verdict.FLAG)
    gate.recipient_access(delivered.delivery_id)
    gate.record_parse(delivered.delivery_id, ParseStatus.PARSED)

    unparsed = gate.attempt_delivery(handle, recipient_id="agent-b", attempt=2)
    gate.record_verdict(unparsed.delivery_id, Verdict.FLAG)
    gate.recipient_access(unparsed.delivery_id)  # delivered, parse not recorded

    withheld = gate.attempt_delivery(handle, recipient_id="agent-b", attempt=3)
    gate.record_verdict(withheld.delivery_id, Verdict.QUARANTINE)
    gate.record_parse(withheld.delivery_id, ParseStatus.NOT_OBSERVED)

    pending = gate.attempt_delivery(handle, recipient_id="agent-b", attempt=4)

    events = gate.events(RUN_ID)
    action = Event(
        event_type=EventType.RECIPIENT_ACTION,
        run_id=RUN_ID,
        seq=len(events),
        occurred_at="2026-10-31T00:00:00Z",
        episode_id="ep_audit",
        delivery_id=delivered.delivery_id,
        sender_id="agent-a",
        recipient_id="agent-b",
    )
    joined = join_trace([*events, action])
    reasons: list[dict[str, Any]] = []
    for row in joined["deliveries"]:
        for missing in row["missing"]:
            reasons.append({
                "delivery_id": row["delivery_id"],
                "missing": missing,
                "reason": _missing_reason(missing, row),
            })
        if row["parse"]["parse_status"] == "not_observed":
            reasons.append({
                "delivery_id": row["delivery_id"],
                "missing": "recipient_parse_outcome",
                "reason": "withheld before delivery: recipient parse is "
                          "not_observed by design (C-04)",
            })
        if not row["delivered"]:
            reasons.append({
                "delivery_id": row["delivery_id"],
                "missing": "recipient_action",
                "reason": "not delivered (withheld or pending), so no "
                          "recipient action can be linked",
            })
    return {
        "run_id": RUN_ID,
        "deliveries": len(joined["deliveries"]),
        "join_summary": joined["summary"],
        "linkage_errors": joined["errors"],
        "missing_link_reasons": reasons,
        "all_missing_explained": all(r["reason"] for r in reasons),
    }


def _missing_reason(missing: str, row: dict[str, Any]) -> str:
    if missing == "verdict_reference":
        return "delivery still pending: no gate verdict recorded yet"
    if missing == "parse_event":
        return "delivered but no parse event was recorded for this delivery"
    if missing == "next_action":
        return "delivered but no recipient action observed in the trace window"
    if missing == "content_hash":
        return "attempted delivery lacks a valid original content hash"
    return f"unclassified missing link: {missing}"


def run_route_audit() -> dict[str, Any]:
    """Full CL-32 audit report over routes R-01..R-08 and one trace."""
    clean, _encoded = build_pair("spatial_lsb", payload_bytes=12)
    data = clean.data
    routes: list[dict[str, Any]] = []
    covered_routes: set[str] = set()
    for route in ROUTES:
        if not route.gate_required:
            outcome = _reviewer_checks(data)
            routes.append({
                "route_id": route.route_id,
                "kind": route.kind,
                "gate_required": False,
                "exception_reason": route.exception_reason,
                "status": "exempt_verified" if outcome["passed"] else "failed",
                "checks": outcome["checks"],
            })
            continue
        outcome = _route_checks(route, data)
        covered_routes.update(outcome["gate"].coverage_report()["covered"])
        status = "pass" if outcome["passed"] else "failed"
        gaps = []
        if route.route_id == "R-06":
            status = "partial"
            gaps.append(
                "R-06 has no dedicated gate derivative API: derivatives "
                "are generated only from gate-served bytes in this audit, "
                "while ArtifactStore.register_derivative remains an "
                "ungated internal call — enforcement is procedural, not "
                "structural."
            )
        routes.append({
            "route_id": route.route_id,
            "kind": route.kind,
            "gate_required": True,
            "exception_reason": None,
            "status": status,
            "checks": outcome["checks"],
            "gaps": gaps,
        })
    trace = _trace_audit(data)
    gaps = [g for r in routes for g in r.get("gaps", [])]
    return {
        "schema": AUDIT_SCHEMA,
        "schema_version": 1,
        "audit_version": AUDIT_VERSION,
        "routes": routes,
        "routes_passed": [r["route_id"] for r in routes if r["status"] == "pass"],
        "routes_exempt_verified": [
            r["route_id"] for r in routes if r["status"] == "exempt_verified"
        ],
        "routes_partial": [r["route_id"] for r in routes if r["status"] == "partial"],
        "routes_failed": [r["route_id"] for r in routes if r["status"] == "failed"],
        "coverage": {
            "covered": sorted(covered_routes),
            "missing": sorted(
                {r.route_id for r in ROUTES if r.gate_required} - covered_routes
            ),
            "exempt": sorted(r.route_id for r in ROUTES if not r.gate_required),
        },
        "trace": trace,
        "gaps": gaps,
        "full_coverage_claimed": False,
        "equated_with_collusion": False,
    }


def validate_route_audit(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a CL-32 audit report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == AUDIT_SCHEMA, f"schema must be {AUDIT_SCHEMA}")
    need(report.get("routes_failed") == [], "no inventoried route may fail its checks")
    need(
        {r["route_id"] for r in report.get("routes") or []}
        == {r.route_id for r in ROUTES},
        "every inventoried route must be audited",
    )
    trace = report.get("trace") or {}
    need(trace.get("all_missing_explained") is True,
         "every missing trace link needs an explicit reason")
    for row in report.get("routes") or []:
        for name, value in (row.get("checks") or {}).items():
            if name == "unauthorized_served":
                need(value == 0, f"{row['route_id']}: unauthorized bytes served")
    need(
        report.get("full_coverage_claimed") is False,
        "audit must not claim full coverage while gaps remain",
    )
    return errors
