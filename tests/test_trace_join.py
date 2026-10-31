"""CL-16 acceptance tests: join findings to ordered trace events (REV-01).

AC1 every attempted delivery has an original hash and verdict reference
AC2 delivered artifacts link to parse/next action or an explicit missing status
AC3 multiple candidate input artifacts remain visible without claiming causation
"""

import json

import pytest

from covertlens import ids
from covertlens.events import Event, EventType, ParseStatus, TraceLog, Verdict
from covertlens.fixtures import build_pair
from covertlens.gate import InterceptionContext, InterceptionGate
from covertlens.lsb import analyze_lsb_bytes, analyze_lsb_version
from covertlens.parsing import analyze_bytes
from covertlens.store import ArtifactStore
from covertlens.trace_join import join_trace, validate_trace_join

TS = "2026-10-28T12:00:00Z"
RUN = "run_join"


def gate_with_two_deliveries():
    """Two PNG deliveries to agent-b; verdicts recorded, both accessed."""
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN, episode_id="ep_1", sender_id="agent-a")
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    results, deliveries = [], []
    for fixture in (clean, encoded):
        handle = gate.intercept_bytes("R-01", fixture.data, ctx)
        results.append(analyze_lsb_version(
            gate.store, handle.artifact_version_id, actor_id="detector"))
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
        gate.recipient_access(delivery.delivery_id)
        deliveries.append(delivery)
    return gate, results, deliveries


def action_event(seq, **kw):
    return Event(EventType.RECIPIENT_ACTION, RUN, seq, TS,
                 recipient_id="agent-b", payload={"action": "answer"}, **kw)


def test_every_attempted_delivery_has_hash_and_verdict_reference():
    gate, results, deliveries = gate_with_two_deliveries()
    report = join_trace(gate.events(RUN), results)
    assert validate_trace_join(report) == []
    assert report["run_id"] == RUN
    assert report["summary"]["attempted_deliveries"] == 2
    assert report["summary"]["with_verdict_reference"] == 2
    assert report["summary"]["with_findings"] == 2
    by_id = {d["delivery_id"]: d for d in report["deliveries"]}
    for delivery in deliveries:
        record = by_id[delivery.delivery_id]
        assert ids.is_content_hash(record["content_hash"])
        assert record["content_hash"] == delivery.content_hash
        assert record["artifact_version_id"] == delivery.artifact_version_id
        assert record["verdict_reference_status"] == "linked"
        assert record["verdict"]["verdict_id"] == delivery.verdict_id
        assert record["verdict"]["verdict"] == "flag"
        assert len(record["findings"]) == 1
        assert record["findings_status"] == "linked"
    json.dumps(report)


def test_undecided_delivery_reports_missing_verdict_reference():
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN, sender_id="agent-a")
    handle = gate.intercept_bytes("R-01", b"\x89PNG\r\n\x1a\nimg", ctx)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    report = join_trace(gate.events(RUN))
    assert validate_trace_join(report) == []
    record = report["deliveries"][0]
    assert record["delivery_id"] == delivery.delivery_id
    assert record["verdict"] is None
    assert record["verdict_reference_status"] == "missing"
    assert "verdict_reference" in record["missing"]
    assert report["errors"]  # flagged, not dropped
    assert report["summary"]["with_verdict_reference"] == 0


def test_delivered_artifacts_link_parse_and_next_action_or_missing():
    gate, results, deliveries = gate_with_two_deliveries()
    gate.record_parse(deliveries[0].delivery_id, ParseStatus.PARSED)
    events = gate.events(RUN)
    events.append(action_event(len(events)))
    report = join_trace(events, results)
    first, second = report["deliveries"]
    assert first["delivered"] is True
    assert first["parse"]["linkage"] == "linked"
    assert first["parse"]["parse_status"] == "parsed"
    assert first["next_action"]["linkage"] in ("candidate", "referenced")
    # Second delivery was served but never parsed: explicit missing.
    assert second["parse"] == {
        "linkage": "missing", "parse_status": "missing",
        "event_id": None, "seq": None,
    }
    assert "parse_event" in second["missing"]
    assert validate_trace_join(report) == []


def test_withheld_delivery_parse_is_not_observed_not_missing():
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN, sender_id="agent-a")
    handle = gate.intercept_bytes("R-01", b"\x89PNG\r\n\x1a\nimg", ctx)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    gate.record_verdict(delivery.delivery_id, Verdict.QUARANTINE)
    gate.record_parse(delivery.delivery_id, ParseStatus.NOT_OBSERVED)
    report = join_trace(gate.events(RUN))
    record = report["deliveries"][0]
    assert record["delivered"] is False
    assert record["parse"]["parse_status"] == "not_observed"
    assert validate_trace_join(report) == []


def test_multiple_candidates_stay_visible_without_causation():
    gate, results, deliveries = gate_with_two_deliveries()
    gate.record_parse(deliveries[0].delivery_id, ParseStatus.PARSED)
    events = gate.events(RUN)
    events.append(action_event(len(events)))
    report = join_trace(events, results)
    assert report["causation_claimed"] is False
    assert len(report["actions"]) == 1
    action = report["actions"][0]
    assert action["causation_claimed"] is False
    assert action["candidate_count"] == 2
    assert set(action["candidate_delivery_ids"]) == {
        d.delivery_id for d in deliveries}
    for record in report["deliveries"]:
        assert record["next_actions"]
        assert all(a["causation_claimed"] is False for a in record["next_actions"])
    # Referenced delivery is a reference, still not a claimed cause.
    events2 = gate.events(RUN)
    gate.record_parse(deliveries[1].delivery_id, ParseStatus.PARSED)
    events2 = gate.events(RUN)
    events2.append(action_event(len(events2), delivery_id=deliveries[1].delivery_id))
    report2 = join_trace(events2, results)
    action2 = report2["actions"][0]
    assert action2["referenced_delivery_id"] == deliveries[1].delivery_id
    assert action2["candidate_count"] == 2
    assert action2["causation_claimed"] is False


def test_hash_mismatch_findings_are_rejected_not_attached():
    gate, results, deliveries = gate_with_two_deliveries()
    clean, _ = build_pair("spatial_lsb", width=32, height=24, payload_bytes=8)
    tampered = dict(results[0].to_dict())
    tampered["content_hash"] = ids.content_hash(b"different-bytes")
    report = join_trace(gate.events(RUN), [tampered, results[1]])
    first = report["deliveries"][0]
    assert first["findings"] == []
    assert first["findings_status"] == "hash_mismatch_rejected"
    assert any("C-05" in e for e in report["errors"])


def test_unjoined_results_are_listed_with_reasons():
    gate, results, _ = gate_with_two_deliveries()
    orphan = analyze_bytes(build_pair(
        "spatial_lsb", width=32, height=24, payload_bytes=8)[0].data)
    report = join_trace(gate.events(RUN), [*results, orphan])
    assert report["unjoined_results"]
    assert any(
        "artifact_version_id" in row["reason"] for row in report["unjoined_results"])
    assert validate_trace_join(report) == []


def test_cross_run_join_is_rejected_and_dict_events_accepted():
    gate, results, _ = gate_with_two_deliveries()
    events = gate.events(RUN)
    other = Event(EventType.ARTIFACT_CREATED, "run_other", 99, TS,
                  artifact_id=ids.new_artifact_id(),
                  artifact_version_id="x", content_hash=ids.content_hash(b"x"))
    with pytest.raises(ValueError, match="across runs"):
        join_trace([*events, other], results)
    as_dicts = [e.to_dict() for e in events]
    report = join_trace(as_dicts, [r.to_dict() for r in results])
    assert validate_trace_join(report) == []
    assert report["summary"]["attempted_deliveries"] == 2


def test_trace_log_input_and_empty_trace():
    log = TraceLog(RUN)
    report = join_trace(log)
    assert report["deliveries"] == [] and report["run_id"] == RUN
    assert validate_trace_join(report) == []
    gate, results, _ = gate_with_two_deliveries()
    log2 = TraceLog(RUN)
    for event in gate.events(RUN):
        log2.append(event)
    assert join_trace(log2, results)["summary"]["attempted_deliveries"] == 2


def test_join_does_not_claim_causation_even_for_single_candidate():
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN, sender_id="agent-a")
    _, encoded = build_pair("spatial_lsb", width=32, height=24, payload_bytes=16)
    handle = gate.intercept_bytes("R-01", encoded.data, ctx)
    result = analyze_lsb_version(
        gate.store, handle.artifact_version_id, actor_id="detector")
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    gate.record_verdict(delivery.delivery_id, Verdict.LOG)
    gate.recipient_access(delivery.delivery_id)
    gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
    events = gate.events(RUN)
    events.append(action_event(len(events), delivery_id=delivery.delivery_id))
    report = join_trace(events, [result])
    assert report["actions"][0]["candidate_count"] == 1
    assert report["actions"][0]["causation_claimed"] is False
    assert report["deliveries"][0]["next_action"]["causation_claimed"] is False


def test_analyze_bytes_result_without_version_is_unjoined():
    gate, _, deliveries = gate_with_two_deliveries()
    loose = analyze_lsb_bytes(build_pair(
        "spatial_lsb", width=32, height=24, payload_bytes=8)[1].data)
    report = join_trace(gate.events(RUN), [loose])
    assert report["deliveries"][0]["findings_status"] == "no_findings_recorded"
    assert report["unjoined_results"]
