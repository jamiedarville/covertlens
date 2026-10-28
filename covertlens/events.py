"""Harness event contracts with stable IDs (CL-7, EV-01).

Five event families are required by CL-7 — creation, attempted delivery,
access/parse, action, run finalization — plus the gate verdict that links
analysis to delivery. Events are ordered by a per-run sequence number,
never join across runs, and pre-delivery verdicts may only cite evidence
that already exists (no lookahead, C-03). Withheld artifacts report parse
``not_observed``, never a successful transfer (C-04).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from . import ids

SCHEMA_VERSION = 1


class EventType(str, Enum):
    ARTIFACT_CREATED = "artifact.created"
    DELIVERY_ATTEMPTED = "delivery.attempted"
    GATE_VERDICT = "gate.verdict"
    ARTIFACT_ACCESSED = "artifact.accessed"
    ARTIFACT_PARSED = "artifact.parsed"
    RECIPIENT_ACTION = "recipient.action"
    RUN_FINALIZED = "run.finalized"


# The five families named in the CL-7 acceptance criteria.
REQUIRED_FAMILIES: dict[str, EventType] = {
    "creation": EventType.ARTIFACT_CREATED,
    "attempted_delivery": EventType.DELIVERY_ATTEMPTED,
    "access_parse": EventType.ARTIFACT_PARSED,
    "action": EventType.RECIPIENT_ACTION,
    "run_finalization": EventType.RUN_FINALIZED,
}


class Verdict(str, Enum):
    LOG = "log"
    FLAG = "flag"
    QUARANTINE = "quarantine"
    FAIL_RUN = "fail_run"


class ParseStatus(str, Enum):
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"
    NOT_OBSERVED = "not_observed"  # withheld/blocked: never "transferred" (C-04)
    MISSING = "missing"


@dataclass
class Event:
    event_type: EventType
    run_id: str
    seq: int
    occurred_at: str
    episode_id: str | None = None
    artifact_id: str | None = None
    artifact_version_id: str | None = None
    content_hash: str | None = None
    delivery_id: str | None = None
    verdict_id: str | None = None
    sender_id: str | None = None
    recipient_id: str | None = None
    parse_status: ParseStatus | None = None
    verdict: Verdict | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @property
    def event_id(self) -> str:
        return ids.event_id(self.run_id, self.seq, self.event_type.value, self.idempotency_key)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["parse_status"] = self.parse_status.value if self.parse_status else None
        data["verdict"] = self.verdict.value if self.verdict else None
        data["event_id"] = self.event_id
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


def validate_event(event: Event | dict[str, Any]) -> list[str]:
    """Return validation errors for one event; empty means valid."""
    data = event.to_dict() if isinstance(event, Event) else dict(event)
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    try:
        etype = EventType(data.get("event_type"))
    except ValueError:
        return [f"unknown event_type: {data.get('event_type')!r}"]
    need(bool(data.get("run_id")), "run_id is required")
    need(isinstance(data.get("seq"), int) and data["seq"] >= 0, "seq must be an int >= 0")
    need(bool(data.get("occurred_at")), "occurred_at is required")
    eid = data.get("event_id")
    if eid is not None:
        need(ids.is_event_id(eid), "event_id must match evt_<32 hex>")
    digest = data.get("content_hash")
    if digest is not None:
        need(ids.is_content_hash(digest), "content_hash must be sha256:<hex>")

    if etype is EventType.ARTIFACT_CREATED:
        need(bool(data.get("artifact_id")), "artifact.created requires artifact_id")
        need(bool(data.get("artifact_version_id")), "artifact.created requires artifact_version_id")
        need(bool(digest), "artifact.created requires content_hash of original bytes")
    if etype is EventType.DELIVERY_ATTEMPTED:
        need(bool(data.get("delivery_id")), "delivery.attempted requires delivery_id")
        need(bool(digest), "delivery.attempted requires original content_hash (REV-01)")
        need(bool(data.get("sender_id")) and bool(data.get("recipient_id")),
             "delivery.attempted requires sender_id and recipient_id")
    if etype is EventType.GATE_VERDICT:
        need(bool(data.get("verdict_id")), "gate.verdict requires verdict_id")
        need(data.get("verdict") in {v.value for v in Verdict},
             "gate.verdict requires a verdict-ladder value")
        need(bool(data.get("delivery_id")), "gate.verdict requires delivery_id")
    if etype is EventType.ARTIFACT_ACCESSED:
        need(bool(data.get("delivery_id")), "artifact.accessed requires delivery_id")
    if etype is EventType.ARTIFACT_PARSED:
        need(data.get("parse_status") in {p.value for p in ParseStatus},
             "artifact.parsed requires parse_status")
    if etype is EventType.RUN_FINALIZED:
        need(data.get("payload", {}).get("outcome") in
             ("completed", "failed_detection", "failed_infrastructure", "aborted"),
             "run.finalized requires payload.outcome")
    return errors


class TraceLog:
    """Ordered, single-run event log enforcing CL-7 ordering invariants."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._events: list[Event] = []
        self._seen_ids: set[str] = set()
        self._finalized = False

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def append(self, event: Event) -> Event:
        """Append an event, rejecting cross-run, out-of-order or duplicate input."""
        problems = validate_event(event)
        if problems:
            raise ValueError("; ".join(problems))
        if event.run_id != self.run_id:
            raise ValueError("events never join across runs (REV-02)")
        if self._finalized:
            raise ValueError("no events after run.finalized")
        expected = len(self._events)
        if event.seq != expected:
            raise ValueError(f"seq must be {expected} (monotonic per run), got {event.seq}")
        if event.event_id in self._seen_ids:
            raise ValueError(f"duplicate event_id {event.event_id} (idempotent retry?)")
        # No lookahead (C-03): a verdict may only reference deliveries already attempted.
        if event.event_type is EventType.GATE_VERDICT:
            attempted = {e.delivery_id for e in self._events
                         if e.event_type is EventType.DELIVERY_ATTEMPTED}
            if event.delivery_id not in attempted:
                raise ValueError("gate.verdict precedes its delivery.attempted (lookahead)")
        # Withheld deliveries must not later claim a successful parse (C-04).
        if event.event_type is EventType.ARTIFACT_PARSED:
            verdicts = {e.delivery_id: e.verdict for e in self._events
                        if e.event_type is EventType.GATE_VERDICT}
            verdict = verdicts.get(event.delivery_id)
            if verdict in (Verdict.QUARANTINE, Verdict.FAIL_RUN) \
                    and event.parse_status is not ParseStatus.NOT_OBSERVED:
                raise ValueError("withheld artifact parse must be not_observed (C-04)")
        self._events.append(event)
        self._seen_ids.add(event.event_id)
        if event.event_type is EventType.RUN_FINALIZED:
            self._finalized = True
        return event
