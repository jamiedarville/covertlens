"""CL-68: banded fixture suite across cover textures (small target, fast)."""

from covertlens.banded_fixtures import (
    BAND_BYTES,
    BANDS,
    SEED_BASE,
    TEXTURES,
    build_banded_dataset,
    held_out_positive_counts,
    texture_of,
)
from covertlens.metadata_fixtures import verify_metadata_fixture
from covertlens.splits import validate_no_leakage

TARGET = 2


def _small():
    return build_banded_dataset(held_out_target=TARGET)


def test_cells_reach_the_held_out_target_or_name_why_not():
    dataset = _small()
    cells = {(c.family, c.texture, c.band): c for c in dataset.cells}
    for family in ("spatial_lsb", "jpeg_dct"):
        for texture in TEXTURES:
            for band in BANDS:
                cell = cells[(family, texture, band)]
                if (
                    family == "jpeg_dct"
                    and band == "high"
                    and texture != "gradient_noise"
                ):
                    # The CL-9 DCT encoder embeds only in |AC| >= 2;
                    # low-texture covers cannot hold a high-band payload.
                    assert cell.constructible is False
                    assert "capacity" in (cell.reason or "")
                    continue
                assert cell.constructible
                # Sizing stops the moment the target is met: it never
                # looks at scores or labels, only the split hash.
                assert cell.split_pairs["held_out"] == TARGET
    for band in BANDS:
        assert cells[("metadata", "mixed", band)].split_pairs["held_out"] == TARGET


def test_payloads_verify_land_in_their_band_and_do_not_leak():
    dataset = _small()
    assert validate_no_leakage(list(dataset.fixtures), dataset.assignments) == []
    for fixture in dataset.fixtures:
        assert texture_of(fixture) in TEXTURES
        if fixture.family == "metadata":
            assert verify_metadata_fixture(fixture)
        elif fixture.role == "encoded":
            assert fixture.verify_payload()
        if fixture.role == "encoded":
            low, high = BAND_BYTES[fixture.payload_band]
            assert low <= fixture.payload_bytes <= high
            assert int(fixture.generator["seed"]) >= SEED_BASE


def test_suite_is_deterministic_and_counts_by_texture():
    first = _small()
    build_banded_dataset.cache_clear()
    second = _small()
    assert [f.fixture_id for f in first.fixtures] == [
        f.fixture_id for f in second.fixtures
    ]
    counts = held_out_positive_counts(second.fixtures, second.assignments)
    for texture in TEXTURES:
        assert counts["spatial_lsb"][texture] == {band: TARGET for band in BANDS}
    summary = second.summary()
    assert summary["held_out_target"] == TARGET
    assert summary["fixture_count"] == len(second.fixtures)
