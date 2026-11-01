"""CL-22 acceptance tests: metadata fixtures and benign controls (DT-06).

AC1 known metadata payloads and clean matched controls are verified
AC2 allowed task metadata exceptions are represented
AC3 fixture lineage, payload units and split rules match the initial dataset
"""

import pytest

from covertlens.metadata_fixtures import (
    ALLOWED_TASK_METADATA,
    PAYLOAD_KEYWORD,
    build_metadata_dataset,
    build_metadata_pair,
    extract_metadata_payload,
    metadata_entries,
    verify_metadata_fixture,
)
from covertlens.parsing import analyze_bytes
from covertlens.splits import assign_splits, validate_no_leakage


@pytest.fixture(scope="module")
def dataset():
    return build_metadata_dataset()


def test_payloads_and_matched_controls_are_verified(dataset):
    encoded = [f for f in dataset if f.role == "encoded"]
    clean = [f for f in dataset if f.role == "clean"]
    assert len(encoded) == len(clean) == 6
    for fixture in dataset:
        assert verify_metadata_fixture(fixture)
    for enc in encoded:
        control = next(f for f in clean if f.pair_id == enc.pair_id)
        assert extract_metadata_payload(enc.data) == enc.payload
        assert extract_metadata_payload(control.data) is None
        # Image domain is bit-identical: only metadata differs.
        parsed_enc, parsed_clean = analyze_bytes(enc.data), analyze_bytes(control.data)
        assert parsed_enc.status.value == parsed_clean.status.value == "parsed"
        assert parsed_enc.pixels == parsed_clean.pixels
        assert parsed_enc.coefficients == parsed_clean.coefficients
        assert enc.width == control.width and enc.height == control.height


def test_allowed_task_metadata_exceptions_are_benign_controls(dataset):
    controls = [f for f in dataset if f.negative_kind == "allowed_task_metadata"]
    assert {f.media_kind for f in controls} == {"png", "jpeg"}
    for control in controls:
        keywords = {e["keyword"] for e in metadata_entries(control.data)}
        assert keywords == set(ALLOWED_TASK_METADATA)
        assert PAYLOAD_KEYWORD not in keywords
        assert control.payload == b""
        assert verify_metadata_fixture(control)
        assert analyze_bytes(control.data).status.value == "parsed"


def test_lineage_units_and_splits_match_initial_dataset(dataset):
    for fixture in dataset:
        assert fixture.family == "metadata"
        assert fixture.payload_bits == fixture.payload_bytes * 8
        assert fixture.bits_per_pixel == fixture.payload_bits / (
            fixture.width * fixture.height
        )
        assert fixture.encoder["name"] == "metadata-text-payload"
        assert fixture.generator["name"]
        assert fixture.content_hash.startswith("sha256:")
    bands = {f.payload_band for f in dataset if f.role == "encoded"}
    assert bands == {"low", "medium", "high"}
    assignments = assign_splits(dataset)
    assert validate_no_leakage(dataset, assignments) == []
    # Pair members never straddle the held-out line.
    by_pair = {}
    for fixture in dataset:
        by_pair.setdefault(fixture.pair_id, set()).add(assignments[fixture.fixture_id])
    assert all(len(v) == 1 for v in by_pair.values())


def test_pairs_are_reproducible_and_media_checked():
    first = build_metadata_pair("png", payload_bytes=32, cover_seed=5, payload_seed=6)
    second = build_metadata_pair("png", payload_bytes=32, cover_seed=5, payload_seed=6)
    assert [f.data for f in first] == [f.data for f in second]
    assert [f.fixture_id for f in first] == [f.fixture_id for f in second]
    with pytest.raises(ValueError):
        build_metadata_pair("gif")
