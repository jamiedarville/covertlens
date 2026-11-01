"""CL-44 acceptance: geometric as the fourth channel family."""

import pytest

from covertlens.events import ParseStatus, Verdict
from covertlens.gate import InterceptionContext, InterceptionGate
from covertlens.geometric import analyze_geometric_bytes
from covertlens.geometric_fixtures import build_geo_pair
from covertlens.manifest import FAMILIES, channel_families, load_manifest, validate_manifest
from covertlens.metadata import analyze_all_bytes
from covertlens.parsing import validate_finding, validate_result
from covertlens.pinning import build_pin, export_bundle, validate_pin
from covertlens.report import build_run_report, validate_run_report
from covertlens.scorecard import load_scorecard
from covertlens.segmentation import FAILURE_MODES, SegmentationResult, validate_segmentation
from covertlens.store import ArtifactStore
from covertlens.verdicts import decide_verdict


@pytest.fixture(scope="module")
def geo_pair():
    return build_geo_pair("height_position")


def test_manifest_has_four_channels():
    manifest = load_manifest()
    assert validate_manifest(manifest) == []
    assert manifest["manifest_version"] == "1.1.0"
    assert channel_families(manifest) == list(FAMILIES)
    assert "geometric" in FAMILIES
    channel = next(c for c in manifest["channels"] if c["family"] == "geometric")
    assert channel["applies_to"] == ["png"]
    assert channel["thresholds"]["status"] == "unfrozen_placeholder"


def test_geometric_finding_validates_and_verdict_is_log_only(geo_pair):
    _clean, encoded = geo_pair
    finding = analyze_geometric_bytes(encoded.data)["finding"]
    assert validate_finding(finding) == []
    decision = decide_verdict([finding])
    assert decision.verdict is Verdict.LOG
    assert decision.enforceable is False
    assert decision.per_family[0]["family"] == "geometric"
    assert "geometric" not in decision.families_without_findings
    assert "spatial_lsb" in decision.families_without_findings


def test_analyze_all_bytes_attaches_geometric_for_png_only(geo_pair):
    _clean, encoded = geo_pair
    result = analyze_all_bytes(encoded.data)
    assert validate_result(result) == []
    families = [f.family for f in result.findings]
    assert "geometric" in families
    assert len(families) == len(set(families))  # at most one per family
    geometric = next(f for f in result.findings if f.family == "geometric")
    assert validate_finding(geometric) == []


def test_corrupt_source_is_a_recorded_failure_mode():
    assert "corrupt_source" in {m["status"] for m in FAILURE_MODES}
    doc = SegmentationResult("corrupt_source", detail="bad vector source").to_dict()
    assert validate_segmentation(doc) == []


def test_report_export_and_pin_carry_geometric(geo_pair):
    _clean, encoded = geo_pair
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id="run_geo44", episode_id="ep_1",
                              sender_id="agent-a")
    handle = gate.intercept_bytes("R-01", encoded.data, ctx)
    result = analyze_all_bytes(
        encoded.data, artifact_version_id=handle.artifact_version_id)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    gate.record_verdict(delivery.delivery_id, Verdict.LOG)
    gate.recipient_access(delivery.delivery_id)
    gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)

    report = build_run_report(gate.events("run_geo44"), [result],
                              report_id="rpt_geo44")
    assert validate_run_report(report) == []
    families = {
        f["family"] for original in report["originals"]
        for f in original["findings"]
    }
    assert "geometric" in families

    pin = build_pin([encoded], seeds={"geo": 44})
    assert validate_pin(pin) == []
    assert any("geometric" in d for d in pin["detectors"])
    assert pin["geometric_config_version"]
    assert pin["thresholds_status"]["geometric"] == "unfrozen_placeholder"

    bundle = export_bundle(report, pin)
    assert bundle["pin_hash"] == pin["pin_hash"]
    assert any("geometric" in d for d in bundle["detectors"])


def test_published_scorecard_has_geometric_section_per_subfamily():
    card = load_scorecard()
    geometric = card["sections"]["geometric"]
    assert geometric["source_schema"] == "covertlens.geo-benchmark"
    assert set(geometric["per_subfamily"]) == {
        "height_position", "gap_timing", "lit_dark", "colour_code",
        "angle_tilt",
    }
    assert geometric["general_geometric_coverage_claimed"] is False
    assert geometric["enforceable"] is False
    for block in geometric["per_subfamily"].values():
        assert block["encoded_recall_any_signal"] is not None
        assert block["benign_false_structure_claim_rate"] == 0.0
