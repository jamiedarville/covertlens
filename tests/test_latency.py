from covertlens.latency import (
    gate_reliability_check,
    limit_behavior_checks,
    measure_class,
    percentile,
    run_reliability_report,
    validate_latency_report,
)

SMALL = (
    {"name": "small", "width": 256, "height": 192, "media": ("png", "jpeg")},
    {"name": "medium", "width": 512, "height": 384, "media": ("png",)},
)


def test_percentile_nearest_rank():
    assert percentile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0], 0.95) == 3.0


def test_small_classes_meet_the_proposal():
    for media in ("png", "jpeg"):
        row = measure_class(media, 256, 192, repetitions=3)
        assert row["statuses"] == {"parsed": 3}
        assert row["p95_s"] <= 2.0
        assert row["meets_proposal"] is True


def test_timeout_and_oversize_are_explicit_and_withhold():
    checks = limit_behavior_checks()
    assert checks["timeout_status"] == "timeout"
    assert checks["timeout_error_class"] == "analysis_timeout"
    assert checks["oversized_status"] == "oversized"
    assert checks["oversized_error_class"] == "oversized_input"
    # Enforcement mode: infrastructure outcome, no clean verdict,
    # and the recipient never receives bytes.
    assert checks["enforcement_outcome_kind"] == "infrastructure"
    assert checks["enforcement_run_outcome"] == "failed_infrastructure"
    assert checks["enforcement_clean_verdict"] is False
    assert checks["enforcement_served_bytes"] is False


def test_gate_reliability_under_concurrent_attempts():
    reliability = gate_reliability_check(deliveries=12, workers=8)
    assert reliability["route_served"] == reliability["expected_route_served"]
    assert reliability["link_served"] == reliability["expected_link_served"]
    assert reliability["access_report"]["unauthorized_served"] == 0


def test_reliability_report_shape_and_narrowed_claim():
    report = run_reliability_report(repetitions=3, classes=SMALL)
    assert validate_latency_report(report) == []
    assert report["assessment"]["universal_claim"] is False
    assert report["assessment"]["proposal_met_for_jpeg_envelope"] is False
    assert report["concurrent"]["workers"] == 4
    assert len(report["tradeoffs"]) >= 3
