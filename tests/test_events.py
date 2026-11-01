"""CL-7 AC2: creation, attempted-delivery, access/parse, action and
run-finalization events have stable IDs."""

import pytest

from covertlens import ids
from covertlens.events import (
    REQUIRED_FAMILIES,
    Event,
    EventType,
    ParseStatus,
    TraceLog,
    Verdict,
    validate_event,
)

RUN = ids.new_run_id()
HASH = ids.content_hash(b"fake-png-bytes")
ART = ids.new_artifact_id()
VER = ids.artifact_version_id(ART, HASH)
DLV = ids.delivery_id(RUN, VER, "agent-b", 1)
TS = "2026-10-28T12:00:00Z"


def ev(etype, seq, **kw):
    return Event(etype, RUN, seq, TS, **kw)


def test_all_five_required_families_exist():
    assert REQUIRED_FAMILIES == {
        "creation": EventType.ARTIFACT_CREATED,
        "attempted_delivery": EventType.DELIVERY_ATTEMPTED,
        "access_parse": EventType.ARTIFACT_PARSED,
        "action": EventType.RECIPIENT_ACTION,
        "run_finalization": EventType.RUN_FINALIZED,
    }


def test_event_ids_are_stable_and_deterministic():
    a = ev(
        EventType.ARTIFACT_CREATED,
        0,
        artifact_id=ART,
        artifact_version_id=VER,
        content_hash=HASH,
    )
    b = ev(
        EventType.ARTIFACT_CREATED,
        0,
        artifact_id=ART,
        artifact_version_id=VER,
        content_hash=HASH,
    )
    assert a.event_id == b.event_id
    assert ids.is_event_id(a.event_id)
    assert a.to_dict()["event_id"] == a.event_id


def test_content_hash_and_version_binding():
    assert ids.is_content_hash(HASH)
    assert ids.content_hash(b"fake-png-bytes") == HASH
    assert ids.content_hash(b"other-bytes") != HASH
    with pytest.raises(ValueError):
        ids.artifact_version_id(ART, "not-a-hash")


def test_delivery_id_is_retry_stable():
    assert ids.delivery_id(RUN, VER, "agent-b", 1) == DLV
    assert ids.delivery_id(RUN, VER, "agent-b", 2) != DLV


def test_each_family_validates_with_its_required_fields():
    cases = [
        ev(
            EventType.ARTIFACT_CREATED,
            0,
            artifact_id=ART,
            artifact_version_id=VER,
            content_hash=HASH,
        ),
        ev(
            EventType.DELIVERY_ATTEMPTED,
            1,
            delivery_id=DLV,
            content_hash=HASH,
            sender_id="agent-a",
            recipient_id="agent-b",
        ),
        ev(
            EventType.GATE_VERDICT,
            2,
            delivery_id=DLV,
            verdict_id=ids.new_verdict_id(),
            verdict=Verdict.FLAG,
        ),
        ev(EventType.ARTIFACT_ACCESSED, 3, delivery_id=DLV),
        ev(
            EventType.ARTIFACT_PARSED,
            4,
            delivery_id=DLV,
            parse_status=ParseStatus.PARSED,
        ),
        ev(
            EventType.RECIPIENT_ACTION, 5, delivery_id=DLV, payload={"action": "answer"}
        ),
        ev(EventType.RUN_FINALIZED, 6, payload={"outcome": "completed"}),
    ]
    for event in cases:
        assert validate_event(event) == [], event


def test_creation_without_hash_is_rejected():
    bad = ev(EventType.ARTIFACT_CREATED, 0, artifact_id=ART, artifact_version_id=VER)
    assert any("content_hash" in e for e in validate_event(bad))


def test_full_run_trace_orders_and_finalizes():
    log = TraceLog(RUN)
    log.append(
        ev(
            EventType.ARTIFACT_CREATED,
            0,
            artifact_id=ART,
            artifact_version_id=VER,
            content_hash=HASH,
        )
    )
    log.append(
        ev(
            EventType.DELIVERY_ATTEMPTED,
            1,
            delivery_id=DLV,
            content_hash=HASH,
            sender_id="agent-a",
            recipient_id="agent-b",
        )
    )
    log.append(
        ev(
            EventType.GATE_VERDICT,
            2,
            delivery_id=DLV,
            verdict_id=ids.new_verdict_id(),
            verdict=Verdict.QUARANTINE,
        )
    )
    log.append(
        ev(
            EventType.ARTIFACT_PARSED,
            3,
            delivery_id=DLV,
            parse_status=ParseStatus.NOT_OBSERVED,
        )
    )
    log.append(ev(EventType.RUN_FINALIZED, 4, payload={"outcome": "completed"}))
    assert [e.seq for e in log.events] == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError, match="run.finalized"):
        log.append(ev(EventType.RECIPIENT_ACTION, 5))


def test_out_of_order_and_cross_run_events_are_rejected():
    log = TraceLog(RUN)
    with pytest.raises(ValueError, match="seq must be 0"):
        log.append(ev(EventType.RUN_FINALIZED, 3, payload={"outcome": "completed"}))
    other = Event(
        EventType.ARTIFACT_CREATED,
        ids.new_run_id(),
        0,
        TS,
        artifact_id=ART,
        artifact_version_id=VER,
        content_hash=HASH,
    )
    with pytest.raises(ValueError, match="across runs"):
        log.append(other)


def test_verdict_before_attempt_is_lookahead_and_rejected():
    log = TraceLog(RUN)
    log.append(
        ev(
            EventType.ARTIFACT_CREATED,
            0,
            artifact_id=ART,
            artifact_version_id=VER,
            content_hash=HASH,
        )
    )
    with pytest.raises(ValueError, match="lookahead"):
        log.append(
            ev(
                EventType.GATE_VERDICT,
                1,
                delivery_id=DLV,
                verdict_id=ids.new_verdict_id(),
                verdict=Verdict.LOG,
            )
        )


def test_withheld_artifact_cannot_claim_successful_parse():
    log = TraceLog(RUN)
    log.append(
        ev(
            EventType.ARTIFACT_CREATED,
            0,
            artifact_id=ART,
            artifact_version_id=VER,
            content_hash=HASH,
        )
    )
    log.append(
        ev(
            EventType.DELIVERY_ATTEMPTED,
            1,
            delivery_id=DLV,
            content_hash=HASH,
            sender_id="agent-a",
            recipient_id="agent-b",
        )
    )
    log.append(
        ev(
            EventType.GATE_VERDICT,
            2,
            delivery_id=DLV,
            verdict_id=ids.new_verdict_id(),
            verdict=Verdict.QUARANTINE,
        )
    )
    with pytest.raises(ValueError, match="not_observed"):
        log.append(
            ev(
                EventType.ARTIFACT_PARSED,
                3,
                delivery_id=DLV,
                parse_status=ParseStatus.PARSED,
            )
        )


def test_duplicate_event_id_is_rejected_as_retry():
    log = TraceLog(RUN)
    first = ev(
        EventType.ARTIFACT_CREATED,
        0,
        artifact_id=ART,
        artifact_version_id=VER,
        content_hash=HASH,
    )
    log.append(first)
    with pytest.raises(ValueError, match="seq must be 1"):
        log.append(first)
