import pytest

from covertlens.geometric_fixtures import (
    SUBFAMILIES,
    assign_geo_splits,
    build_geo_dataset,
    build_geo_pair,
    geo_ground_truth,
    geo_manifest,
    measure_attributes,
    validate_geo_splits,
    verify_geo_fixture,
)
from covertlens.fixtures import _load_png


@pytest.fixture(scope="module")
def dataset():
    return build_geo_dataset()


def test_dataset_covers_all_subfamilies_with_pairs(dataset):
    assert len(dataset) == 24
    for subfamily in SUBFAMILIES:
        roles = {f.role for f in dataset if f.subfamily == subfamily}
        assert {"clean", "encoded"} <= roles
    negatives = [f for f in dataset if f.role == "negative"]
    assert {f.negative_kind for f in negatives} == {
        "legitimate_chart", "unencoded_scene", "benign_edit", "generator_variation",
    }


def test_every_fixture_verified_by_independent_remeasurement(dataset):
    for fixture in dataset:
        assert verify_geo_fixture(fixture), fixture.fixture_id
    # Encoded payloads are symbol sequences (declared units), and
    # re-measurement recovers them exactly from the raster alone.
    for fixture in dataset:
        if fixture.role != "encoded":
            continue
        pixels, w, h = _load_png(fixture.data)
        _attrs, symbols = measure_attributes(pixels, w, h, fixture.subfamily)
        assert tuple(symbols) == fixture.symbols


def test_provenance_units_and_separate_ground_truth(dataset):
    manifest = geo_manifest(dataset)
    assert manifest["family"] == "geometric"
    for row in manifest["fixtures"]:
        assert row["content_hash"].startswith("sha256:")
        assert row["generator"]["name"] and row["generator"]["seed"] is not None
        assert row["encoder"]["config"]["unit"]
        assert "symbols" not in row and "attributes" not in row
    with pytest.raises(PermissionError):
        geo_ground_truth(dataset, role="detector")
    truth = geo_ground_truth(dataset, role="scorer")
    assert len(truth) == len(dataset)


def test_legitimate_chart_is_a_benign_negative_with_grid_heights(dataset):
    chart = next(f for f in dataset if f.negative_kind == "legitimate_chart")
    assert chart.context == "chart"
    assert chart.role == "negative"
    # Its heights are grid-snapped by design: geometry alone must
    # never be the enforcement trigger (GEO-05).
    grid = [16 + 10 * s for s in range(8)]
    assert all(any(abs(a - g) < 1.6 for g in grid) for a in chart.attributes)


def test_splits_follow_lineage_groups(dataset):
    assignments = assign_geo_splits(dataset)
    assert validate_geo_splits(dataset, assignments) == []
    assert set(assignments.values()) <= {"train", "calibration", "held_out"}
    with pytest.raises(ValueError):
        build_geo_pair("not_a_subfamily")
