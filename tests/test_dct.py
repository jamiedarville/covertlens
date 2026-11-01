"""CL-15 acceptance tests: JPEG DCT detector and paired benchmark (DET-04).

AC1 original JPEG coefficient-domain evidence is analyzed
AC2 DCT scores, configuration and limitations are recorded
AC3 paired tests report false positives and recall by payload band
"""

import json

import pytest

from covertlens import ids
from covertlens.dct import (
    CONFIG_VERSION,
    DCT_DETECTOR_NAME,
    DCT_DETECTOR_VERSION,
    DctConfig,
    analyze_dct_bytes,
    analyze_dct_version,
    benchmark_dct,
    detect_dct,
    validate_dct_benchmark,
)
from covertlens.fixtures import build_dataset, build_pair
from covertlens.parsing import analyze_bytes, validate_finding, validate_result
from covertlens.store import ArtifactStore

TS = "2026-10-28T12:00:00Z"


@pytest.fixture(scope="module")
def dataset():
    return build_dataset()


@pytest.fixture(scope="module")
def report(dataset):
    return benchmark_dct(dataset, bootstrap_replicates=200)


def test_jpeg_coefficient_domain_is_scored_on_original_bytes():
    clean, encoded = build_pair("jpeg_dct", width=64, height=48, payload_bytes=64)
    for fixture in (clean, encoded):
        result = analyze_dct_bytes(fixture.data)
        assert result.status.value == "parsed"
        assert result.transform_applied is False
        assert result.content_hash == ids.content_hash(fixture.data)
        assert result.coefficients is not None  # quantized domain, no IDCT
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.coverage["domain"] == "quantized_coefficients"
        assert finding.coverage["blocks_examined"] == len(result.coefficients)
        assert (
            finding.coverage["coefficients_examined"] == len(result.coefficients) * 64
        )
        assert finding.coverage["carriers_examined"] > 0
        assert validate_result(result) == []
    assert (
        analyze_dct_bytes(encoded.data).findings[0].score
        > analyze_dct_bytes(clean.data).findings[0].score
    )


def test_scores_configuration_and_limitations_are_recorded():
    _, encoded = build_pair("jpeg_dct", width=64, height=48, payload_bytes=64)
    finding = analyze_dct_bytes(encoded.data).findings[0]
    assert finding.family == "jpeg_dct"
    assert finding.detector_name == DCT_DETECTOR_NAME
    assert finding.detector_version == DCT_DETECTOR_VERSION
    assert 0.0 <= finding.score <= 1.0
    assert finding.coverage["config_version"] == CONFIG_VERSION
    assert finding.coverage["applicable"] is True
    assert finding.evidence["detector_config_version"] == CONFIG_VERSION
    assert finding.evidence["statistic"] == (
        "coefficient_magnitude_pairs_of_values_chi_square"
    )
    assert finding.limitations  # limitations are always recorded
    assert any("coefficient" in text for text in finding.limitations)
    assert any("CL-27" in text for text in finding.limitations)
    assert validate_finding(finding) == []
    assert DctConfig().to_dict()["version"] == CONFIG_VERSION
    with pytest.raises(ValueError):
        DctConfig(carrier_min_magnitude=0)
    with pytest.raises(ValueError):
        DctConfig(pair_min_count=0)


def test_png_and_failed_parse_get_no_dct_finding():
    _, png = build_pair("spatial_lsb", width=32, height=24, payload_bytes=8)
    png_result = analyze_dct_bytes(png.data)
    assert png_result.media_kind == "png"
    assert png_result.findings == ()
    assert detect_dct(analyze_bytes(png.data)) is None
    clean, _ = build_pair("jpeg_dct", width=32, height=24, payload_bytes=8)
    corrupt = analyze_dct_bytes(clean.data[:40])
    assert corrupt.status.value == "corrupt"
    assert corrupt.findings == ()
    assert validate_result(corrupt) == []


def test_store_version_scoring_binds_exact_version():
    _, encoded = build_pair("jpeg_dct", width=32, height=24, payload_bytes=32)
    store = ArtifactStore()
    version = store.put_original(
        encoded.data, run_id="run_test", producer_id="agent-a", occurred_at=TS
    )
    result = analyze_dct_version(
        store, version.artifact_version_id, actor_id="detector"
    )
    assert result.artifact_version_id == version.artifact_version_id
    assert result.content_hash == version.content_hash
    assert len(result.findings) == 1
    assert validate_result(result) == []


def test_benchmark_reports_scores_by_payload_band(dataset, report):
    assert validate_dct_benchmark(report) == []
    assert report["detector"]["name"] == DCT_DETECTOR_NAME
    assert report["thresholds_status"] == "unfrozen_placeholder"
    dct_fixtures = [f for f in dataset if f.family == "jpeg_dct"]
    assert report["fixture_count"] == len(dct_fixtures)
    assert report["skipped_non_dct"] == len(dataset) - len(dct_fixtures)
    bands = report["by_payload_band"]
    assert bands["none"]["negative_count"] == 5
    for band in ("low", "medium", "high"):
        assert bands[band]["positive_count"] == 1
    means = {b: bands[b]["scores"]["mean"] for b in ("none", "low", "medium", "high")}
    assert means["none"] < means["low"] < means["medium"] < means["high"]
    json.dumps(report)


def test_paired_false_positives_and_recall_by_band(report):
    # Overall sweep: FP + TN always accounts for every negative.
    for point in report["sweep"]:
        assert point["fp"] + point["tn"] == report["negative_count"]
        assert point["tp"] + point["fn"] == report["positive_count"]
        fpr = point["false_positive_rate"]
        assert fpr["ci_low"] <= fpr["estimate"] <= fpr["ci_high"]
    # The none band carries the false-positive sweep.
    none_sweep = report["by_payload_band"]["none"]["sweep"]
    assert none_sweep[0]["fp"] == report["negative_count"]
    assert none_sweep[-1]["fp"] == 0
    # Each encoded band carries its own recall sweep.
    for band in ("low", "medium", "high"):
        band_sweep = report["by_payload_band"][band]["sweep"]
        assert band_sweep[0]["recall"]["estimate"] == 1.0
        assert band_sweep[-1]["recall"]["estimate"] == 0.0
        for point in band_sweep:
            assert point["tp"] + point["fn"] == 1
    # At a mid threshold the high band is recalled with no false positives.
    custom = benchmark_dct(build_dataset(), thresholds=[0.3], bootstrap_replicates=0)
    point = custom["sweep"][0]
    assert point["fp"] == 0
    assert custom["by_payload_band"]["high"]["sweep"][0]["recall"]["estimate"] == 1.0
    assert custom["by_payload_band"]["low"]["sweep"][0]["recall"]["estimate"] == 0.0


def test_expanded_pairs_show_band_ordering_and_weak_low_band():
    fixtures = []
    for seed in (101, 202, 303, 404, 505, 606, 707, 808):
        for i, payload_bytes in enumerate((12, 64, 192)):
            clean, encoded = build_pair(
                "jpeg_dct",
                width=64,
                height=48,
                payload_bytes=payload_bytes,
                cover_seed=seed,
                payload_seed=seed + 7,
            )
            if i == 0:
                fixtures.append(clean)
            fixtures.append(encoded)
    expanded = benchmark_dct(fixtures, bootstrap_replicates=200)
    assert validate_dct_benchmark(expanded) == []
    bands = expanded["by_payload_band"]
    means = {b: bands[b]["scores"]["mean"] for b in ("none", "low", "medium", "high")}
    assert means["none"] < means["low"] < means["medium"] < means["high"]
    assert bands["high"]["roc_auc_vs_negatives"] == 1.0
    assert bands["low"]["roc_auc_vs_negatives"] < bands["high"]["roc_auc_vs_negatives"]


def test_benchmark_rejects_out_of_range_inputs(dataset):
    with pytest.raises(ValueError):
        benchmark_dct(dataset, thresholds=[-0.1])
    with pytest.raises(ValueError):
        benchmark_dct(dataset, bootstrap_replicates=-1)
