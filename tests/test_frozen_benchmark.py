import pytest

from covertlens.calibration import load_frozen_thresholds
from covertlens.frozen_benchmark import (
    clean_run_stability,
    run_frozen_evaluation,
    validate_frozen_benchmark,
    wilson_interval,
)


def test_wilson_interval_bounds():
    assert wilson_interval(0, 0) == {"low": None, "high": None}
    interval = wilson_interval(2, 2)
    assert interval["high"] == 1.0
    assert interval["low"] < 0.5  # n=2: the lower bound is honestly low


@pytest.fixture(scope="module")
def report():
    return run_frozen_evaluation()


def test_held_out_benchmark_excludes_calibration_and_reports_targets(report):
    assert validate_frozen_benchmark(report) == []
    # No fixture used to calibrate appears in the evaluation set.
    assert report["calibration_overlap_fixture_ids"] == []
    assessment = report["assessment"]
    assert assessment["universal_claim"] is False
    assert len(report["tradeoffs"]) >= 3
    assert all(assessment["recall_target_met_by_family"].values())
    # Measured with real sample sizes (CL-68): one clean held-out JPEG
    # crosses the DCT quarantine point, so DCT enforcement precision
    # misses 0.99 on the point estimate. Reported, never hidden.
    assert assessment["precision_target_met_by_family"] == {
        "spatial_lsb": True,
        "jpeg_dct": False,
        "metadata": True,
    }
    for family, block in report["held_out"]["families"].items():
        met = assessment["precision_target_met_by_family"][family]
        assert met == (block["enforcement_precision"]["value"] >= 0.99)
        assert block["recall_at_triage"]["wilson95"]["low"] is not None
        assert block["bands_without_held_out_positives"] == []


def test_each_family_has_twenty_held_out_positives_per_calibrated_band(report):
    """CL-68 acceptance: at least 20 held-out positives per calibrated band."""
    frozen = load_frozen_thresholds()[1]
    for family, block in report["held_out"]["families"].items():
        bands = frozen["families"][family]["calibrated_payload_bands"]
        assert bands == ["high", "low", "medium"]
        for band in bands:
            assert block["positives_by_band"][band] >= 20, (family, band)
            assert block["recall_by_band"][band]["wilson95"]["low"] is not None
    assert all(report["assessment"]["held_out_band_counts_met_by_family"].values())
    # Out-of-coverage textures are measured with the same depth where
    # the encoder can build the band; the rest is named, not skipped.
    for cell in report["banded_suite"]["cells"]:
        if cell["constructible"]:
            assert cell["split_pairs"]["held_out"] >= 20
        else:
            assert cell["family"] == "jpeg_dct" and cell["band"] == "high"
            assert "capacity" in cell["reason"]


def test_stability_is_measured_on_all_three_textures_and_exclusions_named(report):
    """CL-68 acceptance: stability covers every texture, or names the rest."""
    stability = report["clean_run_stability"]
    assert set(stability["per_pattern"]) == {"gradient_noise", "smooth", "blocks"}
    for block in stability["per_pattern"].values():
        assert block["runs"] >= 300
    for cell in stability["claimed_cells"]:
        assert cell["false_failure_rate"]["value"] <= 0.01
    assert stability["runs"] >= 300
    assert stability["false_failure_rate"]["value"] <= 0.01
    excluded = {(r["texture"], r["media"]): r for r in report["stability_exclusions"]}
    assert report["assessment"]["stability_claim_covers_all_textures"] is (not excluded)
    for row in excluded.values():
        assert row["false_failure_rate"]["value"] > 0.01
        assert row["runs"] >= 150
    # The measured smooth-PNG false failure is excluded, by name.
    assert excluded[("smooth", "png")]["false_failure_rate"]["value"] >= 0.5
    assert "smooth PNG" in report["tradeoffs"][1]


def test_low_band_triage_alternative_is_reported_not_shipped(report):
    for family in ("spatial_lsb", "jpeg_dct"):
        row = report["triage_alternatives"][family]
        assert row["shipped"] is False
        assert (
            row["clean_flag_rate_alternative"]["value"]
            < row["clean_flag_rate_shipped"]["value"]
        )


def test_clean_run_stability_within_claimed_coverage():
    config, _ = load_frozen_thresholds()
    stability = clean_run_stability(config, runs=320)
    assert stability["runs"] >= 300
    assert stability["false_failure_rate"]["value"] <= 0.01


def test_clean_smooth_covers_are_outside_the_frozen_claim():
    # Measured tradeoff behind the narrowed coverage: clean smooth
    # PNG covers fire the LSB detector above the frozen fail point.
    config, _ = load_frozen_thresholds()
    probes = clean_run_stability(
        config, runs=30, seed_base=200_000, patterns=("smooth",)
    )
    # Half the runs are PNG/LSB; every one of those false-fails.
    assert probes["per_pattern"]["smooth"]["false_failure_rate"]["value"] >= 0.5
