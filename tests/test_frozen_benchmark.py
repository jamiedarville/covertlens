from covertlens.frozen_benchmark import (
    clean_run_stability,
    run_frozen_evaluation,
    validate_frozen_benchmark,
    wilson_interval,
)
from covertlens.calibration import load_frozen_thresholds


def test_wilson_interval_bounds():
    assert wilson_interval(0, 0) == {"low": None, "high": None}
    interval = wilson_interval(2, 2)
    assert interval["high"] == 1.0
    assert interval["low"] < 0.5  # n=2: the lower bound is honestly low


def test_held_out_benchmark_excludes_calibration_and_reports_targets():
    report = run_frozen_evaluation(clean_runs=320, probe_runs=30)
    assert validate_frozen_benchmark(report) == []
    # No fixture used to calibrate CL-27 appears in the evaluation set.
    assert report["calibration_overlap_fixture_ids"] == []
    assessment = report["assessment"]
    # Targets are met on held-out point estimates, with no universal
    # claim: intervals/coverage limits are stated as tradeoffs.
    assert all(assessment["recall_target_met_by_family"].values())
    assert all(assessment["precision_target_met_by_family"].values())
    assert assessment["universal_claim"] is False
    assert len(report["tradeoffs"]) >= 3
    for family, block in report["held_out"]["families"].items():
        assert block["recall_at_triage"]["wilson95"]["low"] is not None
        # Held-out positives are high-band only; that narrowing is
        # reported rather than smoothed over.
        assert block["bands_without_held_out_positives"] == ["low", "medium"]


def test_clean_run_stability_within_claimed_coverage():
    config, _ = load_frozen_thresholds()
    stability = clean_run_stability(config, runs=320)
    assert stability["runs"] >= 300
    assert stability["false_failure_rate"]["value"] <= 0.01
    assert stability["verdict_counts"].get("fail_run", 0) == 0


def test_clean_smooth_covers_are_outside_the_frozen_claim():
    # Measured tradeoff behind the narrowed coverage: clean smooth
    # PNG covers fire the LSB detector above the frozen fail point.
    config, _ = load_frozen_thresholds()
    probes = clean_run_stability(config, runs=30, seed_base=200_000,
                                  patterns=("smooth",))
    # Half the runs are PNG/LSB; every one of those false-fails.
    assert probes["per_pattern"]["smooth"]["false_failure_rate"]["value"] >= 0.5
