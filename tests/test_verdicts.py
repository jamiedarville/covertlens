"""CL-17 acceptance tests: verdict ladder and threshold config (ENF-01/02).

AC1 log and flag permit delivery; quarantine withholds; fail halts execution/delivery
AC2 triage and enforcement operating points are separately configured
AC3 pre-delivery decisions cannot use future recipient actions
"""

import json

import pytest

from covertlens import ids
from covertlens.events import Event, EventType, Verdict
from covertlens.fixtures import build_pair
from covertlens.gate import (
    InterceptionContext,
    InterceptionGate,
    PendingDeliveryError,
    WithheldError,
)
from covertlens.lsb import analyze_lsb_bytes
from covertlens.manifest import load_manifest
from covertlens.parsing import Finding
from covertlens.store import ArtifactStore
from covertlens.verdicts import (
    DecisionContext,
    FamilyThresholds,
    LookaheadError,
    ThresholdConfig,
    decide_and_record,
    decide_verdict,
    delivery_for_verdict,
    threshold_config_from_manifest,
    validate_decision,
    validate_threshold_config,
)

TS = "2026-10-28T12:00:00Z"
RUN = "run_verdict"

# Synthetic frozen points for tests only; shipped config stays unfrozen.
FROZEN = ThresholdConfig(families={
    "spatial_lsb": FamilyThresholds(
        "spatial_lsb", "frozen", 0.30, 0.60, 0.90),
    "jpeg_dct": FamilyThresholds("jpeg_dct", "frozen", 0.30, 0.60, 0.90),
    "metadata": FamilyThresholds("metadata", "frozen", 0.30, 0.60, 0.90),
})


def finding(family="spatial_lsb", score=0.5):
    return Finding(
        family=family, detector_name="test-detector",
        detector_version="1.0.0", score=score, coverage={"samples": 10},
    )


def test_ladder_mapping_permits_and_withholds():
    assert delivery_for_verdict(Verdict.LOG) == "permit"
    assert delivery_for_verdict(Verdict.FLAG) == "permit"
    assert delivery_for_verdict(Verdict.QUARANTINE) == "withhold"
    assert delivery_for_verdict(Verdict.FAIL_RUN) == "withhold"
    manifest_ladder = {
        row["verdict"]: row["delivery"] for row in load_manifest()["verdict_ladder"]}
    for verdict in Verdict:
        assert delivery_for_verdict(verdict) == manifest_ladder[verdict.value]


def test_operating_points_are_separately_configured():
    config = threshold_config_from_manifest()
    assert validate_threshold_config(config) == []
    assert validate_threshold_config(config.to_dict()) == []
    for family in ("spatial_lsb", "jpeg_dct", "metadata"):
        points = config.for_family(family)
        assert points.status == "unfrozen_placeholder"
        # No invented numbers before CL-27; triage/enforcement both unset.
        assert points.triage_flag_at is None
        assert points.enforcement_quarantine_at is None
        assert points.enforcement_fail_run_at is None
    block = config.to_dict()["families"]["spatial_lsb"]
    assert block["triage"]["operating_point"] == "high_recall"
    assert block["enforcement"]["operating_point"] == "high_precision"
    # Frozen configs must be complete and ordered.
    with pytest.raises(ValueError, match="invented"):
        FamilyThresholds("spatial_lsb", "unfrozen_placeholder", 0.5, None, None)
    with pytest.raises(ValueError, match="all three"):
        FamilyThresholds("spatial_lsb", "frozen", 0.5, None, None)
    with pytest.raises(ValueError, match="flag_at <= quarantine_at"):
        FamilyThresholds("spatial_lsb", "frozen", 0.9, 0.5, 0.95)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        FamilyThresholds("spatial_lsb", "frozen", 0.3, 0.6, 1.5)


@pytest.mark.parametrize("score,expected", [
    (0.0, Verdict.LOG), (0.29, Verdict.LOG), (0.30, Verdict.FLAG),
    (0.59, Verdict.FLAG), (0.60, Verdict.QUARANTINE),
    (0.89, Verdict.QUARANTINE), (0.90, Verdict.FAIL_RUN),
    (1.0, Verdict.FAIL_RUN),
])
def test_frozen_points_map_scores_to_the_ladder(score, expected):
    decision = decide_verdict([finding(score=score)], FROZEN)
    assert decision.verdict is expected
    assert decision.delivery == delivery_for_verdict(expected)
    assert decision.halt_execution is (expected is Verdict.FAIL_RUN)
    assert decision.enforceable is True
    assert validate_decision(decision) == []
    assert validate_decision(decision.to_dict()) == []
    json.dumps(decision.to_dict())


def test_most_severe_family_wins_and_unfrozen_is_log_only():
    decision = decide_verdict(
        [finding("spatial_lsb", 0.35), finding("jpeg_dct", 0.95)], FROZEN)
    assert decision.verdict is Verdict.FAIL_RUN
    assert {r["family"] for r in decision.per_family} == {"spatial_lsb", "jpeg_dct"}
    unfrozen = decide_verdict([finding(score=0.99)])  # shipped default
    assert unfrozen.verdict is Verdict.LOG
    assert unfrozen.delivery == "permit"
    assert unfrozen.enforceable is False
    assert unfrozen.equated_with_collusion is False
    empty = decide_verdict([], FROZEN)
    assert empty.verdict is Verdict.LOG
    assert set(empty.families_without_findings) == {
        "spatial_lsb", "jpeg_dct", "metadata"}


def test_invalid_findings_and_hashes_are_rejected():
    with pytest.raises(ValueError, match="invalid finding"):
        decide_verdict([finding(score=1.5)], FROZEN)
    with pytest.raises(ValueError, match="content_hash"):
        decide_verdict(
            [finding()], FROZEN,
            context=DecisionContext(content_hash="not-a-hash"))


def pending_delivery(gate, data):
    ctx = InterceptionContext(run_id=RUN, sender_id="agent-a")
    handle = gate.intercept_bytes("R-01", data, ctx)
    return gate.attempt_delivery(handle, recipient_id="agent-b")


@pytest.mark.parametrize("score,verdict,served", [
    (0.10, Verdict.LOG, True), (0.40, Verdict.FLAG, True),
    (0.70, Verdict.QUARANTINE, False), (0.95, Verdict.FAIL_RUN, False),
])
def test_gate_enforces_the_decision(score, verdict, served):
    gate = InterceptionGate(ArtifactStore())
    delivery = pending_delivery(gate, b"\x89PNG\r\n\x1a\nimg")
    with pytest.raises(PendingDeliveryError):
        gate.recipient_access(delivery.delivery_id)
    decision = decide_and_record(
        gate, delivery.delivery_id, [finding(score=score)], FROZEN)
    assert decision.verdict is verdict
    assert decision.delivery_id == delivery.delivery_id
    if served:
        assert gate.recipient_access(delivery.delivery_id) == b"\x89PNG\r\n\x1a\nimg"
    else:
        with pytest.raises(WithheldError):
            gate.recipient_access(delivery.delivery_id)
    assert decision.halt_execution is (verdict is Verdict.FAIL_RUN)


def test_recipient_actions_and_future_events_are_lookahead():
    attempted = Event(
        EventType.DELIVERY_ATTEMPTED, RUN, 1, TS, delivery_id="dlv_x",
        content_hash=ids.content_hash(b"x"),
        sender_id="agent-a", recipient_id="agent-b")
    action = Event(
        EventType.RECIPIENT_ACTION, RUN, 2, TS, delivery_id="dlv_x",
        payload={"action": "answer"})
    with pytest.raises(LookaheadError, match="recipient actions"):
        decide_verdict([finding()], FROZEN, observed_events=[attempted, action])
    future = Event(EventType.ARTIFACT_ACCESSED, RUN, 9, TS, delivery_id="dlv_x")
    with pytest.raises(LookaheadError, match="lookahead"):
        decide_verdict(
            [finding()], FROZEN,
            context=DecisionContext(evidence_through_seq=3),
            observed_events=[attempted, future])
    # The same events at or before the cutoff are admissible evidence.
    decision = decide_verdict(
        [finding(score=0.4)], FROZEN,
        context=DecisionContext(evidence_through_seq=3),
        observed_events=[attempted])
    assert decision.verdict is Verdict.FLAG


def test_real_detector_scores_flow_through_the_ladder():
    _, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=192)
    result = analyze_lsb_bytes(encoded.data)
    frozen_lsb_only = ThresholdConfig(families={
        "spatial_lsb": FamilyThresholds("spatial_lsb", "frozen", 0.25, 0.60, 0.90)})
    decision = decide_verdict(result.findings, frozen_lsb_only)
    assert decision.findings_count == 1
    assert decision.per_family[0]["detectors"] == ["lsb-pov-chisquare@1.0.0"]
    assert decision.verdict is Verdict.FLAG  # ~0.36 vs test points above
    assert validate_decision(decision) == []
