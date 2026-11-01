"""CL-43 acceptance: grid discovery replaces handed-down grids."""

import random
from pathlib import Path

import pytest

from covertlens.geometric import analyze_geometric_bytes
from covertlens.geometric_fixtures import (
    build_attacker_geo_pair,
    build_geo_dataset,
)
from covertlens.grid import discover_grid

_CHANNEL = {
    "height_position": ("height", 1.6),
    "gap_timing": ("gap", 1.6),
    "angle_tilt": ("angle", 3.5),
}
_QUANTIZED = ("quantized_without_structure", "structure_claimed")


def test_discover_grid_recovers_attacker_step():
    rng = random.Random(7)
    values = [20.0 + 7.0 * rng.randrange(8) for _ in range(12)]
    block = discover_grid(values, tolerance=1.6)
    assert block["grid"]["source"] == "discovered"
    assert abs(block["step"] - 7.0) <= 1.6
    assert block["support_fraction"] == 1.0
    assert block["levels_used"] >= 3
    assert block["null_exceedance"] <= 0.05
    assert block["rayleigh_R"] > 0.9


def test_discover_grid_continuous_sequence_is_not_significant():
    rng = random.Random(11)
    values = [rng.uniform(10, 90) for _ in range(12)]
    block = discover_grid(values, tolerance=1.6)
    assert block["null_exceedance"] > 0.05


def test_geometric_module_has_no_fixture_grid_import():
    source = Path("covertlens/geometric.py").read_text()
    assert "geometric_fixtures" not in source
    assert "GRIDS" not in source


@pytest.fixture(scope="module")
def dataset():
    return build_geo_dataset()


def test_channels_report_discovered_grids(dataset):
    encoded = next(f for f in dataset if f.role == "encoded")
    report = analyze_geometric_bytes(encoded.data)
    for block in report["channels"].values():
        assert block["grid"]["source"] == "discovered"
        for key in ("step", "offset", "rms_residual", "max_residual",
                    "supporting", "levels_used", "rayleigh_R"):
            assert key in block


def test_original_grid_encoded_quantized_and_clean_no_signal(dataset):
    for fixture in dataset:
        report = analyze_geometric_bytes(fixture.data)
        if fixture.role == "encoded":
            assert report["classification"] in _QUANTIZED, fixture.fixture_id
        elif fixture.role == "clean":
            assert report["classification"] == "no_signal", fixture.fixture_id
            primary = report["channels"][report["primary_channel"]]
            assert not primary.get("quantized")


def test_attacker_grid_step_matches_for_at_least_40_encoded():
    checked = 0
    for subfamily, (channel, tolerance) in _CHANNEL.items():
        for j in range(14):
            _clean, encoded = build_attacker_geo_pair(
                subfamily, scene_seed=4100 + 31 * j,
                payload_seed=910 + 7 * j, grid_seed=6000 + 101 * j,
            )
            report = analyze_geometric_bytes(encoded.data)
            assert report["classification"] in _QUANTIZED, (
                subfamily, j, report["classification"])
            discovered = report["channels"][channel]["step"]
            encoder_step = encoded.encoder["config"]["grid"]["step"]
            assert discovered is not None
            assert abs(discovered - encoder_step) <= tolerance, (
                subfamily, j, discovered, encoder_step)
            checked += 1
    assert checked >= 40


def test_declared_grid_prior_path():
    _clean, encoded = build_attacker_geo_pair(
        "height_position", scene_seed=321, payload_seed=654, grid_seed=2222)
    grid = encoded.encoder["config"]["grid"]
    declared = {"height": {"base": grid["base"], "step": grid["step"]}}
    report = analyze_geometric_bytes(encoded.data, declared_grid=declared)
    assert report["classification"] in _QUANTIZED
    height = report["channels"]["height"]
    assert height["declared"]["support_fraction"] >= 0.9
    assert height["declared_vs_discovered_step_ratio"] == pytest.approx(
        1.0, abs=0.25)
