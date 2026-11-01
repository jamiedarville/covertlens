"""PNG pixel decoding for geometric segmentation (CL-52).

The fixture helper `_load_png` only reads the filter-none 8-bit
RGB PNGs the fixture generator writes; real PNGs (matplotlib,
screenshots, cameras) use per-row filters and other colour
types. This decoder handles the declared subset: non-interlaced,
bit depth 8 or 16 (16-bit samples keep their high byte), colour
types 0 (grey), 2 (RGB), 3 (palette, via PLTE), 4 (grey+alpha)
and 6 (RGBA). Alpha is ignored: colours are taken as stored,
not composited. Interlaced (Adam7) and packed 1/2/4-bit images
raise `PngDecodeError` — the segmenter maps that to its explicit
`unsupported_media` status. The frozen structural parser in
`covertlens/parsing.py` is not altered.
"""

from __future__ import annotations

import struct
import zlib

from .parsing import _paeth

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngDecodeError(ValueError):
    """PNG bytes are corrupt or outside the supported subset."""


def decode_png_rgb(
    data: bytes, *, max_pixels: int = 2_000_000
) -> tuple[bytes, int, int]:
    """Decode a PNG to (RGB pixels, width, height)."""
    if not data.startswith(_PNG_MAGIC):
        raise PngDecodeError("not PNG bytes")
    pos = 8
    ihdr: tuple[int, int, int, int, int] | None = None
    palette: bytes = b""
    idat = bytearray()
    seen_iend = False
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        end = pos + 8 + length
        if end + 4 > len(data):
            raise PngDecodeError("truncated PNG chunk")
        body = data[pos + 8 : end]
        stored = struct.unpack(">I", data[end : end + 4])[0]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != stored:
            raise PngDecodeError(f"CRC mismatch in {kind.decode('latin1')}")
        if kind == b"IHDR":
            if length != 13:
                raise PngDecodeError("invalid IHDR chunk")
            width, height, depth, color, _c, _f, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if interlace != 0:
                raise PngDecodeError("interlaced PNG outside supported subset")
            if depth not in (8, 16):
                raise PngDecodeError(f"PNG bit depth {depth} outside supported subset")
            if color not in _CHANNELS:
                raise PngDecodeError(f"unknown PNG colour type {color}")
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise PngDecodeError("PNG pixel count over limit")
            ihdr = (width, height, depth, color, interlace)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            seen_iend = True
            break
        pos = end + 4
    if ihdr is None or not idat or not seen_iend:
        raise PngDecodeError("PNG missing IHDR, IDAT or IEND")
    width, height, depth, color, _interlace = ihdr
    channels = _CHANNELS[color]
    sample_bytes = depth // 8
    bpp = channels * sample_bytes
    stride = width * bpp
    expected = height * (1 + stride)
    try:
        engine = zlib.decompressobj()
        raw = engine.decompress(bytes(idat), expected + 1)
        raw += engine.flush()
    except zlib.error as exc:
        raise PngDecodeError(f"PNG inflate failed: {exc}") from exc
    if len(raw) < expected:
        raise PngDecodeError("truncated PNG pixel data")

    rows: list[bytes] = []
    prev = bytearray(stride)
    for y in range(height):
        base = y * (1 + stride)
        ftype = raw[base]
        line = bytearray(raw[base + 1 : base + 1 + stride])
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) // 2)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up_left = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 0xFF
        else:
            raise PngDecodeError(f"unknown PNG filter {ftype}")
        rows.append(bytes(line))
        prev = line

    samples = b"".join(rows)
    pixels = bytearray(width * height * 3)
    step = bpp
    out = 0
    if color == 3:
        if not palette:
            raise PngDecodeError("palette PNG missing PLTE")
        for i in range(0, len(samples), step):
            index = samples[i] * 3
            if index + 3 > len(palette):
                raise PngDecodeError("palette index out of range")
            pixels[out : out + 3] = palette[index : index + 3]
            out += 3
        return bytes(pixels), width, height
    for i in range(0, len(samples), step):
        if channels == 1 or channels == 2:  # grey / grey+alpha
            v = samples[i]
            pixels[out : out + 3] = bytes((v, v, v))
        else:  # RGB / RGBA (alpha ignored, high byte for 16-bit)
            pixels[out] = samples[i]
            pixels[out + 1] = samples[i + sample_bytes]
            pixels[out + 2] = samples[i + 2 * sample_bytes]
        out += 3
    return bytes(pixels), width, height
