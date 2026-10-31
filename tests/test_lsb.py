"""CL-14 acceptance tests: LSB spatial detector and benchmark (DET-03).

AC1 LSB scores and applicable coverage are versioned
AC2 clean/encoded test performance is broken down by payload band
AC3 threshold-free results include precision/recall and uncertainty
"""

import json

import pytest

from covertlens import ids
from covertlens.fixtures import build_dataset, build_pair
from covertlens.lsb import (
    CONFIG_VERSION,
    LSB_DETECTOR_NAME,
    LSB_DETECTOR_VERSION,
    LsbConfig,
    analyze_lsb_bytes,
    analyze_lsb_version,
    benchmark_lsb,
    detect_lsb,
    validate_benchmark,
)
from covertlens.parsing import analyze_bytes, validate_finding, validate_result
from covertlens.store import ArtifactStore

TS = "2026-10-28T12:00:00Z"


@pytest.fixture(scope="module")
def dataset():
    return build_dataset()


@pytest.fixture(scope="module")
def report(dataset):
    return benchmark_lsb(dataset, bootstrap_replicates=200)


def test_png_score_is_versioned_with_applicable_coverage():
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    for fixture in (clean, encoded):
        result = analyze_lsb_bytes(fixture.data)
        assert result.status.value == "parsed"
        assert result.content_hash == ids.content_hash(fixture.data)
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.family == "spatial_lsb"
        assert finding.detector_name == LSB_DETECTOR_NAME
        assert finding.detector_version == LSB_DETECTOR_VERSION
        assert finding.schema_version == "1.0.0"
        assert 0.0 <= finding.score <= 1.0
        assert finding.coverage["applicable"] is True
        assert finding.coverage["samples_examined"] == 64 * 48 * 3
        assert finding.coverage["pixels_examined"] == 64 * 48
        assert finding.coverage["channels"] == 3
        assert finding.coverage["pairs_total"] == 128
        assert finding.coverage["pairs_used"] >= 2
        assert finding.coverage["config_version"] == CONFIG_VERSION
        assert finding.evidence["detector_config_version"] == CONFIG_VERSION
        assert finding.evidence["statistic"] == "pairs_of_values_chi_square"
        assert validate_finding(finding) == []
        assert validate_result(result) == []
        assert validate_result(result.to_dict()) == []
    clean_score = analyze_lsb_bytes(clean.data).findings[0].score
    encoded_score = analyze_lsb_bytes(encoded.data).findings[0].score
    assert encoded_score > clean_score


def test_detector_scores_rise_with_payload_band():
    means = {}
    for band, payload_bytes in (("none", 8), ("low", 12), ("medium", 64), ("high", 192)):
        scores = []
        for seed in (101, 202, 303):
            clean, encoded = build_pair(
                "spatial_lsb", width=64, height=48,
                payload_bytes=payload_bytes, cover_seed=seed, payload_seed=seed + 7,
            )
            fixture = clean if band == "none" else encoded
            scores.append(analyze_lsb_bytes(fixture.data).findings[0].score)
        means[band] = sum(scores) / len(scores)
    assert means["none"] < means["low"] < means["medium"] < means["high"]


def test_jpeg_and_failed_parse_get_no_lsb_finding():
    _, jpeg = build_pair("jpeg_dct", width=32, height=24, payload_bytes=8)
    jpeg_result = analyze_lsb_bytes(jpeg.data)
    assert jpeg_result.media_kind == "jpeg"
    assert jpeg_result.findings == ()
    assert detect_lsb(analyze_bytes(jpeg.data)) is None
    clean, _ = build_pair("spatial_lsb", width=32, height=24, payload_bytes=8)
    corrupt = analyze_lsb_bytes(clean.data[: len(clean.data) // 2])
    assert corrupt.status.value == "corrupt"
    assert corrupt.findings == ()
    assert validate_result(corrupt) == []


def test_store_version_scoring_binds_exact_version():
    _, encoded = build_pair("spatial_lsb", width=32, height=24, payload_bytes=32)
    store = ArtifactStore()
    version = store.put_original(
        encoded.data, run_id="run_test", producer_id="agent-a", occurred_at=TS)
    result = analyze_lsb_version(store, version.artifact_version_id, actor_id="detector")
    assert result.artifact_version_id == version.artifact_version_id
    assert result.content_hash == version.content_hash
    assert len(result.findings) == 1
    assert validate_result(result) == []
    history = store.access_history(version.artifact_version_id)
    assert [(h.actor_id, h.purpose) for h in history] == [("detector", "analysis")]


def test_config_is_versioned_and_validated():
    assert LsbConfig().to_dict() == {"version": CONFIG_VERSION, "pair_min_count": 4}
    with pytest.raises(ValueError):
        LsbConfig(pair_min_count=0)
    with pytest.raises(ValueError):
        LsbConfig(version="")


def test_benchmark_breaks_performance_down_by_payload_band(dataset, report):
    assert validate_benchmark(report) == []
    assert report["detector"]["name"] == LSB_DETECTOR_NAME
    assert report["detector"]["version"] == LSB_DETECTOR_VERSION
    assert report["detector"]["config"]["version"] == CONFIG_VERSION
    assert report["thresholds_status"] == "unfrozen_placeholder"
    lsb_fixtures = [f for f in dataset if f.family == "spatial_lsb"]
    assert report["fixture_count"] == len(lsb_fixtures)
    assert report["skipped_non_lsb"] == len(dataset) - len(lsb_fixtures)
    assert report["positive_count"] == 3
    assert report["negative_count"] == 5
    bands = report["by_payload_band"]
    assert bands["none"]["negative_count"] == 5
    for band in ("low", "medium", "high"):
        assert bands[band]["positive_count"] == 1
        assert bands[band]["scores"]["count"] == 1
    rows = {r["fixture_id"]: r for r in report["rows"]}
    for fixture in lsb_fixtures:
        row = rows[fixture.fixture_id]
        assert row["payload_band"] == fixture.payload_band
        assert row["bits_per_pixel"] == round(fixture.bits_per_pixel, 6)
        assert row["label"] == (1 if fixture.role == "encoded" else 0)
        assert row["applicable"] is True and row["score"] is not None
    json.dumps(report)


def test_threshold_free_sweep_has_precision_recall_with_uncertainty(report):
    sweep = report["sweep"]
    assert len(sweep) >= 3
    assert sweep[0]["threshold"] == 0.0 and sweep[-1]["threshold"] == 1.0
    for point in sweep:
        assert point["tp"] + point["fn"] == report["positive_count"]
        assert point["fp"] + point["tn"] == report["negative_count"]
        for name in ("precision", "recall", "false_positive_rate"):
            block = point[name]
            if block["estimate"] is not None:
                assert 0.0 <= block["ci_low"] <= block["estimate"] <= block["ci_high"] <= 1.0
    recalls = [p["recall"]["estimate"] for p in sweep]
    assert recalls == sorted(recalls, reverse=True)  # higher bar, fewer hits
    for key in ("roc_auc", "pr_auc"):
        block = report[key]
        assert 0.0 <= block["ci_low"] <= block["estimate"] <= block["ci_high"] <= 1.0
        assert block["bootstrap_replicates"] == 200
    # Same seed reproduces the same intervals exactly.
    again = benchmark_lsb(build_dataset(), bootstrap_replicates=200)
    assert again["roc_auc"] == report["roc_auc"]
    assert again["pr_auc"] == report["pr_auc"]


def test_expanded_pairs_show_band_ordering_and_low_band_uncertainty():
    fixtures = []
    for seed in (101, 202, 303, 404, 505, 606, 707, 808):
        for i, payload_bytes in enumerate((12, 64, 192)):
            clean, encoded = build_pair(
                "spatial_lsb", width=64, height=48,
                payload_bytes=payload_bytes, cover_seed=seed, payload_seed=seed + 7,
            )
            if i == 0:
                fixtures.append(clean)
            fixtures.append(encoded)
    expanded = benchmark_lsb(fixtures, bootstrap_replicates=200)
    assert validate_benchmark(expanded) == []
    bands = expanded["by_payload_band"]
    means = {band: bands[band]["scores"]["mean"] for band in ("none", "low", "medium", "high")}
    assert means["none"] < means["low"] < means["medium"] < means["high"]
    assert bands["medium"]["roc_auc_vs_negatives"] == 1.0
    assert bands["high"]["roc_auc_vs_negatives"] == 1.0
    # The low band is honestly weaker than the easier bands.
    assert bands["low"]["roc_auc_vs_negatives"] < 1.0
    assert expanded["roc_auc"]["ci_low"] < expanded["roc_auc"]["estimate"]


def test_benchmark_rejects_out_of_range_thresholds_and_replicates(dataset):
    with pytest.raises(ValueError):
        benchmark_lsb(dataset, thresholds=[1.5])
    with pytest.raises(ValueError):
        benchmark_lsb(dataset, bootstrap_replicates=-1)
    custom = benchmark_lsb(dataset, thresholds=[0.25], bootstrap_replicates=0)
    assert [p["threshold"] for p in custom["sweep"]] == [0.25]
    assert validate_benchmark(custom) == []
