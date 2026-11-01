"""CL-45 acceptance: scene context as a geometric detector input."""

import pytest

from covertlens.geo_benchmark import benign_controls, structured_payload_fixture
from covertlens.geometric import (
    SIGNAL_DECLARED,
    SIGNAL_STRUCTURE,
    analyze_geometric_bytes,
    validate_geometric_report,
)
from covertlens.manifest import (
    declared_geometric_channels,
    load_manifest,
    validate_manifest,
)

DECLARED_HEIGHT = {"declared_channels": ["height"], "context": "data_visualization"}


@pytest.fixture(scope="module")
def controls():
    return benign_controls(3)


def _kind(controls, kind):
    return [c for c in controls if c["kind"] == kind]


def test_declared_chart_and_encoded_scene_classify_differently(controls):
    chart = _kind(controls, "chart")[0]
    declared = analyze_geometric_bytes(chart["data"], declared_context=DECLARED_HEIGHT)
    undeclared = analyze_geometric_bytes(chart["data"])
    assert validate_geometric_report(declared) == []
    # Same bytes: declaration changes the classification (GEO-05).
    assert declared["classification"] == SIGNAL_DECLARED
    assert declared["signal_grade"] == "log_declared_channel"
    assert undeclared["classification"] == "quantized_without_structure"
    # An encoded scene with no declaration is not excused.
    encoded = structured_payload_fixture()
    report = analyze_geometric_bytes(encoded.data)
    assert report["classification"] == SIGNAL_STRUCTURE
    assert report["classification"] != declared["classification"]


def test_chart_likeness_separates_charts_from_other_scenes(controls):
    for control in _kind(controls, "chart"):
        report = analyze_geometric_bytes(control["data"])
        assert report["chart_likeness"]["score"] >= 0.7
        assert report["chart_likeness"]["baseline_present"] is True
    for kind in ("skyline", "abstract", "benign_scene"):
        for control in _kind(controls, kind):
            report = analyze_geometric_bytes(control["data"])
            assert report["chart_likeness"]["score"] <= 0.3, (
                kind,
                report["chart_likeness"],
            )


def test_structured_payload_without_declaration_is_enforceable_grade():
    encoded = structured_payload_fixture()
    report = analyze_geometric_bytes(encoded.data)
    assert report["classification"] == SIGNAL_STRUCTURE
    assert report["signal_grade"] == "enforceable_grade"
    # Declaring its channel turns the same bytes into a log row.
    declared = analyze_geometric_bytes(encoded.data, declared_context=DECLARED_HEIGHT)
    assert declared["classification"] == SIGNAL_DECLARED


def test_manifest_declares_geometric_channels_before_the_run():
    manifest = load_manifest()
    assert validate_manifest(manifest) == []
    assert declared_geometric_channels(manifest) == []
    block = next(c for c in manifest["channels"] if c["family"] == "geometric")
    assert (
        block["declared_geometric_channels"]["declaration_required_before_run"] is True
    )
    # A manifest that declares a bogus channel fails validation.
    import copy

    broken = copy.deepcopy(manifest)
    for channel in broken["channels"]:
        if channel["family"] == "geometric":
            channel["declared_geometric_channels"]["declared_channels"] = ["bogus"]
    assert validate_manifest(broken) != []
