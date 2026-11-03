"""CL-62: genuinely adaptive attacker (score-oracle search + controls)."""

import pytest

from covertlens.adaptive import run_adaptive, validate_adaptive


@pytest.fixture(scope="module")
def report():
    return run_adaptive()


def test_adaptive_report_is_valid(report):
    assert validate_adaptive(report) == []
    assert report["separate_from_frozen_benchmark"] is True
    assert report["merged_into_frozen_claim"] is False


def test_every_family_searched_with_budget_and_controls(report):
    families = {e["family"]: e for e in report["experiments"]}
    assert set(families) == {"spatial_lsb", "jpeg_dct", "geometric"}
    for family, experiment in families.items():
        assert experiment["controls"]["n"] >= 1, family
        assert isinstance(experiment["confounded"], bool), family
        assert experiment["operating_points"], family
        for name, point in experiment["operating_points"].items():
            assert point["queries_used"] <= report["query_budget_per_point"], (
                family,
                name,
            )
            assert point["queries_used"] >= 1
            if point["max_payload_under"] is not None:
                assert point["score_at_max"] < point["threshold"]


def test_figure_reports_achieved_payload_per_point(report):
    points = report["figure"]["points"]
    assert points
    for point in points:
        assert point["family"]
        assert point["operating_point"] in ("triage", "quarantine")
        assert "achieved_payload" in point
        assert point["queries_used"] >= 1
