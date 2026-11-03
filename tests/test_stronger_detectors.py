"""CL-61 acceptance tests: stronger pixel detectors (DET-03/DET-04, OP-06).

AC1 On +/-1 embedded fixtures, the new spatial detector's ROC-AUC
    beats PoV chi-square, with bootstrap intervals reported
AC2 Calibrated-histogram DCT detector is individually visible and
    beats PoV on the +/-1 DCT suite
AC3 No regression on the existing frozen benchmark (frozen paths
    stay pinned to the originally calibrated detectors)
"""

import json

import pytest

from covertlens import ids
from covertlens.dct import (
    CAL_CONFIG_VERSION,
    CAL_DETECTOR_NAME,
    CAL_DETECTOR_VERSION,
    benchmark_dct_calibrated,
    detect_dct_calibrated,
    validate_dct_calibrated_benchmark,
)
from covertlens.fixtures import (
    build_dataset,
    build_matching_dataset,
    build_matching_pair,
    build_pair,
)
from covertlens.frozen_benchmark import _family_score
from covertlens.lsb import (
    SPA_CONFIG_VERSION,
    SPA_DETECTOR_NAME,
    SPA_DETECTOR_VERSION,
    SpaConfig,
    analyze_lsb_pairs_bytes,
    benchmark_lsb,
    benchmark_lsb_pairs,
    validate_lsb_pairs_benchmark,
)
from covertlens.metadata import analyze_all_bytes
from covertlens.parsing import analyze_bytes, validate_finding, validate_result


@pytest.fixture(scope="module")
def matching_dataset():
    return build_matching_dataset()


@pytest.fixture(scope="module")
def pairs_report(matching_dataset):
    return benchmark_lsb_pairs(matching_dataset, bootstrap_replicates=200)


@pytest.fixture(scope="module")
def calibrated_report(matching_dataset):
    return benchmark_dct_calibrated(matching_dataset, bootstrap_replicates=200)


def test_matching_fixtures_verify_and_differ_only_by_embedding(matching_dataset):
    encoded = [f for f in matching_dataset if f.role == "encoded"]
    assert encoded  # the suite exists
    for fixture in encoded:
        assert fixture.verify_payload()
        assert fixture.encoder["name"] in ("lsb-matching-png", "dct-matching-jpeg")
        assert fixture.generator["pattern"] == "smooth_field"
    cleans = {f.pair_id: f for f in matching_dataset if f.role == "clean"}
    for fixture in encoded:
        assert fixture.data != cleans[fixture.pair_id].data
        assert fixture.payload_bits > 0


def test_spa_finding_is_versioned_with_coverage():
    clean, encoded = build_matching_pair("spatial_lsb", payload_bytes=64)
    for fixture in (clean, encoded):
        result = analyze_lsb_pairs_bytes(fixture.data)
        assert result.status.value == "parsed"
        assert result.content_hash == ids.content_hash(fixture.data)
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.family == "spatial_lsb"
        assert finding.detector_name == SPA_DETECTOR_NAME
        assert finding.detector_version == SPA_DETECTOR_VERSION
        assert 0.0 <= finding.score <= 1.0
        assert finding.coverage["applicable"] is True
        assert finding.coverage["pairs_examined"] > 0
        assert finding.coverage["config_version"] == SPA_CONFIG_VERSION
        assert finding.evidence["statistic"] == ("sample_pair_lsb_agreement_randomness")
        assert finding.evidence["reliable"] is True
        assert validate_finding(finding) == []
        assert validate_result(result) == []
    clean_score = analyze_lsb_pairs_bytes(clean.data).findings[0].score
    encoded_score = analyze_lsb_pairs_bytes(encoded.data).findings[0].score
    assert encoded_score > clean_score


def test_spa_gates_to_zero_on_uncorrelated_covers():
    # The CL-9 gradient_noise covers have no adjacent-pair correlation:
    # the pair statistic must declare itself unreliable, not improvise.
    clean, _ = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    finding = analyze_lsb_pairs_bytes(clean.data).findings[0]
    assert finding.evidence["reliable"] is False
    assert finding.score == 0.0
    assert any("not reliable" in text for text in finding.limitations)


def test_spa_jpeg_and_failed_parse_get_no_finding():
    _, jpeg = build_matching_pair("jpeg_dct", width=64, height=48, payload_bytes=8)
    assert analyze_lsb_pairs_bytes(jpeg.data).findings == ()
    clean, _ = build_matching_pair("spatial_lsb", payload_bytes=8)
    corrupt = analyze_lsb_pairs_bytes(clean.data[: len(clean.data) // 2])
    assert corrupt.status.value == "corrupt"
    assert corrupt.findings == ()
    with pytest.raises(ValueError):
        SpaConfig(min_pairs=0)
    with pytest.raises(ValueError):
        SpaConfig(smooth_min_fraction=1.5)


def test_spa_beats_pov_on_matching_fixtures_with_bootstrap(pairs_report):
    assert validate_lsb_pairs_benchmark(pairs_report) == []
    assert pairs_report["detector"]["name"] == SPA_DETECTOR_NAME
    assert pairs_report["comparator"]["name"] == "lsb-pov-chisquare"
    assert pairs_report["thresholds_status"] == "unfrozen_placeholder"
    for key in ("pairs_roc_auc", "pov_roc_auc"):
        block = pairs_report[key]
        assert block["bootstrap_replicates"] == 200
        assert 0.0 <= block["ci_low"] <= block["estimate"] <= block["ci_high"] <= 1.0
    # Acceptance: on +/-1 fixtures the sample-pair ROC-AUC beats PoV.
    assert pairs_report["pairs_beats_pov"] is True
    assert (
        pairs_report["pairs_roc_auc"]["estimate"]
        > pairs_report["pov_roc_auc"]["estimate"]
    )
    rows = {r["fixture_id"]: r for r in pairs_report["rows"]}
    assert len(rows) == pairs_report["fixture_count"]
    for row in rows.values():
        assert row["pairs_score"] is not None
        assert row["pov_score"] is not None  # both individually visible
    json.dumps(pairs_report)


def test_calibrated_finding_is_versioned_with_coverage():
    clean, encoded = build_matching_pair(
        "jpeg_dct", width=64, height=48, payload_bytes=16
    )
    for fixture in (clean, encoded):
        result = analyze_bytes(fixture.data)
        finding = detect_dct_calibrated(result)
        assert finding is not None
        assert finding.family == "jpeg_dct"
        assert finding.detector_name == CAL_DETECTOR_NAME
        assert finding.detector_version == CAL_DETECTOR_VERSION
        assert 0.0 <= finding.score <= 1.0
        assert finding.coverage["domain"] == "quantized_coefficients"
        assert finding.coverage["config_version"] == CAL_CONFIG_VERSION
        assert finding.evidence["statistic"] == ("calibrated_histogram_total_variation")
        assert finding.evidence["reliable"] is True
        assert validate_finding(finding) == []


def test_calibrated_gates_on_uncorrelated_jpeg():
    # Gradient-noise JPEG blocks are spatially uncorrelated, so the
    # neighbor calibration cannot speak and must gate to 0.
    _, encoded = build_pair("jpeg_dct", width=64, height=48, payload_bytes=64)
    finding = detect_dct_calibrated(analyze_bytes(encoded.data))
    assert finding is not None
    assert finding.evidence["reliable"] is False
    assert finding.score == 0.0
    assert any("not reliable" in text for text in finding.limitations)
    # PNGs and failed parses get no calibrated finding.
    clean_png, _ = build_matching_pair("spatial_lsb", payload_bytes=8)
    assert detect_dct_calibrated(analyze_bytes(clean_png.data)) is None


def test_calibrated_beats_pov_on_matching_fixtures(calibrated_report):
    assert validate_dct_calibrated_benchmark(calibrated_report) == []
    assert calibrated_report["detector"]["name"] == CAL_DETECTOR_NAME
    assert calibrated_report["comparator"]["name"] == ("dct-coefficient-pov-chisquare")
    for key in ("calibrated_roc_auc", "pov_roc_auc"):
        block = calibrated_report[key]
        assert block["bootstrap_replicates"] == 200
        assert 0.0 <= block["ci_low"] <= block["estimate"] <= block["ci_high"] <= 1.0
    assert calibrated_report["calibrated_beats_pov"] is True
    assert (
        calibrated_report["calibrated_roc_auc"]["estimate"]
        > calibrated_report["pov_roc_auc"]["estimate"]
    )
    for row in calibrated_report["rows"]:
        assert row["calibrated_score"] is not None
        assert row["pov_score"] is not None  # both individually visible
    json.dumps(calibrated_report)


def test_both_detectors_individually_visible_in_pipeline():
    _, encoded_png = build_matching_pair("spatial_lsb", payload_bytes=64)
    result = analyze_all_bytes(encoded_png.data)
    assert validate_result(result) == []
    spatial = [f for f in result.findings if f.family == "spatial_lsb"]
    assert [f.detector_name for f in spatial] == [
        "lsb-pov-chisquare",
        "lsb-sample-pairs",
    ]
    _, encoded_jpeg = build_matching_pair(
        "jpeg_dct", width=64, height=48, payload_bytes=16
    )
    result_j = analyze_all_bytes(encoded_jpeg.data)
    dct = [f for f in result_j.findings if f.family == "jpeg_dct"]
    assert [f.detector_name for f in dct] == [
        "dct-coefficient-pov-chisquare",
        "dct-calibrated-histogram",
    ]


def test_frozen_family_score_stays_pinned_to_pov():
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    result = analyze_all_bytes(encoded.data)
    pov = next(f for f in result.findings if f.detector_name == "lsb-pov-chisquare")
    assert _family_score(encoded, "spatial_lsb") == pytest.approx(pov.score)
    assert _family_score(clean, "spatial_lsb") is not None
    # The CL-14 benchmark on the original suite is unchanged in shape.
    report = benchmark_lsb(build_dataset(), bootstrap_replicates=0)
    assert report["detector"]["name"] == "lsb-pov-chisquare"
    assert report["positive_count"] == 3
    assert report["negative_count"] == 5


def test_benchmarks_validate_against_shipped_schemas(pairs_report, calibrated_report):
    jsonschema = pytest.importorskip("jsonschema")
    from pathlib import Path

    schemas = Path(__file__).resolve().parent.parent / "schemas"
    for name, report in (
        ("lsb-pairs-benchmark.schema.json", pairs_report),
        ("dct-calibrated-benchmark.schema.json", calibrated_report),
    ):
        schema = json.loads((schemas / name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(report))
        assert errors == [], f"{name}: {errors[:3]}"
