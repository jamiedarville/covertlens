"""Baseline JPEG pixel reconstruction for geometric segmentation (CL-52).

The DCT detector works in the coefficient domain by design and
never reconstructs pixels (see `covertlens/dct.py`). Geometry
needs a raster, so this module decodes 8-bit sequential Huffman
JPEGs (SOF0/SOF1) to RGB pixels: per-component quantisation and
Huffman tables, restart intervals, sampling factors 4:4:4 /
4:2:2 / 4:2:0 (nearest-neighbour upsampling), separable IDCT,
YCbCr conversion (Adobe transform flag ignored; 3-component
scans are treated as YCbCr, 1-component as greyscale).

Progressive (SOF2), arithmetic-coded, lossless, and 4-component
(CMYK/YCCK) files raise `JpegDecodeError` — the segmenter maps
that to its explicit `unsupported_media` status. Reconstructed
pixels are lossy evidence: callers must record the JPEG
fidelity limitation wherever attributes measured from them are
reported.
"""

from __future__ import annotations

import math
import struct

from .parsing import _ZIGZAG, _parse_huffman


class JpegDecodeError(ValueError):
    """JPEG bytes are corrupt or outside the supported subset."""


_COS = [
    [math.cos((2 * x + 1) * u * math.pi / 16.0) for x in range(8)] for u in range(8)
]
_C = [1.0 / math.sqrt(2.0)] + [1.0] * 7


def _idct_block(coeffs: list[int]) -> list[int]:
    """Dequantized raster-order coefficients -> 64 pixel samples."""
    if not any(coeffs[1:]):
        level = max(0, min(255, int(round(coeffs[0] / 8.0)) + 128))
        return [level] * 64
    tmp = [0.0] * 64
    for y in range(8):
        base = y * 8
        for x in range(8):
            total = 0.0
            for u in range(8):
                total += _C[u] * coeffs[base + u] * _COS[u][x]
            tmp[base + x] = total
    out = [0] * 64
    for y in range(8):
        for x in range(8):
            total = 0.0
            for v in range(8):
                total += _C[v] * tmp[v * 8 + x] * _COS[v][y]
            out[y * 8 + x] = max(0, min(255, int(round(total / 4.0)) + 128))
    return out


class _ScanBits:
    """Bit reader over one entropy segment (FF00 already unstuffed)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self._buf = 0
        self._count = 0

    def _bit(self) -> int:
        if self._count == 0:
            if self._pos >= len(self._data):
                raise JpegDecodeError("truncated JPEG entropy data")
            self._buf = self._data[self._pos]
            self._pos += 1
            self._count = 8
        self._count -= 1
        return (self._buf >> self._count) & 1

    def read_code(self, table: dict[tuple[int, int], int]) -> int:
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self._bit()
            if (code, length) in table:
                return table[(code, length)]
        raise JpegDecodeError("invalid JPEG Huffman code")

    def read_value(self, size: int) -> int:
        if size == 0:
            return 0
        value = 0
        for _ in range(size):
            value = (value << 1) | self._bit()
        if value < (1 << (size - 1)):
            value -= (1 << size) - 1
        return value


def _split_scan(scan: bytes) -> list[bytes]:
    """Split entropy data at restart markers, unstuffing FF00."""
    segments: list[bytes] = []
    current = bytearray()
    i = 0
    while i < len(scan):
        byte = scan[i]
        if byte == 0xFF and i + 1 < len(scan):
            nxt = scan[i + 1]
            if nxt == 0x00:
                current.append(0xFF)
                i += 2
                continue
            if 0xD0 <= nxt <= 0xD7:
                segments.append(bytes(current))
                current = bytearray()
                i += 2
                continue
            if nxt == 0xD9:  # EOI: image data ends
                break
            if nxt == 0xFF:  # fill byte before a marker
                i += 1
                continue
            break  # any other marker ends the scan for our purposes
        current.append(byte)
        i += 1
    segments.append(bytes(current))
    return segments


def probe_jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the first SOF segment, or None."""
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if length < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2) and pos + 9 <= len(data):
            height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
            return width, height
        pos += 2 + length
    return None


def _parse_quant_tables(body: bytes) -> dict[int, list[int]]:
    tables: dict[int, list[int]] = {}
    i = 0
    while i < len(body):
        kind = body[i]
        precision, table_id = kind >> 4, kind & 0x0F
        if precision == 0:
            raw = body[i + 1 : i + 65]
            if len(raw) != 64:
                raise JpegDecodeError("truncated DQT segment")
            values = list(raw)
            i += 65
        elif precision == 1:
            raw = body[i + 1 : i + 129]
            if len(raw) != 128:
                raise JpegDecodeError("truncated DQT segment")
            values = list(struct.unpack(">64H", raw))
            i += 129
        else:
            raise JpegDecodeError("unsupported DQT precision")
        raster = [0] * 64
        for k, value in enumerate(values):
            raster[_ZIGZAG[k]] = value
        tables[table_id] = raster
    return tables


def decode_jpeg_rgb(
    data: bytes, *, max_pixels: int = 2_000_000
) -> tuple[bytes, int, int]:
    """Decode a baseline Huffman JPEG to (RGB pixels, width, height)."""
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise JpegDecodeError("not JPEG bytes")
    pos = 2
    quant: dict[int, list[int]] = {}
    huff: dict[int, dict[tuple[int, int], int]] = {}
    restart_interval = 0
    frame_w = 0
    frame_h = 0
    frame_comps: list[dict[str, int]] | None = None
    scan_start: int | None = None
    scan_tables: dict[int, tuple[int, int]] = {}
    while pos < len(data):
        if data[pos] != 0xFF:
            raise JpegDecodeError("corrupt JPEG marker stream")
        marker = data[pos + 1] if pos + 1 < len(data) else 0
        if marker == 0xD9:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if pos + 4 > len(data):
            raise JpegDecodeError("truncated JPEG segment")
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if length < 2 or pos + 2 + length > len(data):
            raise JpegDecodeError("truncated JPEG segment body")
        body = data[pos + 4 : pos + 2 + length]
        if marker == 0xDB:
            quant.update(_parse_quant_tables(body))
        elif marker == 0xC4:
            try:
                huff.update(_parse_huffman(body))
            except Exception as exc:
                raise JpegDecodeError(str(exc)) from None
        elif marker == 0xDD:
            if len(body) != 2:
                raise JpegDecodeError("short DRI segment")
            restart_interval = struct.unpack(">H", body)[0]
        elif marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            if marker not in (0xC0, 0xC1):
                raise JpegDecodeError(
                    f"JPEG frame type 0xFF{marker:02X} outside sequential Huffman subset"
                )
            if len(body) < 6 or body[0] != 8:
                raise JpegDecodeError("only 8-bit JPEG frames are supported")
            height, width = struct.unpack(">HH", body[1:5])
            ncomp = body[5]
            if ncomp not in (1, 3) or len(body) < 6 + 3 * ncomp:
                raise JpegDecodeError("only 1- or 3-component JPEGs are supported")
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise JpegDecodeError("JPEG pixel count over limit")
            comps = []
            for i in range(ncomp):
                cid, sampling, qid = body[6 + 3 * i : 9 + 3 * i]
                hsamp, vsamp = sampling >> 4, sampling & 0x0F
                if not (1 <= hsamp <= 4 and 1 <= vsamp <= 4):
                    raise JpegDecodeError("unsupported JPEG sampling factor")
                comps.append({"id": cid, "h": hsamp, "v": vsamp, "q": qid})
            frame_w, frame_h, frame_comps = width, height, comps
        elif marker == 0xDA:
            if frame_comps is None or not quant or not huff:
                raise JpegDecodeError("JPEG scan before frame/tables")
            nscan = body[0] if body else 0
            if nscan != len(frame_comps) or len(body) < 1 + 2 * nscan:
                raise JpegDecodeError("only interleaved scans are supported")
            for i in range(nscan):
                cid, tables_byte = body[1 + 2 * i], body[2 + 2 * i]
                scan_tables[cid] = (tables_byte >> 4, tables_byte & 0x0F)
            scan_start = pos + 2 + length
            break
        pos += 2 + length
    if frame_comps is None or scan_start is None:
        raise JpegDecodeError("JPEG missing frame or scan")

    width, height, comps = frame_w, frame_h, frame_comps
    hmax = max(c["h"] for c in comps)
    vmax = max(c["v"] for c in comps)
    mcus_x = (width + 8 * hmax - 1) // (8 * hmax)
    mcus_y = (height + 8 * vmax - 1) // (8 * vmax)
    planes: list[list[int]] = []
    plane_dims: list[tuple[int, int, int, int]] = []  # samples w/h, blocks w/h
    for comp in comps:
        samples_w = (width * comp["h"] + hmax - 1) // hmax
        samples_h = (height * comp["v"] + vmax - 1) // vmax
        blocks_w = mcus_x * comp["h"]
        blocks_h = mcus_y * comp["v"]
        plane_dims.append((samples_w, samples_h, blocks_w, blocks_h))
        planes.append([128] * (blocks_w * 8 * blocks_h * 8))

    def decode_block(reader: _ScanBits, comp_idx: int, prev: list[int]) -> list[int]:
        comp = comps[comp_idx]
        dc_id, ac_id = scan_tables[comp["id"]]
        try:
            dc_table = huff[dc_id]
            ac_table = huff[0x10 | ac_id]
        except KeyError:
            raise JpegDecodeError("JPEG missing Huffman table") from None
        qtable = quant.get(comp["q"])
        if qtable is None:
            raise JpegDecodeError("JPEG missing quantisation table")
        coeffs = [0] * 64
        size = reader.read_code(dc_table)
        prev[comp_idx] += reader.read_value(size)
        coeffs[0] = prev[comp_idx]
        k = 1
        while k < 64:
            rs = reader.read_code(ac_table)
            run, sz = rs >> 4, rs & 0x0F
            if rs == 0x00:
                break
            if rs == 0xF0:
                k += 16
                continue
            k += run
            if k >= 64:
                raise JpegDecodeError("JPEG AC run overflows block")
            coeffs[_ZIGZAG[k]] = reader.read_value(sz)
            k += 1
        return _idct_block([coeffs[i] * qtable[i] for i in range(64)])

    segments = _split_scan(data[scan_start:])
    total_mcus = mcus_x * mcus_y
    mcu_index = 0
    for seg_index, segment in enumerate(segments):
        if restart_interval and seg_index > 0 and mcu_index % restart_interval != 0:
            raise JpegDecodeError("restart marker out of interval")
        reader = _ScanBits(segment)
        prev = [0] * len(comps)
        segment_mcus = (
            min(restart_interval, total_mcus - mcu_index)
            if restart_interval
            else total_mcus - mcu_index
        )
        for _ in range(segment_mcus):
            mcu_x, mcu_y = mcu_index % mcus_x, mcu_index // mcus_x
            for ci, comp in enumerate(comps):
                _sw, _sh, blocks_w, _blocks_h = plane_dims[ci]
                plane = planes[ci]
                plane_w = blocks_w * 8
                for by in range(comp["v"]):
                    for bx in range(comp["h"]):
                        block = decode_block(reader, ci, prev)
                        ox = (mcu_x * comp["h"] + bx) * 8
                        oy = (mcu_y * comp["v"] + by) * 8
                        for row in range(8):
                            base = (oy + row) * plane_w + ox
                            plane[base : base + 8] = block[row * 8 : row * 8 + 8]
            mcu_index += 1
        if mcu_index >= total_mcus:
            break
    if mcu_index < total_mcus:
        raise JpegDecodeError("truncated JPEG scan")

    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            samples = []
            for ci, (_sw, _sh, blocks_w, _bh) in enumerate(plane_dims):
                samples_w, samples_h = plane_dims[ci][0], plane_dims[ci][1]
                src_x = min(samples_w - 1, (x * samples_w) // width)
                src_y = min(samples_h - 1, (y * samples_h) // height)
                samples.append(planes[ci][src_y * (blocks_w * 8) + src_x])
            offset = (y * width + x) * 3
            if len(samples) == 1:
                pixels[offset : offset + 3] = bytes((samples[0],) * 3)
            else:
                lum, cb, cr = samples
                pixels[offset] = max(0, min(255, int(round(lum + 1.402 * (cr - 128)))))
                pixels[offset + 1] = max(
                    0,
                    min(
                        255,
                        int(round(lum - 0.344136 * (cb - 128) - 0.714136 * (cr - 128))),
                    ),
                )
                pixels[offset + 2] = max(
                    0, min(255, int(round(lum + 1.772 * (cb - 128))))
                )
    return bytes(pixels), width, height
