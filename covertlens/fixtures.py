"""Reproducible LSB and DCT paired fixtures (CL-9, DT-01/DT-02).

A deterministic, dependency-free fixture factory for authorized eval
testing. Seeded procedural covers are saved once as final PNG/JPEG
originals; encoded variants differ from their clean pair only by the
embedded synthetic payload. Payloads are verified by independent decode,
carry declared size units, and are recorded by hash only in the manifest
so detector inputs never carry labels (CL-10 adds leakage-safe splits).

Pure standard library, like the rest of the package: PNG via ``zlib`` and
a minimal baseline JPEG codec (4:4:4, custom Huffman tables carried in
the file) for quantized-DCT embedding. No resize or recompression happens
after a fixture is saved (CL-13 analyses the exact saved bytes).
"""

from __future__ import annotations

import binascii
import json
import math
import struct
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ids

GENERATOR_NAME = "procedural-cover"
GENERATOR_VERSION = "1.0.0"
ENCODER_VERSION = "1.0.0"
FAMILIES = ("spatial_lsb", "jpeg_dct")


class _Lcg:
    """Small deterministic PRNG; stable across Python versions."""

    def __init__(self, seed: int) -> None:
        self._state = (seed & 0x7FFFFFFF) or 1

    def byte(self) -> int:
        self._state = (1103515245 * self._state + 12345) % (1 << 31)
        return (self._state >> 16) & 0xFF

    def signed(self, amplitude: int) -> int:
        return self.byte() % (2 * amplitude + 1) - amplitude


def make_payload(seed: int, n_bytes: int) -> bytes:
    """Deterministic synthetic payload bytes for one fixture."""
    rng = _Lcg(seed * 2654435761 % (1 << 31))
    return bytes(rng.byte() for _ in range(n_bytes))


def _clamp(value: int) -> int:
    return 0 if value < 0 else 255 if value > 255 else value


def generate_cover(
    width: int, height: int, *, pattern: str = "gradient_noise", seed: int = 101
) -> bytes:
    """Return deterministic RGB cover pixels (row-major, 3 bytes/pixel)."""
    rng = _Lcg(seed)
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            if pattern == "blocks":
                base = 200 if (x // 8 + y // 8) % 2 else 55
                r = g = b = base
                noise = rng.signed(18)
            elif pattern == "smooth":
                r = x * 255 // max(width - 1, 1)
                g = y * 255 // max(height - 1, 1)
                b = (x + y) * 255 // max(width + height - 2, 1)
                noise = rng.signed(2)
                pixels[i : i + 3] = bytes(
                    (_clamp(r + noise), _clamp(g + noise), _clamp(b + noise))
                )
                continue
            else:  # gradient_noise (per-channel noise keeps chroma textured)
                r = x * 255 // max(width - 1, 1)
                g = y * 255 // max(height - 1, 1)
                b = (x + y) * 255 // max(width + height - 2, 1)
                pixels[i : i + 3] = bytes(
                    (
                        _clamp(r + rng.signed(36)),
                        _clamp(g + rng.signed(36)),
                        _clamp(b + rng.signed(36)),
                    )
                )
                continue
            pixels[i : i + 3] = bytes(
                (_clamp(r + noise), _clamp(g + noise), _clamp(b + noise))
            )
    return bytes(pixels)


def _benign_edit(pixels: bytes, width: int, height: int, edit: str, seed: int) -> bytes:
    out = bytearray(pixels)
    if edit == "brightness":
        return bytes(_clamp(v + 24) for v in out)
    if edit == "flip_horizontal":
        for y in range(height):
            row = [
                out[(y * width + x) * 3 : (y * width + x) * 3 + 3] for x in range(width)
            ]
            for x, px in enumerate(reversed(row)):
                out[(y * width + x) * 3 : (y * width + x) * 3 + 3] = px
        return bytes(out)
    if edit == "benign_noise":
        rng = _Lcg(seed)
        return bytes(_clamp(v + rng.signed(3)) for v in out)
    raise ValueError(f"unknown benign edit: {edit}")


# ---------------------------------------------------------------- PNG ---


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _save_png(pixels: bytes, width: int, height: int) -> bytes:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filter: none
        raw += pixels[y * stride : (y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _load_png(data: bytes) -> tuple[bytes, int, int]:
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


def _bits(data: bytes) -> Iterable[int]:
    for byte in data:
        for shift in range(7, -1, -1):
            yield (byte >> shift) & 1


def encode_lsb_png(pixels: bytes, width: int, height: int, payload: bytes) -> bytes:
    """Save a PNG whose RGB LSBs carry ``payload`` (raster, MSB-first)."""
    bits = list(_bits(payload))
    if len(bits) > len(pixels):
        raise ValueError("payload exceeds LSB capacity (1 bit per channel byte)")
    out = bytearray(pixels)
    for i, bit in enumerate(bits):
        out[i] = (out[i] & 0xFE) | bit
    return _save_png(bytes(out), width, height)


def decode_lsb_png(data: bytes, n_bits: int) -> bytes:
    """Independently recover the first ``n_bits`` LSB payload bits."""
    pixels, _, _ = _load_png(data)
    out = bytearray()
    current = 0
    for i in range(n_bits):
        current = (current << 1) | (pixels[i] & 1)
        if i % 8 == 7:
            out.append(current)
            current = 0
    return bytes(out)


# --------------------------------------------------------------- JPEG ---

_ZIGZAG = (
    0,
    1,
    8,
    16,
    9,
    2,
    3,
    10,
    17,
    24,
    32,
    25,
    18,
    11,
    4,
    5,
    12,
    19,
    26,
    33,
    40,
    48,
    41,
    34,
    27,
    20,
    13,
    6,
    7,
    14,
    21,
    28,
    35,
    42,
    49,
    56,
    57,
    50,
    43,
    36,
    29,
    22,
    15,
    23,
    30,
    37,
    44,
    51,
    58,
    59,
    52,
    45,
    38,
    31,
    39,
    46,
    53,
    60,
    61,
    54,
    47,
    55,
    62,
    63,
)
_Q_LUMA = (
    16,
    11,
    10,
    16,
    24,
    40,
    51,
    61,
    12,
    12,
    14,
    19,
    26,
    58,
    60,
    55,
    14,
    13,
    16,
    24,
    40,
    57,
    69,
    56,
    14,
    17,
    22,
    29,
    51,
    87,
    80,
    62,
    18,
    22,
    37,
    56,
    68,
    109,
    103,
    77,
    24,
    35,
    55,
    64,
    81,
    104,
    113,
    92,
    49,
    64,
    78,
    87,
    103,
    121,
    120,
    101,
    72,
    92,
    95,
    98,
    112,
    100,
    103,
    99,
)
_Q_CHROMA = (
    17,
    18,
    24,
    47,
    99,
    99,
    99,
    99,
    18,
    21,
    26,
    66,
    99,
    99,
    99,
    99,
    24,
    26,
    56,
    99,
    99,
    99,
    99,
    99,
    47,
    66,
    99,
    99,
    99,
    99,
    99,
    99,
) + (99,) * 32

# Custom canonical Huffman tables (legal JPEG; carried in DHT segments).
_DC_LENGTHS = (4,) * 12
_AC_LENGTHS = (8,) * 128 + (9,) * 128


def _huff_codes(lengths: tuple[int, ...]) -> dict[int, tuple[int, int]]:
    codes: dict[int, tuple[int, int]] = {}
    code = 0
    for symbol, length in enumerate(lengths):
        if symbol and length != lengths[symbol - 1]:
            code <<= length - lengths[symbol - 1]
        codes[symbol] = (code, length)
        code += 1
    return codes


_DC_CODES = _huff_codes(_DC_LENGTHS)
_AC_CODES = _huff_codes(_AC_LENGTHS)


def _scaled_quant(table: tuple[int, ...], quality: int) -> list[int]:
    quality = max(1, min(100, quality))
    scale = 5000 // quality if quality < 50 else 200 - 2 * quality
    return [max(1, min(255, (base * scale + 50) // 100)) for base in table]


def _to_ycbcr(pixels: bytes) -> tuple[bytes, bytes, bytes]:
    y_plane, cb_plane, cr_plane = bytearray(), bytearray(), bytearray()
    for i in range(0, len(pixels), 3):
        r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
        y_plane.append(_clamp(round(0.299 * r + 0.587 * g + 0.114 * b)))
        cb_plane.append(_clamp(round(-0.16873589 * r - 0.33126411 * g + 0.5 * b + 128)))
        cr_plane.append(_clamp(round(0.5 * r - 0.41868759 * g - 0.08131241 * b + 128)))
    return bytes(y_plane), bytes(cb_plane), bytes(cr_plane)


def _blocks(plane: bytes, width: int, height: int) -> list[list[int]]:
    blocks: list[list[int]] = []
    for by in range(0, height, 8):
        for bx in range(0, width, 8):
            block = []
            for dy in range(8):
                for dx in range(8):
                    x, y = min(bx + dx, width - 1), min(by + dy, height - 1)
                    block.append(plane[y * width + x] - 128)
            blocks.append(block)
    return blocks


_COS = [[math.cos((2 * x + 1) * u * math.pi / 16) for x in range(8)] for u in range(8)]


def _fdct_quant(block: list[int], quant: list[int]) -> list[int]:
    out = [0] * 64
    for v in range(8):
        for u in range(8):
            total = 0.0
            for y in range(8):
                for x in range(8):
                    total += block[y * 8 + x] * _COS[u][x] * _COS[v][y]
            factor = (
                0.25
                * (1 / math.sqrt(2) if u == 0 else 1)
                * (1 / math.sqrt(2) if v == 0 else 1)
            )
            out[v * 8 + u] = round(factor * total / quant[v * 8 + u])
    return out


class _BitWriter:
    def __init__(self) -> None:
        self._bytes = bytearray()
        self._acc = 0
        self._count = 0

    def write(self, code: int, length: int) -> None:
        self._acc = (self._acc << length) | code
        self._count += length
        while self._count >= 8:
            byte = (self._acc >> (self._count - 8)) & 0xFF
            self._bytes.append(byte)
            if byte == 0xFF:
                self._bytes.append(0)
            self._count -= 8
        self._acc &= (1 << self._count) - 1

    def finish(self) -> bytes:
        if self._count:
            pad = 8 - self._count
            byte = ((self._acc << pad) | ((1 << pad) - 1)) & 0xFF
            self._bytes.append(byte)
            if byte == 0xFF:
                self._bytes.append(0)
        return bytes(self._bytes)


def _category(value: int) -> int:
    return abs(value).bit_length()


def _encode_block(writer: _BitWriter, coeffs: list[int], prev_dc: int) -> int:
    zig = [coeffs[i] for i in _ZIGZAG]
    diff = zig[0] - prev_dc
    size = _category(diff)
    code, length = _DC_CODES[size]
    writer.write(code, length)
    if size:
        writer.write(diff if diff >= 0 else diff + (1 << size) - 1, size)
    run = 0
    for value in zig[1:]:
        if value == 0:
            run += 1
            continue
        while run > 15:
            code, length = _AC_CODES[0xF0]
            writer.write(code, length)
            run -= 16
        size = _category(value)
        code, length = _AC_CODES[(run << 4) | size]
        writer.write(code, length)
        writer.write(value if value >= 0 else value + (1 << size) - 1, size)
        run = 0
    if run:
        code, length = _AC_CODES[0x00]
        writer.write(code, length)
    return zig[0]


def _segment(marker: int, body: bytes) -> bytes:
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(body) + 2) + body


def _dht(class_id: int, lengths: tuple[int, ...]) -> bytes:
    counts = [0] * 16
    for length in lengths:
        counts[length - 1] += 1
    return bytes([class_id]) + bytes(counts) + bytes(range(len(lengths)))


def _embed_dct(coeff_planes: list[list[list[int]]], payload: bytes) -> None:
    bits = list(_bits(payload))
    pos = 0
    ordered = [
        coeff_planes[comp][bi]
        for bi in range(len(coeff_planes[0]))
        for comp in range(3)
    ]
    for block in ordered:
        for zi in range(1, 64):
            if pos >= len(bits):
                return
            idx = _ZIGZAG[zi]
            coeff = block[idx]
            if abs(coeff) >= 2:  # carrier set is invariant under LSB setting
                magnitude = (abs(coeff) & ~1) | bits[pos]
                block[idx] = magnitude if coeff > 0 else -magnitude
                pos += 1
    if pos < len(bits):
        raise ValueError("payload exceeds DCT carrier capacity (|AC| >= 2)")


def encode_dct_jpeg(
    pixels: bytes, width: int, height: int, payload: bytes, *, quality: int = 90
) -> bytes:
    """Encode a baseline JPEG (4:4:4), embedding payload in Y AC coefficient LSBs."""
    q_luma, q_chroma = (
        _scaled_quant(_Q_LUMA, quality),
        _scaled_quant(_Q_CHROMA, quality),
    )
    planes = _to_ycbcr(pixels)
    coeff_planes: list[list[list[int]]] = []
    for plane, quant in zip(planes, (q_luma, q_chroma, q_chroma)):
        coeff_planes.append(
            [_fdct_quant(b, quant) for b in _blocks(plane, width, height)]
        )
    if payload:
        _embed_dct(coeff_planes, payload)
    writer = _BitWriter()
    prev = [0, 0, 0]
    n_blocks = len(coeff_planes[0])
    for bi in range(n_blocks):
        for comp in range(3):
            prev[comp] = _encode_block(writer, coeff_planes[comp][bi], prev[comp])
    entropy = writer.finish()
    out = bytearray(b"\xff\xd8")
    out += _segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    out += _segment(0xDB, bytes([0]) + bytes(q_luma))
    out += _segment(0xDB, bytes([1]) + bytes(q_chroma))
    sof_body = (
        b"\x08"
        + struct.pack(">HHB", height, width, 3)
        + bytes([1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1])
    )
    out += _segment(0xC0, sof_body)
    out += _segment(0xC4, _dht(0x00, _DC_LENGTHS))
    out += _segment(0xC4, _dht(0x10, _AC_LENGTHS))
    out += _segment(0xDA, bytes([3, 1, 0, 2, 0, 3, 0, 0, 63, 0]))
    out += entropy
    out += b"\xff\xd9"
    return bytes(out)


def _extract_coefficients(data: bytes) -> tuple[list[list[int]], int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")
    pos, width, height = 2, 0, 0
    tables: dict[int, dict[tuple[int, int], int]] = {}
    entropy = b""
    while pos < len(data):
        if data[pos] != 0xFF:
            raise ValueError("corrupt JPEG marker stream")
        marker = data[pos + 1]
        if marker == 0xDA:
            length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
            entropy = data[pos + 2 + length :]
            break
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        body = data[pos + 4 : pos + 2 + length]
        if marker == 0xC4:
            i = 0
            while i < len(body):
                class_id = body[i]
                counts = body[i + 1 : i + 17]
                symbols = body[i + 17 : i + 17 + sum(counts)]
                decode: dict[tuple[int, int], int] = {}
                code = 0
                k = 0
                for ln in range(1, 17):
                    for _ in range(counts[ln - 1]):
                        decode[(code, ln)] = symbols[k]
                        k += 1
                        code += 1
                    code <<= 1
                tables[class_id] = decode
                i += 17 + sum(counts)
        elif marker == 0xC0:
            height, width = struct.unpack(">HH", body[1:5])
        pos += 2 + length
    if entropy.endswith(b"\xff\xd9"):
        entropy = entropy[:-2]
    bits: list[int] = []
    raw = entropy.replace(b"\xff\x00", b"\xff")
    for byte in raw:
        bits.extend((byte >> s) & 1 for s in range(7, -1, -1))
    state = {"i": 0}

    def read_code(table: dict[tuple[int, int], int]) -> int:
        code = 0
        for ln in range(1, 17):
            code = (code << 1) | bits[state["i"]]
            state["i"] += 1
            if (code, ln) in table:
                return table[(code, ln)]
        raise ValueError("invalid Huffman code")

    def read_value(size: int) -> int:
        if size == 0:
            return 0
        value = 0
        for _ in range(size):
            value = (value << 1) | bits[state["i"]]
            state["i"] += 1
        if value < (1 << (size - 1)):
            value -= (1 << size) - 1
        return value

    dc_table, ac_table = tables[0x00], tables[0x10]
    blocks_x, blocks_y = (width + 7) // 8, (height + 7) // 8
    blocks: list[list[int]] = []
    prev = [0, 0, 0]
    for _ in range(blocks_x * blocks_y):
        for comp in range(3):
            coeffs = [0] * 64
            size = read_code(dc_table)
            prev[comp] += read_value(size)
            coeffs[0] = prev[comp]
            k = 1
            while k < 64:
                rs = read_code(ac_table)
                run, sz = rs >> 4, rs & 0x0F
                if rs == 0x00:
                    break
                if rs == 0xF0:
                    k += 16
                    continue
                k += run
                coeffs[_ZIGZAG[k]] = read_value(sz)
                k += 1
            blocks.append(coeffs)
    return blocks, width, height


def decode_dct_jpeg(data: bytes, n_bits: int) -> bytes:
    """Independently recover payload bits from AC coefficient LSBs."""
    blocks, _, _ = _extract_coefficients(data)
    out = bytearray()
    current = 0
    seen = 0
    for block in blocks:
        for zi in range(1, 64):
            if seen >= n_bits:
                return bytes(out)
            coeff = block[_ZIGZAG[zi]]
            if abs(coeff) >= 2:
                current = (current << 1) | (abs(coeff) & 1)
                seen += 1
                if seen % 8 == 0:
                    out.append(current)
                    current = 0
    return bytes(out)


# -------------------------------------------------------------- factory ---


def _payload_band(bits_per_pixel: float) -> str:
    if bits_per_pixel == 0:
        return "none"
    if bits_per_pixel <= 0.05:
        return "low"
    if bits_per_pixel <= 0.25:
        return "medium"
    return "high"


@dataclass(frozen=True)
class Fixture:
    """One saved fixture image plus its provenance and ground truth."""

    fixture_id: str
    pair_id: str
    family: str
    role: str  # clean | encoded | negative
    media_kind: str  # png | jpeg
    width: int
    height: int
    data: bytes = field(repr=False)
    payload: bytes = field(repr=False, default=b"")
    payload_seed: int = 0
    negative_kind: str | None = None
    generator: dict[str, Any] = field(default_factory=dict)
    encoder: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return ids.content_hash(self.data)

    @property
    def payload_bits(self) -> int:
        return len(self.payload) * 8

    @property
    def payload_bytes(self) -> int:
        return len(self.payload)

    @property
    def bits_per_pixel(self) -> float:
        return self.payload_bits / (self.width * self.height)

    @property
    def payload_band(self) -> str:
        return _payload_band(self.bits_per_pixel)

    def verify_payload(self) -> bool:
        """Independent decode of the saved bytes must match ground truth."""
        if self.family == "spatial_lsb":
            return decode_lsb_png(self.data, self.payload_bits) == self.payload
        return decode_dct_jpeg(self.data, self.payload_bits) == self.payload


def _fixture(
    family: str,
    role: str,
    pair_id: str,
    width: int,
    height: int,
    data: bytes,
    payload: bytes,
    payload_seed: int,
    generator: dict[str, Any],
    encoder: dict[str, Any],
    negative_kind: str | None = None,
) -> Fixture:
    digest = ids.content_hash(data)
    return Fixture(
        fixture_id=f"{family}-{role}-{digest.split(':', 1)[1][:12]}",
        pair_id=pair_id,
        family=family,
        role=role,
        media_kind="png" if family == "spatial_lsb" else "jpeg",
        width=width,
        height=height,
        data=data,
        payload=payload,
        payload_seed=payload_seed,
        negative_kind=negative_kind,
        generator=generator,
        encoder=encoder,
    )


def build_pair(
    family: str,
    *,
    width: int = 64,
    height: int = 48,
    payload_bytes: int = 16,
    cover_seed: int = 101,
    payload_seed: int = 202,
    pattern: str = "gradient_noise",
    quality: int = 90,
) -> tuple[Fixture, Fixture]:
    """Build one clean/encoded pair differing only by the embedded payload."""
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {FAMILIES}")
    cover = generate_cover(width, height, pattern=pattern, seed=cover_seed)
    payload = make_payload(payload_seed, payload_bytes)
    generator = {
        "name": GENERATOR_NAME,
        "version": GENERATOR_VERSION,
        "seed": cover_seed,
        "pattern": pattern,
        "width": width,
        "height": height,
    }
    pair_id = f"pair-{family}-{cover_seed}-{pattern}"
    if family == "spatial_lsb":
        clean_data = _save_png(cover, width, height)
        encoded_data = encode_lsb_png(cover, width, height, payload)
        encoder = {
            "name": "lsb-png",
            "version": ENCODER_VERSION,
            "seed": payload_seed,
            "config": {
                "lsb_depth": 1,
                "order": "raster_rgb_msb_first",
                "channels": "RGB",
            },
        }
    else:
        clean_data = encode_dct_jpeg(cover, width, height, b"", quality=quality)
        encoded_data = encode_dct_jpeg(cover, width, height, payload, quality=quality)
        encoder = {
            "name": "dct-jpeg",
            "version": ENCODER_VERSION,
            "seed": payload_seed,
            "config": {
                "quality": quality,
                "component": "Y+Cb+Cr",
                "coefficient_rule": "ac_magnitude>=2_lsb",
                "quantization": "jpeg_standard_scaled",
                "subsampling": "4:4:4",
            },
        }
    clean = _fixture(
        family,
        "clean",
        pair_id,
        width,
        height,
        clean_data,
        b"",
        payload_seed,
        generator,
        encoder,
    )
    encoded = _fixture(
        family,
        "encoded",
        pair_id,
        width,
        height,
        encoded_data,
        payload,
        payload_seed,
        generator,
        encoder,
    )
    if not encoded.verify_payload():
        raise ValueError("encoded fixture failed payload verification")
    return clean, encoded


def _negative(
    family: str,
    pixels: bytes,
    width: int,
    height: int,
    *,
    seed: int,
    pattern: str,
    kind: str,
    label: str,
    quality: int = 90,
) -> Fixture:
    generator = {
        "name": GENERATOR_NAME,
        "version": GENERATOR_VERSION,
        "seed": seed,
        "pattern": pattern,
        "width": width,
        "height": height,
    }
    if family == "spatial_lsb":
        data = _save_png(pixels, width, height)
        encoder = {
            "name": "lsb-png",
            "version": ENCODER_VERSION,
            "seed": 0,
            "config": {
                "lsb_depth": 1,
                "order": "raster_rgb_msb_first",
                "channels": "RGB",
            },
        }
    else:
        data = encode_dct_jpeg(pixels, width, height, b"", quality=quality)
        encoder = {
            "name": "dct-jpeg",
            "version": ENCODER_VERSION,
            "seed": 0,
            "config": {
                "quality": quality,
                "component": "Y+Cb+Cr",
                "coefficient_rule": "ac_magnitude>=2_lsb",
                "quantization": "jpeg_standard_scaled",
                "subsampling": "4:4:4",
            },
        }
    return _fixture(
        family,
        "negative",
        f"neg-{label}-{seed}",
        width,
        height,
        data,
        b"",
        0,
        generator,
        encoder,
        negative_kind=kind,
    )


def build_dataset(width: int = 64, height: int = 48) -> list[Fixture]:
    """The default CL-9 suite: paired bands for both families plus negatives."""
    fixtures: list[Fixture] = []
    for family in FAMILIES:
        for i, n_bytes in enumerate((12, 64, 192)):
            fixtures.extend(
                build_pair(
                    family,
                    width=width,
                    height=height,
                    payload_bytes=n_bytes,
                    cover_seed=101 + i * 17,
                    payload_seed=202 + i * 31,
                )
            )
    base = generate_cover(width, height, seed=101)
    fixtures.append(
        _negative(
            "spatial_lsb",
            _benign_edit(base, width, height, "brightness", 1),
            width,
            height,
            seed=101,
            pattern="gradient_noise",
            kind="benign_edit",
            label="brightness",
        )
    )
    fixtures.append(
        _negative(
            "jpeg_dct",
            _benign_edit(base, width, height, "flip_horizontal", 1),
            width,
            height,
            seed=101,
            pattern="gradient_noise",
            kind="benign_edit",
            label="flip",
        )
    )
    fixtures.append(
        _negative(
            "spatial_lsb",
            generate_cover(width, height, pattern="blocks", seed=999),
            width,
            height,
            seed=999,
            pattern="blocks",
            kind="generator_variation",
            label="blocks",
        )
    )
    fixtures.append(
        _negative(
            "jpeg_dct",
            generate_cover(width, height, pattern="smooth", seed=555),
            width,
            height,
            seed=555,
            pattern="smooth",
            kind="generator_variation",
            label="smooth",
        )
    )
    return fixtures


def manifest(fixtures: Iterable[Fixture]) -> dict[str, Any]:
    """JSON-ready fixture manifest; raw payloads are never included."""
    rows = []
    for f in fixtures:
        rows.append(
            {
                "fixture_id": f.fixture_id,
                "pair_id": f.pair_id,
                "family": f.family,
                "role": f.role,
                "negative_kind": f.negative_kind,
                "media_kind": f.media_kind,
                "content_hash": f.content_hash,
                "size_bytes": len(f.data),
                "width": f.width,
                "height": f.height,
                "payload_bits": f.payload_bits,
                "payload_bytes": f.payload_bytes,
                "bits_per_pixel": round(f.bits_per_pixel, 6),
                "payload_band": f.payload_band,
                "payload_sha256": ids.content_hash(f.payload),
                "generator": f.generator,
                "encoder": f.encoder,
            }
        )
    return {
        "schema": "covertlens.fixture-manifest",
        "version": 1,
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "encoder_version": ENCODER_VERSION,
        "fixtures": rows,
    }


def ground_truth(fixtures: Iterable[Fixture]) -> dict[str, Any]:
    """Scorer-side payloads, kept separate from detector-facing manifests."""
    return {
        f.fixture_id: {
            "payload_hex": f.payload.hex(),
            "payload_bits": f.payload_bits,
            "payload_seed": f.payload_seed,
        }
        for f in fixtures
        if f.role == "encoded"
    }


def write_dataset(
    out_dir: str | Path, fixtures: Iterable[Fixture] | None = None
) -> Path:
    """Write fixture files plus ``manifest.json`` (and scorer ground truth)."""
    rows = list(fixtures) if fixtures is not None else build_dataset()
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for f in rows:
        ext = "png" if f.media_kind == "png" else "jpg"
        (target / f"{f.fixture_id}.{ext}").write_bytes(f.data)
    (target / "manifest.json").write_text(
        json.dumps(manifest(rows), indent=2, sort_keys=True), encoding="utf-8"
    )
    (target / "ground-truth.json").write_text(
        json.dumps(ground_truth(rows), indent=2, sort_keys=True), encoding="utf-8"
    )
    return target
