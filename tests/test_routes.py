"""CL-7 AC3: every file-reference and tool-output image route is inventoried."""

from covertlens.routes import ROUTES, routes_by_kind, validate_inventory


def test_inventory_is_valid_and_ids_unique():
    assert validate_inventory() == []
    assert len({r.route_id for r in ROUTES}) == len(ROUTES)


def test_both_required_kinds_are_covered():
    kinds = {r.kind for r in ROUTES}
    assert "file_reference" in kinds
    assert "tool_output" in kinds
    assert routes_by_kind("tool_output")
    assert routes_by_kind("file_reference")


def test_every_route_is_gated_or_has_an_explicit_exception():
    for route in ROUTES:
        if route.gate_required:
            assert route.exception_reason is None
        else:
            assert route.exception_reason  # no silent ungated route


def test_gate_bypass_paths_are_inventoried():
    names = {r.name for r in ROUTES}
    # Paths CL-18 calls out as equivalent to direct delivery.
    assert "cached_link_access" in names
    assert "artifact_store_direct_access" in names
    assert "tool_output_image" in names
    assert "agent_file_reference" in names


def test_every_route_names_an_interception_point():
    for route in ROUTES:
        assert route.interception_point
        assert route.carries in ("bytes", "reference", "derivative")
