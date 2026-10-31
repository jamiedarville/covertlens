import pytest

from covertlens.robustness import run_robustness, validate_robustness


@pytest.fixture(scope="module")
def report():
    return run_robustness()


def _by_name(report, name):
    return next(e for e in report["experiments"] if e["name"] == name)


def test_separate_from_frozen_benchmark(report):
    assert validate_robustness(report) == []
    assert report["separate_from_frozen_benchmark"] is True
    assert report["merged_into_frozen_claim"] is False
    assert report["frozen_benchmark_reference"]["schema"] == "covertlens.frozen-benchmark"


def test_adaptive_attempts_evade_enforcement(report):
    reduced = _by_name(report, "adaptive_reduced_rate_lsb")
    assert reduced["attempts"]["withheld"] == 0
    keywords = _by_name(report, "adaptive_allowed_keyword_metadata")
    assert keywords["outcome"] == "evaded"
    assert keywords["attempts"]["at_triage"] == 0


def test_unseen_configurations_bound_the_claim(report):
    assert _by_name(report, "unseen_jpeg_quality_50")["outcome"] == "detected"
    assert _by_name(report, "unseen_jpeg_quality_75")["outcome"] == "detected"
    assert _by_name(report, "unseen_cover_pattern_blocks")["outcome"] == "evaded"
    larger = _by_name(report, "unseen_larger_image_128x96")
    assert larger["attempts"]["withheld"] == 0
    assert larger["attempts"]["at_triage"] == 0


def test_confounded_and_low_signal_results_stay_unresolved(report):
    smooth = _by_name(report, "unseen_cover_pattern_smooth")
    assert smooth["outcome"] == "confounded_unresolved"
    # The clean control fails exactly like the attempt: confounded.
    assert smooth["controls"]["withheld"] == smooth["controls"]["n"] == 1
    assert any(
        u["experiment"] == "unseen_cover_pattern_smooth" for u in report["unresolved"]
    )
    sequence = _by_name(report, "adaptive_low_signal_sequence")
    assert sequence["kind"] == "low_signal_sequence"
    assert sequence["sequence_view"]["any_withheld"] is False
    assert sequence["attempts"]["n"] == 6


def test_limitations_documented(report):
    assert len(report["coverage_limitations"]) >= 4
    assert any("densit" in text for text in report["coverage_limitations"])
