"""CL-52: real PNG row filters, colour types and bounded inflation."""

import struct
import zlib

import pytest

from covertlens.png_pixels import PngDecodeError, decode_png_rgb
from tests.test_parsing import filtered_png


def _chunk(kind, body):
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body))
    )


def _png(raw, *, depth=8, color=2, extra=b""):
    header = struct.pack(">IIBBBBB", 2, 1, depth, color, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + extra
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def test_filtered_rows_decode_to_original_pixels():
    pixels = bytes((x * 13 + y * 17) % 256 for y in range(8) for x in range(12 * 3))
    assert decode_png_rgb(filtered_png(pixels, 12, 8)) == (pixels, 12, 8)


@pytest.mark.parametrize(
    ("color", "depth", "samples", "expected"),
    [
        (0, 8, b"\x14\x78", bytes((20, 20, 20, 120, 120, 120))),
        (4, 8, b"\x14\xff\x78\xff", bytes((20, 20, 20, 120, 120, 120))),
        (6, 8, b"\x14\x28\x3c\xff\x50\x64\x78\xff", bytes((20, 40, 60, 80, 100, 120))),
        (
            2,
            16,
            b"\x14\x00\x28\x00\x3c\x00\x50\x00\x64\x00\x78\x00",
            bytes((20, 40, 60, 80, 100, 120)),
        ),
    ],
)
def test_colour_types(color, depth, samples, expected):
    assert decode_png_rgb(_png(b"\x00" + samples, color=color, depth=depth)) == (
        expected,
        2,
        1,
    )


def test_palette_indices():
    palette = _chunk(b"PLTE", bytes((20, 40, 60, 80, 100, 120)))
    assert decode_png_rgb(_png(b"\x00\x01\x00", color=3, extra=palette))[0] == bytes(
        (80, 100, 120, 20, 40, 60)
    )
    with pytest.raises(PngDecodeError, match="palette index"):
        decode_png_rgb(_png(b"\x00\x02\x00", color=3, extra=palette))


@pytest.mark.parametrize("raw", [b"\x00" + bytes(5), b"\x00" + bytes(1_000_000)])
def test_inflated_size_must_match_dimensions(raw):
    with pytest.raises(PngDecodeError, match="length does not match"):
        decode_png_rgb(_png(raw))


def test_bad_crc_is_corrupt():
    data = bytearray(_png(b"\x00" + bytes(6)))
    data[-1] ^= 1
    with pytest.raises(PngDecodeError, match="CRC"):
        decode_png_rgb(bytes(data))
