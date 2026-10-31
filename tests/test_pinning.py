"""CL-26 acceptance tests: pinned replay and reproducibility (OPS-01).

AC1 dataset, detector, configuration, thresholds and seeds are pinned
AC2 repeated inputs reproduce verdicts or meet documented stochastic bounds
AC3 report exports carry hashes, trace references, versions and decisions
"""

import hashlib

import pytest

from covertlens.fixtures import build_pair
from covertlens.metadata import analyze_all_bytes
from covertlens.pinning import (
    build_pin,
    export_bundle,
    pin_differences,
    validate_export,
    validate_pin,
    verify_reproducibility,
)
from covertlens.report import build_run_report
from covertlens.events import ParseStatus, Verdict
from covertlens.gate import InterceptionContext, InterceptionGate
from covertlens.lsb import analyze_lsb_version
from covertlens.store import ArtifactStore
from covertlens.verdicts import FamilyThresholds, ThresholdConfig

FROZEN = ThresholdConfig(version="pin-test-1", families={
    "spatial_lsb": FamilyThresholds("spatial_lsb", "frozen", 0.25, 0.6, 0.9)})


def fixtures():
    clean, encoded = build_pair("spatial_lsb", width=32, height=24, payload_bytes=16)
    return [clean, encoded]


def test_pin_covers_dataset_detectors_config_and_seeds():
    pin = build_pin(fixtures(), threshold_config=FROZEN, seeds={"replay": 7})
    assert validate_pin(pin) == []
    assert pin["dataset"]["fixture_count"] == 2
    assert pin["threshold_config_version"] == "pin-test-1"
    assert pin["seeds"] == {"replay": 7}
    assert len(pin["detectors"]) == 3
    assert pin_differences(
        pin, fixtures(), threshold_config=FROZEN, seeds={"replay": 7}) == []
    # Each kind of drift is named.
    _, other = build_pair("spatial_lsb", width=32, height=24, payload_bytes=17)
    drifts = pin_differences(
        pin, [fixtures()[0], other], threshold_config=FROZEN, seeds={"replay": 7})
    assert "dataset" in drifts
    assert "seeds" in pin_differences(
        pin, fixtures(), threshold_config=FROZEN, seeds={"replay": 8})
    assert "detectors" in pin_differences(
        pin, fixtures(), threshold_config=FROZEN, seeds={"replay": 7},
        detector_versions=["other@9"])
    tampered = dict(pin, seeds={"replay": 99})
    assert validate_pin(tampered) != []


def test_repeated_inputs_reproduce_verdicts_exactly():
    result = verify_reproducibility(fixtures(), threshold_config=FROZEN, repetitions=3)
    assert result["exact_reproduction"] is True
    assert result["within_bounds"] is True
    assert result["verdict_agreement"] == 1.0
    with pytest.raises(ValueError):
        verify_reproducibility(fixtures(), repetitions=1)


def test_stochastic_scorer_meets_documented_bounds():
    def noisy(data: bytes, seed: int) -> float:
        # Deterministic-in-seed jitter around the real LSB evidence.
        base = analyze_all_bytes(data).findings[0].score
        jitter = (hashlib.sha256(f"{seed}".encode()).digest()[0] % 5) / 100.0
        return base + jitter

    result = verify_reproducibility(
        fixtures(), repetitions=4, stochastic_scorer=noisy,
        base_seed=100, agreement_min=0.5)
    assert result["deterministic"] is False
    assert result["seeds"] == [100, 101, 102, 103]
    assert result["within_bounds"] == (result["verdict_agreement"] >= 0.5)


def test_export_carries_hashes_trace_versions_and_decisions():
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id="run_pin", episode_id="ep_1", sender_id="agent-a")
    clean, encoded = fixtures()
    results = []
    for fixture in (clean, encoded):
        handle = gate.intercept_bytes("R-01", fixture.data, ctx)
        results.append(analyze_lsb_version(
            gate.store, handle.artifact_version_id, actor_id="detector"))
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
        gate.recipient_access(delivery.delivery_id)
        gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
    report = build_run_report(gate.events("run_pin"), results)
    pin = build_pin([clean, encoded], threshold_config=FROZEN, seeds={"replay": 7})
    bundle = export_bundle(report, pin)
    assert validate_export(bundle) == []
    assert bundle["run_id"] == "run_pin"
    assert bundle["pin_hash"] == pin["pin_hash"]
    assert bundle["trace_references"]["event_ids"]
    assert {o["content_hash"] for o in bundle["originals"]} == {
        clean.content_hash, encoded.content_hash}
    assert {d["verdict"] for d in bundle["decisions"]} == {"flag"}
    assert all("data" not in o for o in bundle["originals"])
    broken = dict(bundle, threshold_config_version="other")
    assert validate_export(broken) != []
