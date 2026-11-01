import pytest

from covertlens.route_audit import run_route_audit, validate_route_audit


@pytest.fixture(scope="module")
def report():
    return run_route_audit()


def test_every_inventoried_route_is_audited(report):
    assert validate_route_audit(report) == []
    assert [r["route_id"] for r in report["routes"]] == [
        "R-01",
        "R-02",
        "R-03",
        "R-04",
        "R-05",
        "R-06",
        "R-07",
        "R-08",
    ]
    assert report["routes_failed"] == []
    assert report["routes_exempt_verified"] == ["R-08"]


def test_gated_routes_pass_creation_hash_gate_access(report):
    for row in report["routes"]:
        if not row["gate_required"]:
            continue
        checks = row["checks"]
        assert checks["creation"] is True
        assert checks["hash"] is True
        assert checks["gate_pending_denied"] is True
        assert checks["gate_withheld_denied"] is True
        assert checks["permitted_served_exact_bytes"] is True
        assert checks["unauthorized_served"] == 0


def test_r06_derivative_gap_is_named_not_hidden(report):
    assert report["routes_partial"] == ["R-06"]
    assert report["full_coverage_claimed"] is False
    assert any("R-06" in gap for gap in report["gaps"])
    r06 = next(r for r in report["routes"] if r["route_id"] == "R-06")
    assert r06["checks"]["derivative_blocked_when_withheld"] is True
    assert r06["checks"]["derivative_from_served_bytes"] is True


def test_missing_trace_links_have_explicit_reasons(report):
    trace = report["trace"]
    assert trace["all_missing_explained"] is True
    reasons = {(r["missing"]) for r in trace["missing_link_reasons"]}
    # Pending verdict, unrecorded parse and withheld not_observed
    # are each classified rather than silently absent.
    assert "verdict_reference" in reasons
    assert "parse_event" in reasons
    assert "recipient_parse_outcome" in reasons
