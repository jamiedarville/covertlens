"""CL-23 acceptance tests: metadata scoring and integration (DET-05).

AC1 metadata scores distinguish supported encoding evidence from benign controls
AC2 LSB, DCT and metadata outputs remain individually visible
AC3 all three families run through pinned threshold configurations
"""

import json

import pytest

from covertlens.events import Verdict
from covertlens.fixtures import build_pair
from covertlens.metadata import (
    METADATA_DETECTOR_NAME,
    analyze_all_bytes,
    analyze_and_decide,
    benchmark_metadata,
    detect_metadata,
    validate_metadata_benchmark,
)
from covertlens.metadata_fixtures import (
    build_metadata_dataset,
    build_metadata_pair,
    encode_metadata_png,
)
from covertlens.parsing import analyze_bytes, validate_finding, validate_result
from covertlens.verdicts import FamilyThresholds, ThresholdConfig

FROZEN_ALL = ThresholdConfig(version="test-pinned-1", families={
    "spatial_lsb": FamilyThresholds("spatial_lsb", "frozen", 0.25, 0.6, 0.9),
    "jpeg_dct": FamilyThresholds("jpeg_dct", "frozen", 0.25, 0.6, 0.9),
    "metadata": FamilyThresholds("metadata", "frozen", 0.5, 0.85, 0.95),
})


@pytest.fixture(scope="module")
def meta_dataset():
    return build_metadata_dataset()


def test_scores_distinguish_encoding_from_benign_controls(meta_dataset):
    scores = {}
    for fixture in meta_dataset:
        finding = detect_metadata(fixture.data, analyze_bytes(fixture.data))
        assert finding is not None
        assert finding.family == "metadata"
        assert finding.detector_name == METADATA_DETECTOR_NAME
        assert validate_finding(finding) == []
        # Payload values never leak into the finding record.
        assert fixture.payload.decode("latin-1", "ignore") not in json.dumps(
            finding.to_dict(), default=str) or not fixture.payload
        scores.setdefault(fixture.role, []).append(finding.score)
    assert min(scores["encoded"]) >= 0.9
    assert max(scores["clean"] + scores["negative"]) == 0.0
    report = benchmark_metadata(meta_dataset, thresholds=[0.5])
    assert validate_metadata_benchmark(report) == []
    assert report["roc_auc"]["estimate"] == 1.0
    assert report["by_payload_band"]["high"]["roc_auc_vs_negatives"] == 1.0
    mid = report["sweep"][0]
    assert mid["fp"] == 0 and mid["recall"]["estimate"] == 1.0


def test_unknown_metadata_is_weak_and_allowed_is_benign():
    clean, _ = build_metadata_pair("png", payload_bytes=8)
    unknown = encode_metadata_png(clean.data, b"opaque-value", keyword="X-Custom")
    finding = detect_metadata(unknown, analyze_bytes(unknown))
    assert 0.0 < finding.score < 0.9
    assert finding.evidence["unknown_entries"] == 1
    allowed_only = detect_metadata(clean.data, analyze_bytes(clean.data))
    assert allowed_only.score == 0.0
    corrupt = analyze_bytes(clean.data[:16])
    assert detect_metadata(clean.data[:16], corrupt) is None


def test_all_families_individually_visible_on_one_result():
    _, encoded_png = build_metadata_pair("png", payload_bytes=64)
    result = analyze_all_bytes(encoded_png.data)
    assert validate_result(result) == []
    families = {f.family: f for f in result.findings}
    assert set(families) == {"spatial_lsb", "metadata"}
    assert families["spatial_lsb"].score == 0 or families["spatial_lsb"].score > 0
    assert families["metadata"].score >= 0.9
    _, encoded_jpeg = build_metadata_pair("jpeg", payload_bytes=64)
    result_j = analyze_all_bytes(encoded_jpeg.data)
    assert {f.family for f in result_j.findings} == {"jpeg_dct", "metadata"}
    assert len(result_j.findings) == 2  # not blended into one score


def test_all_three_families_run_through_pinned_thresholds():
    _, encoded_png = build_metadata_pair("png", payload_bytes=64)
    result, decision = analyze_and_decide(encoded_png.data, FROZEN_ALL)
    assert decision is not None
    assert decision.config_version == "test-pinned-1"  # pinned config recorded
    per_family = {r["family"]: r for r in decision.per_family}
    assert per_family["metadata"]["verdict"] == "quarantine"  # ~0.91 vs points
    assert per_family["spatial_lsb"]["verdict"] in ("log", "flag")
    assert decision.verdict is Verdict.QUARANTINE

    _, encoded_jpeg = build_metadata_pair("jpeg", payload_bytes=64)
    _, decision_j = analyze_and_decide(encoded_jpeg.data, FROZEN_ALL)
    assert {r["family"] for r in decision_j.per_family} == {"jpeg_dct", "metadata"}

    clean, _ = build_pair("spatial_lsb", width=32, height=24, payload_bytes=8)
    result_c, decision_c = analyze_and_decide(clean.data, FROZEN_ALL)
    assert {f.family for f in result_c.findings} == {"spatial_lsb", "metadata"}
    # A clean artifact is never withheld: log or at most a triage flag.
    assert decision_c.verdict in (Verdict.LOG, Verdict.FLAG)
    assert decision_c.delivery == "permit"
    clean_rows = {r["family"]: r for r in decision_c.per_family}
    assert clean_rows["metadata"]["verdict"] == "log"
    broken, decision_b = analyze_and_decide(b"not-an-image", FROZEN_ALL)
    assert decision_b is None and broken.findings == ()
