"""CL-9 acceptance tests: reproducible LSB and DCT paired fixtures.

AC1 clean and encoded pairs have verified payloads with declared size units
AC2 generator and encoder versions, configurations and seeds are recorded
AC3 benign edits and generator variation are included as negatives
"""

import json

import pytest

from covertlens import ids
from covertlens.fixtures import (
    ENCODER_VERSION,
    GENERATOR_VERSION,
    build_dataset,
    build_pair,
    decode_dct_jpeg,
    decode_lsb_png,
    encode_dct_jpeg,
    encode_lsb_png,
    generate_cover,
    make_payload,
    manifest,
)
from covertlens.store import ArtifactStore

W, H = 64, 48


def test_clean_and_encoded_pairs_have_verified_payloads():
    for family in ("spatial_lsb", "jpeg_dct"):
        clean, encoded = build_pair(family, width=W, height=H, payload_bytes=16)
        assert clean.role == "clean" and encoded.role == "encoded"
        assert clean.pair_id == encoded.pair_id
        assert clean.content_hash != encoded.content_hash
        assert encoded.payload == make_payload(encoded.payload_seed, 16)
        assert ids.content_hash(encoded.data) == encoded.content_hash
        assert encoded.verify_payload() is True


def test_declared_size_units_are_consistent():
    _, encoded = build_pair("spatial_lsb", width=W, height=H, payload_bytes=24)
    assert encoded.payload_bits == 24 * 8
    assert encoded.payload_bytes == 24
    assert encoded.bits_per_pixel == pytest.approx(24 * 8 / (W * H))
    _, encoded_jpeg = build_pair("jpeg_dct", width=W, height=H, payload_bytes=24)
    assert encoded_jpeg.payload_bits == 24 * 8
    assert encoded_jpeg.bits_per_pixel == pytest.approx(24 * 8 / (W * H))


def test_generation_is_byte_for_byte_reproducible():
    first = build_pair("jpeg_dct", width=W, height=H, payload_bytes=8)
    second = build_pair("jpeg_dct", width=W, height=H, payload_bytes=8)
    assert [f.content_hash for f in first] == [f.content_hash for f in second]
    assert first[1].data == second[1].data


def test_lsb_round_trip_and_clean_control():
    cover = generate_cover(W, H, pattern="gradient_noise", seed=7)
    payload = make_payload(99, 12)
    encoded_png = encode_lsb_png(cover, W, H, payload)
    assert decode_lsb_png(encoded_png, len(payload) * 8) == payload
    clean_png = encode_lsb_png(cover, W, H, b"")
    assert decode_lsb_png(clean_png, len(payload) * 8) != payload


def test_dct_round_trip_and_clean_control():
    cover = generate_cover(W, H, pattern="gradient_noise", seed=7)
    payload = make_payload(99, 12)
    encoded_jpeg = encode_dct_jpeg(cover, W, H, payload, quality=90)
    assert encoded_jpeg.startswith(b"\xff\xd8") and encoded_jpeg.endswith(b"\xff\xd9")
    assert decode_dct_jpeg(encoded_jpeg, len(payload) * 8) == payload
    clean_jpeg = encode_dct_jpeg(cover, W, H, b"", quality=90)
    assert decode_dct_jpeg(clean_jpeg, len(payload) * 8) != payload


def test_provenance_records_versions_seeds_and_configs():
    clean, encoded = build_pair("spatial_lsb", width=W, height=H, payload_bytes=8)
    for fixture in (clean, encoded):
        assert fixture.generator["name"] and fixture.generator["version"] == GENERATOR_VERSION
        assert isinstance(fixture.generator["seed"], int)
        assert fixture.encoder["version"] == ENCODER_VERSION
        assert fixture.encoder["config"]
    doc = manifest([clean, encoded])
    json.dumps(doc)  # manifest is JSON-serializable
    encoded_row = [r for r in doc["fixtures"] if r["role"] == "encoded"][0]
    assert encoded_row["payload_sha256"] == ids.content_hash(encoded.payload)
    assert "payload_hex" not in encoded_row  # labels never ride with inputs
    assert doc["generator"]["version"] == GENERATOR_VERSION


def test_benign_edits_and_generator_variation_are_negatives():
    dataset = build_dataset()
    negatives = [f for f in dataset if f.role == "negative"]
    assert negatives, "dataset must ship negatives (AC3)"
    assert all(f.payload_bits == 0 for f in negatives)
    labels = {f.negative_kind for f in negatives}
    assert "benign_edit" in labels and "generator_variation" in labels
    assert all(f.verify_payload() for f in negatives)


def test_dataset_covers_both_families_and_payload_bands():
    dataset = build_dataset()
    encoded = [f for f in dataset if f.role == "encoded"]
    assert {f.family for f in encoded} == {"spatial_lsb", "jpeg_dct"}
    bands = {(f.family, f.payload_band) for f in encoded}
    assert ("spatial_lsb", "low") in bands and ("jpeg_dct", "high") in bands
    for pair_id in {f.pair_id for f in encoded}:
        roles = {f.role for f in dataset if f.pair_id == pair_id}
        assert roles >= {"clean", "encoded"}


def test_fixtures_ingest_into_cl8_store_with_matching_hashes():
    store = ArtifactStore()
    for fixture in build_dataset():
        version = store.put_original(
            fixture.data,
            run_id="run_fixtures",
            producer_id="fixture-factory",
            declared_hash=fixture.content_hash,
        )
        assert version.content_hash == fixture.content_hash
        assert store.get_original(version.artifact_version_id, actor_id="test") == fixture.data
