"""CL-12 acceptance tests: artifact-store interception and pending delivery.

AC1 all inventoried image paths reach the gate before recipient access (EV-06)
AC2 stable run, episode, sender, recipient and artifact version/hash are emitted (EV-06)
AC3 repeated references and retries are handled idempotently (EV-07)
"""

import pytest

from covertlens import ids
from covertlens.events import EventType, ParseStatus, Verdict, validate_event
from covertlens.gate import (
    InterceptionContext,
    InterceptionGate,
    PendingDeliveryError,
    WithheldError,
)
from covertlens.routes import ROUTES
from covertlens.store import ArtifactStore

PNG = b"\x89PNG\r\n\x1a\n" + b"gate-test-image-v1"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"gate-test-image-v2-changed"
CTX = InterceptionContext(run_id="run_gate", episode_id="ep_1", sender_id="agent-a")


def fresh_gate():
    return InterceptionGate(ArtifactStore())


def deliver(gate, data=PNG, route="R-01", recipient="agent-b", ctx=CTX):
    handle = gate.intercept_bytes(route, data, ctx)
    return handle, gate.attempt_delivery(handle, recipient_id=recipient)


def test_interception_ingests_and_emits_stable_identities():
    gate = fresh_gate()
    handle, delivery = deliver(gate)
    assert handle.content_hash == ids.content_hash(PNG)
    assert handle.artifact_version_id == ids.artifact_version_id(handle.artifact_id, handle.content_hash)
    assert delivery.state == "pending"
    events = gate.events("run_gate")
    assert [e.event_type for e in events] == [
        EventType.ARTIFACT_CREATED,
        EventType.DELIVERY_ATTEMPTED,
    ]
    attempted = events[1]
    assert attempted.run_id == "run_gate" and attempted.episode_id == "ep_1"
    assert attempted.sender_id == "agent-a" and attempted.recipient_id == "agent-b"
    assert attempted.content_hash == handle.content_hash
    assert attempted.artifact_version_id == handle.artifact_version_id
    for event in events:
        assert validate_event(event) == []


def test_every_gated_route_reaches_the_gate_and_r08_is_not_a_delivery():
    gate = fresh_gate()
    gated = [r for r in ROUTES if r.gate_required]
    assert len(gated) == 7
    for route in gated:
        handle = gate.intercept_bytes(route.route_id, PNG, CTX)
        assert handle.content_hash == ids.content_hash(PNG)
    assert gate.coverage_report()["missing"] == []
    with pytest.raises(ValueError, match="review"):
        gate.intercept_bytes("R-08", PNG, CTX)
    with pytest.raises(ValueError, match="unknown route"):
        gate.intercept_bytes("R-99", PNG, CTX)


def test_pending_delivery_serves_no_bytes_until_a_permitting_verdict():
    gate = fresh_gate()
    _, delivery = deliver(gate)
    with pytest.raises(PendingDeliveryError):
        gate.recipient_access(delivery.delivery_id)
    gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
    assert gate.recipient_access(delivery.delivery_id) == PNG
    assert gate.events("run_gate")[-1].event_type is EventType.ARTIFACT_ACCESSED


def test_quarantine_and_fail_run_withhold_and_parse_is_not_observed():
    for verdict in (Verdict.QUARANTINE, Verdict.FAIL_RUN):
        gate = fresh_gate()
        _, delivery = deliver(gate)
        gate.record_verdict(delivery.delivery_id, verdict)
        with pytest.raises(WithheldError):
            gate.recipient_access(delivery.delivery_id)
        with pytest.raises(ValueError, match="not_observed"):
            gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
        gate.record_parse(delivery.delivery_id, ParseStatus.NOT_OBSERVED)


def test_repeated_references_and_retries_are_idempotent():
    gate = fresh_gate()
    first = gate.intercept_reference("R-03", "artifact://img-1", lambda ref: PNG, CTX)
    second = gate.intercept_reference("R-03", "artifact://img-1", lambda ref: PNG, CTX)
    assert first.artifact_version_id == second.artifact_version_id
    created = [e for e in gate.events("run_gate") if e.event_type is EventType.ARTIFACT_CREATED]
    assert len(created) == 1
    d1 = gate.attempt_delivery(first, recipient_id="agent-b", attempt=1)
    d2 = gate.attempt_delivery(first, recipient_id="agent-b", attempt=1)
    assert d1.delivery_id == d2.delivery_id
    attempted = [e for e in gate.events("run_gate") if e.event_type is EventType.DELIVERY_ATTEMPTED]
    assert len(attempted) == 1
    d3 = gate.attempt_delivery(first, recipient_id="agent-b", attempt=2)
    assert d3.delivery_id != d1.delivery_id


def test_verdict_binds_the_exact_version_changed_bytes_need_a_new_verdict():
    gate = fresh_gate()
    _, delivery = deliver(gate)
    gate.record_verdict(delivery.delivery_id, Verdict.LOG)
    assert gate.store.verdict_status(delivery.verdict_id) == "current"
    handle2 = gate.intercept_bytes("R-01", PNG2, InterceptionContext(
        run_id="run_gate", episode_id="ep_1", sender_id="agent-a",
        artifact_id=delivery.artifact_id,
    ))
    assert handle2.artifact_version_id != delivery.artifact_version_id
    assert gate.store.verdict_status(delivery.verdict_id) == "invalidated"
    delivery2 = gate.attempt_delivery(handle2, recipient_id="agent-b")
    with pytest.raises(PendingDeliveryError):
        gate.recipient_access(delivery2.delivery_id)


def test_coverage_report_lists_unexercised_gated_routes():
    gate = fresh_gate()
    report = gate.coverage_report()
    assert set(report["missing"]) == {r.route_id for r in ROUTES if r.gate_required}
    gate.intercept_bytes("R-01", PNG, CTX)
    report = gate.coverage_report()
    assert "R-01" in report["covered"] and "R-02" in report["missing"]
