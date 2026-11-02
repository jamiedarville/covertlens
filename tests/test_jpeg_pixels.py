"""CL-52: baseline JPEG pixel decoder and JPEG segmentation path.

Round-trips use the repo's own encoder (`encode_dct_jpeg`, 4:4:4);
the decoder was additionally validated against libjpeg (cjpeg/
djpeg: 4:2:0, 4:2:2, restart intervals, optimized Huffman,
grayscale) during CL-52 development. Independent subsampled, RGB, grayscale,
optimized-table and restart-interval outputs from libjpeg are committed
under tests/data/jpeg/ for offline CI.
"""

from pathlib import Path

import pytest

from covertlens.fixtures import encode_dct_jpeg
from covertlens.geometric import analyze_geometric_bytes
from covertlens.jpeg_pixels import JpegDecodeError, decode_jpeg_rgb, probe_jpeg_size
from covertlens.png_pixels import decode_png_rgb
from covertlens.segmentation import segment_image

_BACKGROUND = (238, 238, 232)
_BAR = (70, 110, 160)
DATA = Path(__file__).parent / "data/jpeg"


def _bars_pixels(width=192, height=96, heights=(26, 46, 36, 56, 46, 66)):
    pixels = bytearray(bytes(_BACKGROUND) * (width * height))
    x = 16
    for bar_height in heights:
        for py in range(height - 16 - bar_height, height - 16):
            for px in range(x, x + 12):
                i = (py * width + px) * 3
                pixels[i : i + 3] = bytes(_BAR)
        x += 24
    return bytes(pixels)


def test_round_trip_smooth_content():
    width, height = 64, 48
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels += bytes(((x * 4) % 256, (y * 5) % 256, ((x + y) * 2) % 256))
    data = encode_dct_jpeg(bytes(pixels), width, height, b"", quality=95)
    assert probe_jpeg_size(data) == (width, height)
    decoded, w, h = decode_jpeg_rgb(data)
    assert (w, h) == (width, height)
    diffs = [abs(a - b) for a, b in zip(decoded, pixels)]
    assert sum(diffs) / len(diffs) < 4.0


def test_rejects_non_jpeg_and_truncated():
    with pytest.raises(JpegDecodeError):
        decode_jpeg_rgb(b"\x89PNG\r\n\x1a\n" + bytes(32))
    assert probe_jpeg_size(b"not an image") is None
    data = encode_dct_jpeg(_bars_pixels(), 192, 96, b"", quality=90)
    with pytest.raises(JpegDecodeError):
        decode_jpeg_rgb(data[: len(data) // 3])


def test_jpeg_segmentation_records_fidelity_limitation():
    data = encode_dct_jpeg(_bars_pixels(), 192, 96, b"", quality=92)
    result = segment_image(data)
    assert result.status == "ok"
    assert result.media_kind == "jpeg"
    assert "lossily" in result.detail
    assert len(result.elements) == 6
    report = analyze_geometric_bytes(data)
    limitations = report["finding"].limitations
    assert any("fidelity limitation" in item for item in limitations)
    assert report["segmentation"]["media_kind"] == "jpeg"


@pytest.mark.parametrize(
    "name", ["444", "422", "420", "restart", "optimized", "grayscale", "rgb"]
)
def test_independent_libjpeg_reference(name):
    data = (DATA / f"{name}.jpg").read_bytes()
    pixels, width, height = decode_jpeg_rgb(data)
    reference, rw, rh = decode_png_rgb((DATA / f"{name}.png").read_bytes())
    assert (width, height) == (rw, rh) == (97, 65)
    diffs = [abs(a - b) for a, b in zip(pixels, reference, strict=True)]
    assert max(diffs) <= 3
    assert sum(diffs) / len(diffs) < 0.5


def test_progressive_is_explicitly_unsupported():
    result = segment_image((DATA / "progressive.jpg").read_bytes())
    assert result.status == "unsupported_media"
    assert result.media_kind == "jpeg"


@pytest.mark.parametrize("marker", [0xC3, 0xC9, 0xCA])
def test_other_frame_encodings_are_explicitly_unsupported(marker):
    data = (DATA / "444.jpg").read_bytes().replace(b"\xff\xc0", bytes((255, marker)), 1)
    result = segment_image(data)
    assert result.status == "unsupported_media"
    assert result.media_kind == "jpeg"


def test_missing_eoi_is_corrupt():
    data = (DATA / "444.jpg").read_bytes()
    assert data.endswith(b"\xff\xd9")
    assert segment_image(data[:-2]).status == "corrupt_input"


def test_unknown_scan_component_is_corrupt_instead_of_raising():
    data = bytearray((DATA / "444.jpg").read_bytes())
    start = data.index(b"\xff\xda")
    data[start + 5] = 99
    assert segment_image(bytes(data)).status == "corrupt_input"


def test_invalid_restart_sequence_is_corrupt():
    data = (DATA / "restart.jpg").read_bytes()
    assert b"\xff\xd0" in data
    data = data.replace(b"\xff\xd0", b"\xff\xd1", 1)
    assert segment_image(data).status == "corrupt_input"


def test_jpeg_pixel_limit_is_checked_before_decode():
    from covertlens.segmentation import SegmenterConfig

    result = segment_image(
        (DATA / "420.jpg").read_bytes(), SegmenterConfig(max_pixels=100)
    )
    assert result.status == "limit_exceeded"
    assert result.media_kind == "jpeg"
