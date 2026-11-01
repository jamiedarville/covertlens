import pytest

from covertlens.geometric_fixtures import build_geo_dataset, geo_ground_truth
from covertlens.segmentation import (
    SegmenterConfig,
    segment_image,
    validate_segmentation,
)


@pytest.fixture(scope="module")
def dataset():
    return build_geo_dataset()


def _one(dataset, subfamily, role):
    return next(f for f in dataset if f.subfamily == subfamily and f.role == role)


def test_reading_order_and_height_sequence(dataset):
    fixture = _one(dataset, "height_position", "encoded")
    result = segment_image(fixture.data)
    assert result.status == "ok"
    assert validate_segmentation(result.to_dict()) == []
    lefts = [e["left"] for e in result.elements]
    assert lefts == sorted(lefts), "reading order is left-to-right"
    truth = geo_ground_truth([fixture], role="scorer")[fixture.fixture_id]
    expected = [16 + 10 * s for s in truth["symbols"]]
    assert result.sequence("height") == pytest.approx(expected, abs=1.6)


def test_gap_colour_and_angle_sequences(dataset):
    gap_fx = _one(dataset, "gap_timing", "encoded")
    gaps = segment_image(gap_fx.data).sequence("gap_to_next")[:-1]
    truth = geo_ground_truth([gap_fx], role="scorer")[gap_fx.fixture_id]
    assert gaps == pytest.approx([6 + 6 * s for s in truth["symbols"]], abs=1.6)

    colour_fx = _one(dataset, "colour_code", "encoded")
    result = segment_image(colour_fx.data)
    truth = geo_ground_truth([colour_fx], role="scorer")[colour_fx.fixture_id]
    assert result.sequence("colour_index") == list(truth["symbols"])
    assert all(d < 1.0 for d in result.sequence("colour_distance"))

    angle_fx = _one(dataset, "angle_tilt", "encoded")
    angles = segment_image(angle_fx.data).sequence("angle_deg")
    truth = geo_ground_truth([angle_fx], role="scorer")[angle_fx.fixture_id]
    assert angles == pytest.approx([-30 + 15 * s for s in truth["symbols"]], abs=3.5)


def test_lit_dark_near_background_elements_survive_threshold(dataset):
    # Lit elements are flat grey 235 against background (238,238,232):
    # Euclidean distance ~5.2, far below the strong-foreground
    # tolerance. The component-coherence path must keep them.
    fixture = _one(dataset, "lit_dark", "encoded")
    result = segment_image(fixture.data)
    assert result.status == "ok"
    truth = geo_ground_truth([fixture], role="scorer")[fixture.fixture_id]
    expected = [45.0 if s == 0 else 235.0 for s in truth["symbols"]]
    assert result.sequence("brightness") == pytest.approx(expected, abs=6.0)


def test_failure_modes_are_explicit(dataset):
    clean = _one(dataset, "height_position", "clean")
    # Blank raster: no foreground at all.
    from covertlens.fixtures import _save_png

    blank = _save_png(bytes((238, 238, 232)) * (64 * 32), 64, 32)
    assert segment_image(blank).status == "no_foreground"
    # Garbage after a JPEG signature does not decode: corrupt.
    assert segment_image(b"\xff\xd8\xff\xe0" + bytes(64)).status == "corrupt_input"
    # Progressive JPEG (SOF2) is outside the supported subset.
    sof2_body = bytes([8, 0, 16, 0, 16, 3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1])
    progressive = (
        b"\xff\xd8\xff\xc2" + (len(sof2_body) + 2).to_bytes(2, "big") + sof2_body
    )
    assert segment_image(progressive).status == "unsupported_media"
    # Non-raster bytes are unsupported, not corrupt.
    assert segment_image(b"GIF89a" + bytes(32)).status == "unsupported_media"
    # Corrupt PNG header with a valid signature.
    assert segment_image(b"\x89PNG\r\n\x1a\n" + bytes(32)).status == "corrupt_input"
    # Limits are explicit too.
    tiny = segment_image(clean.data, SegmenterConfig(max_pixels=100))
    assert tiny.status == "limit_exceeded"
    few = segment_image(clean.data, SegmenterConfig(min_elements=99))
    assert few.status == "too_few_elements"
    for result in (segment_image(blank), tiny, few):
        doc = result.to_dict()
        assert validate_segmentation(doc) == []
        assert doc["decoded_message"] is None


def test_method_and_tolerances_recorded(dataset):
    doc = segment_image(_one(dataset, "lit_dark", "encoded").data).to_dict()
    assert doc["segmenter"] == {"name": "geometric-segmenter", "version": "1.1.0"}
    assert doc["tolerances"]["angle_tolerance_deg"] == 3.5
    assert doc["tolerances"]["background_distance_tolerance"] == 24.0
    assert doc["tolerances"]["background_distance_floor"] == 3.0
    assert doc["tolerances"]["coherent_colour_fraction"] == 0.9
    assert doc["tolerances"]["preserve_thin_components"] is True
    assert doc["media_kind"] == "png"
    assert {m["status"] for m in doc["failure_modes"]} >= {
        "no_foreground",
        "too_few_elements",
        "unsupported_media",
    }
    # Lit/dark states separate cleanly on brightness.
    brightness = doc["sequences"]["brightness"]
    assert all(b < 100 or b > 200 for b in brightness)
