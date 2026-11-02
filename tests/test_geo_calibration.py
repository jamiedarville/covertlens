"""Frozen geometric operating points and scorer boundary (CL-54)."""

import pytest

from covertlens.calibration import calibrate_thresholds, load_frozen_thresholds
from covertlens.geo_benchmark import benign_controls, build_structured_pair
from covertlens.geo_calibration import (
    evaluate_geometric_held_out,
    geometric_calibration_dataset,
)
from covertlens.geometric import analyze_geometric_bytes
from covertlens.geometric_fixtures import validate_geo_splits
from covertlens.vector_source import analyze_with_source, build_vector_source
from covertlens.verdicts import decide_verdict


def test_geometric_held_out_labels_cannot_calibrate():
    fixtures, assignments = geometric_calibration_dataset()
    assert validate_geo_splits(fixtures, assignments) == []
    held = [f for f in fixtures if assignments[f.fixture_id] == "held_out"]
    assert held
    with pytest.raises(ValueError, match="held-out"):
        calibrate_thresholds(held, assignments)
    dev_hashes = {
        f.content_hash for f in fixtures if assignments[f.fixture_id] != "held_out"
    }
    assert not dev_hashes.intersection(f.content_hash for f in held)


def test_frozen_structure_quarantines_but_declared_chart_permits():
    config, _ = load_frozen_thresholds()
    _, scene = build_structured_pair("height_position")
    finding = analyze_geometric_bytes(scene.data)["finding"]
    decision = decide_verdict([finding], config)
    assert decision.verdict.value == "quarantine"
    assert decision.enforceable
    chart = next(c for c in benign_controls() if c["kind"] == "chart")
    finding = analyze_geometric_bytes(
        chart["data"], declared_context={"declared_channels": ["height"]}
    )["finding"]
    assert decide_verdict([finding], config).verdict.value == "log"
    # Both vector and raster paths use the same ladder decision.
    binding = analyze_with_source(scene, build_vector_source(scene))
    assert binding["decision"]["verdict"] == "quarantine"
    assert binding["decision"]["content_hash"] == scene.content_hash
    assert binding["cleared"] is False
    fallback = analyze_with_source(scene)
    assert fallback["clearance"] == "not_cleared"


def test_held_out_report_has_intervals_and_no_universal_claim():
    report = evaluate_geometric_held_out()
    assert report["universal_claim"] is False
    assert report["development_overlap"] is False
    for row in report["subfamilies"].values():
        for key in ("recall_triage", "recall_enforcement", "recall_structure"):
            assert row[key]["n"] > 0
            assert row[key]["wilson_95"]["low"] is not None
    assert (
        report["chart_controls"]["declared_height"]["false_enforcement"]["successes"]
        == 0
    )
