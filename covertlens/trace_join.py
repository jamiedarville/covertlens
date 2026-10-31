"""Join artifact findings to ordered recipient trace events (CL-16, REV-01).

The join is a pure, read-only projection over one run: CL-7 trace
events, CL-12 gate deliveries (the same events) and CL-13/14/15
analysis results go in; a versioned per-delivery report comes out.
Every attempted delivery in the report carries the original
`content_hash` and, once decided, its `verdict_id` reference —
attempts without a verdict yet are flagged as explicit linkage
errors, never silently dropped. Delivered artifacts link to their
parse event and to the recipient's next action, or carry the
explicit `missing` status (the CL-7 `ParseStatus.MISSING` value for
parse). Findings attach only when the analysis result's content hash
matches the attempted delivery's hash for the exact artifact version:
changed bytes never inherit findings (C-05).

Recipient actions are linked as *candidates*: every delivery served
to the acting recipient before the action remains visible, the
action's own `delivery_id` (when present) is reported as a reference,
and `causation_claimed` is always false. A join shows what could have
informed an action; it never asserts what caused it.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import ids
from .events import Event, EventType, ParseStatus, TraceLog, Verdict
from .parsing import AnalysisResult

JOIN_SCHEMA = "covertlens.trace-join"
JOIN_SCHEMA_VERSION = 1
JOIN_VERSION = "1.0.0"


def _coerce(item: Event | dict[str, Any]) -> Event:
    if isinstance(item, Event):
        return item
    data = dict(item)
    return Event(
        event_type=EventType(data["event_type"]),
        run_id=data["run_id"],
        seq=int(data["seq"]),
        occurred_at=data.get("occurred_at") or "",
        episode_id=data.get("episode_id"),
        artifact_id=data.get("artifact_id"),
        artifact_version_id=data.get("artifact_version_id"),
        content_hash=data.get("content_hash"),
        delivery_id=data.get("delivery_id"),
        verdict_id=data.get("verdict_id"),
        sender_id=data.get("sender_id"),
        recipient_id=data.get("recipient_id"),
        parse_status=(
            ParseStatus(data["parse_status"]) if data.get("parse_status") else None
        ),
        verdict=Verdict(data["verdict"]) if data.get("verdict") else None,
        idempotency_key=data.get("idempotency_key"),
        payload=dict(data.get("payload") or {}),
        schema_version=int(data.get("schema_version") or 1),
    )


def _event_ref(event: Event) -> dict[str, Any]:
    return {"event_id": event.event_id, "seq": event.seq}


def join_trace(
    events: TraceLog | Iterable[Event | dict[str, Any]],
    results: Iterable[AnalysisResult | dict[str, Any]] = (),
) -> dict[str, Any]:
    """Build the REV-01 join report for one run.

    `events` is a CL-7 `TraceLog` or an iterable of `Event` / event
    dicts from a single run (cross-run input raises). `results` are
    CL-13 analysis results (objects or `to_dict()` dicts) whose
    findings should attach to their artifact version's deliveries.
    """
    raw = list(events.events) if isinstance(events, TraceLog) else list(events)
    ordered = sorted((_coerce(e) for e in raw), key=lambda e: e.seq)
    run_ids = {e.run_id for e in ordered}
    if len(run_ids) > 1:
        raise ValueError("events never join across runs (REV-02)")
    run_id = ordered[0].run_id if ordered else (
        events.run_id if isinstance(events, TraceLog) else None
    )

    errors: list[str] = []
    seqs = [e.seq for e in ordered]
    if seqs != sorted(set(seqs)):
        errors.append("duplicate seq values in trace; ordering is ambiguous")

    by_delivery: dict[str, dict[str, Any]] = {}
    attempts: list[Event] = []
    verdicts: dict[str, Event] = {}
    accesses: dict[str, Event] = {}
    parses: dict[str, Event] = {}
    creations: dict[str, Event] = {}
    actions: list[Event] = []
    for event in ordered:
        if event.event_type is EventType.ARTIFACT_CREATED and event.artifact_version_id:
            creations[event.artifact_version_id] = event
        elif event.event_type is EventType.DELIVERY_ATTEMPTED and event.delivery_id:
            attempts.append(event)
        elif event.event_type is EventType.GATE_VERDICT and event.delivery_id:
            verdicts[event.delivery_id] = event
        elif event.event_type is EventType.ARTIFACT_ACCESSED and event.delivery_id:
            accesses[event.delivery_id] = event
        elif event.event_type is EventType.ARTIFACT_PARSED and event.delivery_id:
            parses[event.delivery_id] = event
        elif event.event_type is EventType.RECIPIENT_ACTION:
            actions.append(event)

    # Index findings by artifact version, keeping the claimed hash so a
    # mismatch against the delivery's original hash can be rejected.
    findings_by_version: dict[str, list[dict[str, Any]]] = {}
    result_hash_by_version: dict[str, str] = {}
    unjoined: list[dict[str, Any]] = []
    for item in results:
        data = item.to_dict() if isinstance(item, AnalysisResult) else dict(item)
        version_id = data.get("artifact_version_id")
        digest = data.get("content_hash")
        if not version_id:
            unjoined.append(
                {
                    "artifact_version_id": None,
                    "content_hash": digest,
                    "reason": "analysis result carries no artifact_version_id; "
                    "findings cannot bind to an exact version",
                }
            )
            continue
        result_hash_by_version[version_id] = str(digest)
        findings_by_version.setdefault(version_id, []).extend(
            data.get("findings") or []
        )

    # Candidate inputs per action: deliveries served (accessed) to the
    # acting recipient before the action, plus the referenced delivery.
    action_records: list[dict[str, Any]] = []
    candidates_by_action: dict[str, list[str]] = {}
    for action in actions:
        candidates: list[str] = []
        for attempt in attempts:
            delivery_id = attempt.delivery_id or ""
            access = accesses.get(delivery_id)
            if access is None or access.seq >= action.seq:
                continue
            if (
                action.recipient_id is not None
                and attempt.recipient_id != action.recipient_id
            ):
                continue
            candidates.append(delivery_id)
        if action.delivery_id and action.delivery_id not in candidates:
            referenced = by_attempt(attempts, action.delivery_id)
            if referenced is not None:
                candidates.append(action.delivery_id)
        candidates_by_action[action.event_id] = candidates
        action_records.append(
            {
                "event_id": action.event_id,
                "seq": action.seq,
                "recipient_id": action.recipient_id,
                "referenced_delivery_id": action.delivery_id,
                "candidate_delivery_ids": candidates,
                "candidate_count": len(candidates),
                "causation_claimed": False,
                "linkage_basis": (
                    "deliveries served to the recipient before this action "
                    "(plus the action's delivery reference when present); "
                    "candidates are visible inputs, not a cause"
                ),
            }
        )

    deliveries: list[dict[str, Any]] = []
    for attempt in attempts:
        delivery_id = attempt.delivery_id or ""
        missing: list[str] = []
        digest = attempt.content_hash
        if not digest or not ids.is_content_hash(digest):
            missing.append("content_hash")
            errors.append(f"{delivery_id}: attempted delivery lacks a valid original content_hash")
        verdict_event = verdicts.get(delivery_id)
        if verdict_event is None:
            missing.append("verdict_reference")
            errors.append(f"{delivery_id}: no gate.verdict yet (verdict reference missing)")
        access = accesses.get(delivery_id)
        delivered = access is not None
        parse_event = parses.get(delivery_id)
        if parse_event is not None:
            parse_block: dict[str, Any] = {
                "linkage": "linked",
                "parse_status": (
                    parse_event.parse_status.value
                    if parse_event.parse_status
                    else ParseStatus.MISSING.value
                ),
                **_event_ref(parse_event),
            }
        else:
            parse_block = {
                "linkage": "missing",
                "parse_status": ParseStatus.MISSING.value,
                "event_id": None,
                "seq": None,
            }
            if delivered:
                missing.append("parse_event")
        # Findings bind to the exact version and hash (C-05).
        findings: list[dict[str, Any]] = []
        findings_status = "no_findings_recorded"
        version_id = attempt.artifact_version_id
        claimed = result_hash_by_version.get(version_id or "")
        if version_id in findings_by_version:
            if claimed != digest:
                findings_status = "hash_mismatch_rejected"
                errors.append(
                    f"{delivery_id}: analysis content_hash {claimed} does not "
                    f"match original {digest}; findings not attached (C-05)"
                )
            else:
                findings = list(findings_by_version[version_id])
                findings_status = "linked" if findings else "no_findings_recorded"
        next_actions = [
            {
                **_event_ref(action),
                "linkage": (
                    "referenced" if action.delivery_id == delivery_id else "candidate"
                ),
                "causation_claimed": False,
            }
            for action in actions
            if delivery_id in candidates_by_action.get(action.event_id, [])
            or action.delivery_id == delivery_id
        ]
        if delivered and not next_actions:
            missing.append("next_action")
        deliveries.append(
            {
                "delivery_id": delivery_id,
                "artifact_id": attempt.artifact_id,
                "artifact_version_id": version_id,
                "content_hash": digest,
                "episode_id": attempt.episode_id,
                "sender_id": attempt.sender_id,
                "recipient_id": attempt.recipient_id,
                "attempted": _event_ref(attempt),
                "verdict": (
                    {
                        "verdict_id": verdict_event.verdict_id,
                        "verdict": (
                            verdict_event.verdict.value
                            if verdict_event.verdict
                            else None
                        ),
                        **_event_ref(verdict_event),
                    }
                    if verdict_event is not None
                    else None
                ),
                "verdict_reference_status": (
                    "linked" if verdict_event is not None else "missing"
                ),
                "access": _event_ref(access) if access is not None else None,
                "delivered": delivered,
                "parse": parse_block,
                "findings": findings,
                "findings_status": findings_status,
                "next_action": (
                    next_actions[0]
                    if next_actions
                    else {
                        "linkage": "missing",
                        "event_id": None,
                        "seq": None,
                        "causation_claimed": False,
                    }
                ),
                "next_actions": next_actions,
                "missing": missing,
            }
        )

    known_versions = {d["artifact_version_id"] for d in deliveries} | set(creations)
    for version_id, digest in result_hash_by_version.items():
        if version_id not in known_versions:
            unjoined.append(
                {
                    "artifact_version_id": version_id,
                    "content_hash": digest,
                    "reason": "no attempted delivery or creation for this "
                    "artifact version in the run",
                }
            )

    summary = {
        "attempted_deliveries": len(deliveries),
        "with_verdict_reference": sum(
            1 for d in deliveries if d["verdict_reference_status"] == "linked"
        ),
        "delivered": sum(1 for d in deliveries if d["delivered"]),
        "with_parse": sum(1 for d in deliveries if d["parse"]["linkage"] == "linked"),
        "with_next_action": sum(1 for d in deliveries if d["next_actions"]),
        "with_findings": sum(1 for d in deliveries if d["findings"]),
        "actions": len(action_records),
        "linkage_errors": len(errors),
    }
    return {
        "schema": JOIN_SCHEMA,
        "schema_version": JOIN_SCHEMA_VERSION,
        "join_version": JOIN_VERSION,
        "run_id": run_id,
        "causation_claimed": False,
        "deliveries": deliveries,
        "actions": action_records,
        "unjoined_results": unjoined,
        "errors": errors,
        "summary": summary,
    }


def by_attempt(attempts: list[Event], delivery_id: str) -> Event | None:
    for attempt in attempts:
        if attempt.delivery_id == delivery_id:
            return attempt
    return None


def validate_trace_join(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one join report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == JOIN_SCHEMA, f"schema must be {JOIN_SCHEMA}")
    need(
        report.get("schema_version") == JOIN_SCHEMA_VERSION,
        f"schema_version must be {JOIN_SCHEMA_VERSION}",
    )
    need(bool(report.get("join_version")), "join_version is required")
    need(bool(report.get("run_id")), "run_id is required")
    need(
        report.get("causation_claimed") is False,
        "a trace join never claims causation",
    )
    for i, delivery in enumerate(report.get("deliveries") or []):
        prefix = f"deliveries[{i}]"
        need(bool(delivery.get("delivery_id")), f"{prefix}.delivery_id is required")
        need(
            ids.is_content_hash(delivery.get("content_hash")),
            f"{prefix}.content_hash must be the original sha256 hash (REV-01)",
        )
        need(
            delivery.get("verdict_reference_status") in ("linked", "missing"),
            f"{prefix}.verdict_reference_status must be linked or missing",
        )
        if delivery.get("verdict_reference_status") == "linked":
            need(
                bool((delivery.get("verdict") or {}).get("verdict_id")),
                f"{prefix}.verdict.verdict_id is required when linked",
            )
        parse = delivery.get("parse") or {}
        need(
            parse.get("linkage") in ("linked", "missing"),
            f"{prefix}.parse.linkage must be linked or missing (explicit missing status)",
        )
        if parse.get("linkage") == "missing":
            need(
                parse.get("parse_status") == ParseStatus.MISSING.value,
                f"{prefix}.parse must use the explicit missing status",
            )
        for action in delivery.get("next_actions") or []:
            need(
                action.get("causation_claimed") is False,
                f"{prefix} next_actions must not claim causation",
            )
    for i, action in enumerate(report.get("actions") or []):
        need(
            action.get("causation_claimed") is False,
            f"actions[{i}] must not claim causation",
        )
        need(
            action.get("candidate_count") == len(action.get("candidate_delivery_ids") or []),
            f"actions[{i}].candidate_count must match candidate_delivery_ids",
        )
    summary = report.get("summary") or {}
    need(
        summary.get("attempted_deliveries") == len(report.get("deliveries") or []),
        "summary.attempted_deliveries must match deliveries",
    )
    need(
        summary.get("linkage_errors") == len(report.get("errors") or []),
        "summary.linkage_errors must match errors",
    )
    return errors
