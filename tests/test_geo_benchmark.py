"""CL-42 acceptance: benign controls, subfamily coverage, benchmark."""

import pytest

from covertlens.geo_benchmark import (
    benign_controls,
    run_geo_benchmark,
    validate_geo_benchmark,
)
from covertlens.geometric_fixtures import SUBFAMILIES


@pytest.fixture(scope="module")
def report():
    return run_geo_benchmark()


def test_all_five_subfamilies_reported_separately(report):
    assert set(report["subfamilies"]) == set(SUBFAMILIES)
    assert report["coverage"]["evaluated_subfamilies"] == list(SUBFAMILIES)
    # No general geometric coverage is claimed from any subfamily.
    assert report["coverage"]["general_geometric_coverage_claimed"] is False
    for block in report["subfamilies"].values():
        assert block["encoded"]["recall_any_signal"]["n"] >= 5
        assert block["benign"]["false_structure_claims"]["n"] >= 5
        for metric in (
            block["encoded"]["recall_any_signal"],
            block["benign"]["false_structure_claims"],
        ):
            assert metric["wilson_95"]["low"] is not None


def test_benign_controls_distinguished(report):
    kinds = set(report["benign_controls"])
    assert kinds == {"skyline", "chart", "abstract", "benign_scene"}
    for block in report["benign_controls"].values():
        # No benign control is ever structure-claimed.
        assert block["false_structure_claims"]["successes"] == 0
        assert block["context"]
    # Legitimate charts quantize (data values) but claim no structure:
    # distinguished by scene context plus the structure test (GEO-05).
    assert (
        report["benign_controls"]["chart"]["classifications"].get(
            "structure_claimed", 0
        )
        == 0
    )


def test_benchmark_separates_recall_from_false_claims(report):
    for block in report["subfamilies"].values():
        # Encoded sequences are separated from benign geometry.
        assert block["encoded"]["recall_any_signal"]["rate"] >= 0.8
        assert block["benign"]["false_structure_claims"]["rate"] == 0.0
    assert report["prevalence"]["encoded_n"] > 0
    assert report["prevalence"]["benign_n"] > report["prevalence"]["encoded_n"]
    assert report["benchmark_passed"] is True
    assert validate_geo_benchmark(report) == []


def test_height_or_size_alone_never_enforces(report):
    assert report["enforcement"]["height_or_size_alone_triggers_enforcement"] is False
    # Under the CL-54 freeze structure is withheld; quantization never is.
    assert report["enforcement"]["mode"] == "frozen_ladder"
    assert report["enforcement"]["structure_claims_withheld"] is True
    assert report["detector"]["enforceable"] is True
    assert report["coverage_checks"]["height_or_size_alone_never_enforces"] is True
    assert report["equated_with_collusion"] is False


def test_controls_are_deterministic_and_benign_labelled():
    first, second = benign_controls(2), benign_controls(2)
    assert [c["content_hash"] for c in first] == [c["content_hash"] for c in second]
    assert all(c["expected"] == "benign" for c in first)
    assert {c["kind"] for c in first} == {
        "skyline",
        "chart",
        "abstract",
        "benign_scene",
    }


def test_cl78_rows_jitter_stride_and_random_payloads(report):
    jitter = report["jittered_attacker"]
    assert set(jitter) == {"height_position", "gap_timing"}
    for row in jitter.values():
        assert set(row["amplitudes"]) == {"+/-1px", "+/-2px", "+/-3px"}
        one = row["amplitudes"]["+/-1px"]["structured"]["structure_recall"]
        base = row["baseline_unjittered"]["structured"]["structure_recall"]
        assert one["successes"] >= base["successes"] - 1
    assert set(report["every_other_level_attacker"]) == {
        "height_position",
        "gap_timing",
        "angle_tilt",
    }
    random_rows = report["random_payload_structure"]
    assert random_rows["binomial_tail_at_stated_level"] >= 0.01
    # The positive control is a fixed structured word, not a seed scan.
    scene = report["scene_context"]
    assert scene["encoded_structured_no_declaration"]["classification"] == (
        "structure_claimed"
    )
    assert scene["encoded_structured_declared_height"]["verdict"] != "log"
