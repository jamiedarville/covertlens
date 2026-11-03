"""Shared PNG byte helpers (CL-63).

One home for the fixture PNG encoder/decoder that used to live as
private helpers in `covertlens.fixtures` and were imported across
modules by private name. Bytes are unchanged: by default the image
data is stored uncompressed so hashes are reproducible across zlib
builds.
"""

from __future__ import annotations

import binascii
import struct
import zlib


def png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


_STORED_BLOCK_MAX = 0xFFFF


def zlib_stored(data: bytes) -> bytes:
    """Wrap ``data`` in a zlib stream of uncompressed (stored) deflate blocks.

    ``zlib.compress`` output depends on the zlib implementation the
    interpreter links against: classic zlib and zlib-ng emit different
    bytes for the same pixels at the same level. Fixture bytes feed
    content hashes, fixture IDs and the pinned dataset hashes, so they
    must be identical on every machine. Stored blocks are fully defined
    by RFC 1950/1951, and Adler-32 is a fixed checksum, so this stream is
    byte-identical everywhere and still decodes with any inflater.
    """
    out = bytearray(b"\x78\x01")  # deflate, 32K window, no dictionary, level 0
    for start in range(0, max(len(data), 1), _STORED_BLOCK_MAX):
        chunk = data[start : start + _STORED_BLOCK_MAX]
        final = start + _STORED_BLOCK_MAX >= len(data)
        out.append(1 if final else 0)  # BFINAL bit, BTYPE=00 (stored)
        out += struct.pack("<HH", len(chunk), len(chunk) ^ 0xFFFF)
        out += chunk
    out += struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)
    return bytes(out)


def save_png(
    pixels: bytes, width: int, height: int, *, compress: bool = False
) -> bytes:
    """Encode 8-bit RGB pixels as a PNG.

    By default the image data is stored uncompressed so the bytes, and
    every hash derived from them, are reproducible across zlib builds.
    ``compress=True`` uses the platform's zlib for realistic file sizes;
    its bytes vary by zlib implementation, so use it only where file
    bytes are never pinned (latency workloads).
    """
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filter: none
        raw += pixels[y * stride : (y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9) if compress else zlib_stored(bytes(raw))
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND", b"")
    )


def load_png(data: bytes) -> tuple[bytes, int, int]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    pos, idat, width, height = 8, bytearray(), 0, 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            if (depth, color) != (8, 2):
                raise ValueError("fixture PNGs are 8-bit RGB")
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(bytes(idat))
    stride = width * 3
    pixels = bytearray()
    for y in range(height):
        row = raw[y * (stride + 1) : (y + 1) * (stride + 1)]
        if row[0] != 0:
            raise ValueError("unsupported PNG filter (fixtures use none)")
        pixels += row[1:]
    return bytes(pixels), width, height


# Rendering pixels to PNG bytes is `save_png`; the name is kept
# explicit for call sites that render a scene rather than save a file.
render_png = save_png
