"""Bounded PNG/JPEG parsing and analysis result schema (CL-13, DET-01/02).

Original bytes are parsed natively — never resized, recompressed or
replaced by a preview derivative — under versioned worker limits that
are checked before unbounded work. Every input yields one versioned
result with a stable status: ``parsed``, ``corrupt``,
``unsupported_format``, ``unsupported_encoding``, ``oversized`` or
``timeout``. Failures are infrastructure outcomes recorded in the
result, never clean verdicts or collusion findings (C-02, manifest
error behaviour). Parsed results carry the original content hash, so
hash drift is detectable, and a validated channel-finding schema
(DET-02) that CL-14/CL-15/CL-23 detectors populate.

Declared parser subset (anything outside it returns
``unsupported_encoding`` with the limitation recorded instead of a
guessed parse): 8-bit non-interlaced PNG (all colour types) and 8-bit
baseline sequential DCT JPEG with 4:4:4 sampling (3 components).
Thresholds stay unfrozen (CL-27); this module fixes no detector scores.
"""

from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import ids
from .manifest import FAMILIES
from .store import ArtifactStore

RESULT_SCHEMA = "covertlens.analysis-result"
RESULT_SCHEMA_VERSION = 1
PARSER_NAME = "covertlens.bounded-parser"
PARSER_VERSION = "1.0.0"
LIMITS_VERSION = "1.0.0"
FINDING_SCHEMA_VERSION = "1.0.0"

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class AnalysisStatus(str, Enum):
    PARSED = "parsed"
    CORRUPT = "corrupt"
    UNSUPPORTED_FORMAT = "unsupported_format"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    OVERSIZED = "oversized"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ParserLimits:
    """Versioned worker bounds; every bound is checked before heavy work."""

    max_input_bytes: int = 10 * 1024 * 1024  # 10 MiB
    max_pixels: int = 20_000_000  # 20 MP
    max_width: int = 8192
    max_height: int = 8192
    max_decompressed_bytes: int = 128 * 1024 * 1024
    max_runtime_s: float = 2.0  # 0 means: always already timed out (tests)
    version: str = LIMITS_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_input_bytes", "max_pixels", "max_width", "max_height",
            "max_decompressed_bytes",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.max_runtime_s < 0:
            raise ValueError("max_runtime_s must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "max_input_bytes": self.max_input_bytes,
            "max_pixels": self.max_pixels,
            "max_width": self.max_width,
            "max_height": self.max_height,
            "max_decompressed_bytes": self.max_decompressed_bytes,
            "max_runtime_s": self.max_runtime_s,
        }


DEFAULT_LIMITS = ParserLimits()


@dataclass(frozen=True)
class Finding:
    """One detector channel finding (DET-02); populated by CL-14/15/23."""

    family: str
    detector_name: str
    detector_version: str
    score: float
    coverage: dict[str, Any]
    evidence: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    schema_version: str = FINDING_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "detector_name": self.detector_name,
            "detector_version": self.detector_version,
            "score": self.score,
            "coverage": dict(self.coverage),
            "evidence": dict(self.evidence),
            "limitations": list(self.limitations),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class AnalysisResult:
    """One bounded-parse outcome; JSON shape is the analysis-result schema.

    ``pixels`` (PNG sample bytes, row-major) and ``coefficients`` (JPEG
    quantized coefficient blocks in raster MCU order) are transient
    detector inputs and are never serialised into the result JSON.
    """

    content_hash: str
    status: AnalysisStatus
    input_bytes: int
    media_kind: str | None = None
    artifact_id: str | None = None
    artifact_version_id: str | None = None
    image: dict[str, Any] | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    errors: tuple[dict[str, str], ...] = ()
    limitations: tuple[str, ...] = ()
    elapsed_s: float = 0.0
    limits: ParserLimits = DEFAULT_LIMITS
    pixels: bytes | None = field(default=None, repr=False)
    coefficients: tuple[tuple[int, ...], ...] | None = field(default=None, repr=False)

    @property
    def transform_applied(self) -> bool:
        """Analysis always consumes the exact original bytes (DET-01)."""
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "schema_version": RESULT_SCHEMA_VERSION,
            "artifact_id": self.artifact_id,
            "artifact_version_id": self.artifact_version_id,
            "content_hash": self.content_hash,
            "media_kind": self.media_kind,
            "status": self.status.value,
            "transform_applied": False,
            "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
            "limits": self.limits.to_dict(),
            "image": self.image,
            "input_bytes": self.input_bytes,
            "coverage": dict(self.coverage),
            "findings": [f.to_dict() for f in self.findings],
            "errors": [dict(e) for e in self.errors],
            "limitations": list(self.limitations),
            "elapsed_ms": round(self.elapsed_s * 1000, 3),
        }


def validate_finding(finding: Finding | dict[str, Any]) -> list[str]:
    """Return validation errors for one channel finding; empty is valid."""
    data = finding.to_dict() if isinstance(finding, Finding) else dict(finding)
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(data.get("family") in FAMILIES, f"family must be one of {FAMILIES}")
    need(isinstance(data.get("detector_name"), str) and bool(data.get("detector_name")),
         "detector_name is required")
    need(isinstance(data.get("detector_version"), str)
         and bool(data.get("detector_version")), "detector_version is required")
    score = data.get("score")
    need(isinstance(score, (int, float)) and not isinstance(score, bool)
         and 0.0 <= float(score) <= 1.0, "score must be a number in [0, 1]")
    need(isinstance(data.get("coverage"), dict), "coverage must be an object")
    need(isinstance(data.get("evidence", {}), dict), "evidence must be an object")
    need(isinstance(data.get("limitations", []), list)
         and all(isinstance(x, str) for x in data.get("limitations", [])),
         "limitations must be a list of strings")
    need(data.get("schema_version") == FINDING_SCHEMA_VERSION,
         f"finding schema_version must be {FINDING_SCHEMA_VERSION}")
    return errors


def validate_result(result: AnalysisResult | dict[str, Any]) -> list[str]:
    """Return validation errors for one analysis result; empty is valid."""
    data = result.to_dict() if isinstance(result, AnalysisResult) else dict(result)
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(data.get("schema") == RESULT_SCHEMA, f"schema must be {RESULT_SCHEMA}")
    need(data.get("schema_version") == RESULT_SCHEMA_VERSION,
         f"schema_version must be {RESULT_SCHEMA_VERSION}")
    need(ids.is_content_hash(data.get("content_hash")),
         "content_hash must be sha256:<hex> of the original bytes")
    status = data.get("status")
    need(status in {s.value for s in AnalysisStatus},
         f"status must be one of {[s.value for s in AnalysisStatus]}")
    need(data.get("transform_applied") is False,
         "transform_applied must be false (original bytes only, DET-01)")
    parser = data.get("parser") or {}
    need(parser.get("name") == PARSER_NAME and parser.get("version") == PARSER_VERSION,
         "parser name/version must be the bounded parser's")
    limits = data.get("limits") or {}
    need(limits.get("version") == LIMITS_VERSION, "limits version is required")
    findings = data.get("findings", [])
    for i, finding in enumerate(findings):
        for err in validate_finding(finding):
            errors.append(f"findings[{i}]: {err}")
    if status != AnalysisStatus.PARSED.value:
        need(findings == [], "failed parses carry no findings (C-02)")
        need(bool(data.get("errors")), "failed parses must carry explicit errors")
    if status == AnalysisStatus.PARSED.value:
        need(data.get("media_kind") in ("png", "jpeg"),
             "parsed results must name png or jpeg media")
        coverage = data.get("coverage") or {}
        need(any(v for v in coverage.values() if isinstance(v, int) and v > 0),
             "parsed results must report positive coverage")
    return errors


class _Fail(Exception):
    """Internal control flow carrying one explicit failure result."""

    def __init__(self, status: AnalysisStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _result(
    data: bytes,
    status: AnalysisStatus,
    limits: ParserLimits,
    start: float,
    *,
    detail: str | None = None,
    media_kind: str | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
    image: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    pixels: bytes | None = None,
    coefficients: tuple[tuple[int, ...], ...] | None = None,
    limitations: tuple[str, ...] = (),
) -> AnalysisResult:
    errors: tuple[dict[str, str], ...] = ()
    if status is not AnalysisStatus.PARSED:
        errors = ({"code": status.value, "detail": detail or status.value},)
    return AnalysisResult(
        content_hash=ids.content_hash(data),
        status=status,
        input_bytes=len(data),
        media_kind=media_kind,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
        image=image,
        coverage=coverage or {},
        errors=errors,
        limitations=limitations,
        elapsed_s=max(0.0, time.monotonic() - start),
        limits=limits,
        pixels=pixels,
        coefficients=coefficients,
    )


def _check_deadline(start: float, limits: ParserLimits) -> None:
    if time.monotonic() - start > limits.max_runtime_s:
        raise _Fail(AnalysisStatus.TIMEOUT,
                    f"runtime deadline {limits.max_runtime_s}s exceeded")


def _check_dimensions(width: int, height: int, limits: ParserLimits) -> None:
    if width < 1 or height < 1:
        raise _Fail(AnalysisStatus.CORRUPT, "image dimensions must be positive")
    if width > limits.max_width or height > limits.max_height:
        raise _Fail(AnalysisStatus.OVERSIZED,
                    f"dimensions {width}x{height} exceed "
                    f"{limits.max_width}x{limits.max_height}")
    if width * height > limits.max_pixels:
        raise _Fail(AnalysisStatus.OVERSIZED,
                    f"pixel count {width * height} exceeds {limits.max_pixels}")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)


def _crc(kind: bytes, body: bytes) -> int:
    return zlib.crc32(kind + body) & 0xFFFFFFFF


def _parse_png(
    data: bytes, limits: ParserLimits, start: float
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Parse an 8-bit non-interlaced PNG; return image, coverage, samples."""
    _check_deadline(start, limits)
    if len(data) < 8 or not data.startswith(_PNG_MAGIC):
        raise _Fail(AnalysisStatus.UNSUPPORTED_FORMAT, "not PNG bytes")
    pos = 8
    ihdr: dict[str, Any] | None = None
    idat = bytearray()
    seen_iend = False
    while pos < len(data):
        if pos + 8 > len(data):
            raise _Fail(AnalysisStatus.CORRUPT, "truncated PNG chunk header")
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        end = pos + 8 + length + 4
        if end > len(data):
            raise _Fail(AnalysisStatus.CORRUPT, f"truncated PNG chunk {kind!r}")
        body = data[pos + 8 : pos + 8 + length]
        stored = struct.unpack(">I", data[pos + 8 + length : end])[0]
        if _crc(kind, body) != stored:
            raise _Fail(AnalysisStatus.CORRUPT, f"CRC mismatch in {kind.decode('latin1')}")
        if ihdr is None and kind != b"IHDR":
            raise _Fail(AnalysisStatus.CORRUPT, "first PNG chunk must be IHDR")
        if kind == b"IHDR":
            if ihdr is not None or length != 13:
                raise _Fail(AnalysisStatus.CORRUPT, "invalid IHDR chunk")
            width, height, depth, color, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", body)
            ihdr = {"width": width, "height": height, "bit_depth": depth,
                    "color_type": color, "interlace": interlace}
            if depth != 8:
                raise _Fail(AnalysisStatus.UNSUPPORTED_ENCODING,
                            f"PNG bit depth {depth} outside declared 8-bit subset")
            if color not in _PNG_CHANNELS:
                raise _Fail(AnalysisStatus.CORRUPT,
                            f"unknown PNG colour type {color}")
            if interlace != 0:
                raise _Fail(AnalysisStatus.UNSUPPORTED_ENCODING,
                            "interlaced PNG outside declared subset")
            _check_dimensions(width, height, limits)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            seen_iend = True
            break
        elif kind == b"PLTE":
            pass  # palette bytes; indices are still parsed row-wise
        elif kind[:1].isupper():
            raise _Fail(AnalysisStatus.UNSUPPORTED_ENCODING,
                        f"unknown critical PNG chunk {kind.decode('latin1')}")
        pos = end
    if ihdr is None or not idat or not seen_iend:
        raise _Fail(AnalysisStatus.CORRUPT, "PNG missing IHDR, IDAT or IEND")
    width, height = int(ihdr["width"]), int(ihdr["height"])
    channels = _PNG_CHANNELS[int(ihdr["color_type"])]
    if int(ihdr["color_type"]) == 3:
        # Palette images need PLTE; absence is structural corruption.
        if b"PLTE" not in data:
            raise _Fail(AnalysisStatus.CORRUPT, "palette PNG missing PLTE")
    stride = width * channels
    expected = height * (1 + stride)
    if expected > limits.max_decompressed_bytes:
        raise _Fail(AnalysisStatus.OVERSIZED,
                    f"decompressed size {expected} exceeds "
                    f"{limits.max_decompressed_bytes}")
    _check_deadline(start, limits)
    try:
        engine = zlib.decompressobj()
        raw = engine.decompress(bytes(idat), limits.max_decompressed_bytes + 1)
        if len(raw) > limits.max_decompressed_bytes:
            raise _Fail(AnalysisStatus.OVERSIZED, "decompressed PNG data exceeds limit")
        raw += engine.flush()
    except _Fail:
        raise
    except zlib.error as exc:
        raise _Fail(AnalysisStatus.CORRUPT, f"PNG inflate failed: {exc}") from exc
    if len(raw) < expected:
        raise _Fail(AnalysisStatus.CORRUPT, "truncated PNG pixel data")
    rows: list[bytes] = []
    prev = bytearray(stride)
    for y in range(height):
        _check_deadline(start, limits)
        base = y * (1 + stride)
        ftype = raw[base]
        line = bytearray(raw[base + 1 : base + 1 + stride])
        if len(line) != stride:
            raise _Fail(AnalysisStatus.CORRUPT, "short PNG row")
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) // 2)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up_left = prev[i - channels] if i >= channels else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 0xFF
        else:
            raise _Fail(AnalysisStatus.CORRUPT, f"unknown PNG filter {ftype}")
        rows.append(bytes(line))
        prev = line
    image = {"width": width, "height": height,
             "bit_depth": int(ihdr["bit_depth"]),
             "color_type": int(ihdr["color_type"]), "channels": channels}
    coverage = {"rows_parsed": height, "pixels_parsed": width * height}
    return image, coverage, b"".join(rows)


_ZIGZAG = (
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
)


class _BitReader:
    """Bounded scan reader: unstuffs FF00 and stops cleanly at markers."""

    def __init__(self, scan: bytes) -> None:
        self._bits: list[int] = []
        i = 0
        while i < len(scan):
            byte = scan[i]
            if byte == 0xFF and i + 1 < len(scan):
                nxt = scan[i + 1]
                if nxt == 0x00:
                    self._bits.extend((byte >> s) & 1 for s in range(7, -1, -1))
                    i += 2
                    continue
                if 0xD0 <= nxt <= 0xD9:
                    raise _Fail(AnalysisStatus.CORRUPT,
                                "restart/EOI marker inside entropy data "
                                "(restart intervals outside declared subset)")
            self._bits.extend((byte >> s) & 1 for s in range(7, -1, -1))
            i += 1
        self._pos = 0

    def read_code(self, table: dict[tuple[int, int], int]) -> int:
        code = 0
        for length in range(1, 17):
            if self._pos >= len(self._bits):
                raise _Fail(AnalysisStatus.CORRUPT, "truncated JPEG entropy data")
            code = (code << 1) | self._bits[self._pos]
            self._pos += 1
            if (code, length) in table:
                return table[(code, length)]
        raise _Fail(AnalysisStatus.CORRUPT, "invalid JPEG Huffman code")

    def read_value(self, size: int) -> int:
        if size == 0:
            return 0
        if self._pos + size > len(self._bits):
            raise _Fail(AnalysisStatus.CORRUPT, "truncated JPEG entropy data")
        value = 0
        for _ in range(size):
            value = (value << 1) | self._bits[self._pos]
            self._pos += 1
        if value < (1 << (size - 1)):
            value -= (1 << size) - 1
        return value


def _parse_huffman(body: bytes) -> dict[int, dict[tuple[int, int], int]]:
    tables: dict[int, dict[tuple[int, int], int]] = {}
    i = 0
    while i < len(body):
        class_id = body[i]
        if i + 17 > len(body):
            raise _Fail(AnalysisStatus.CORRUPT, "truncated DHT segment")
        counts = body[i + 1 : i + 17]
        total = sum(counts)
        symbols = body[i + 17 : i + 17 + total]
        if len(symbols) != total:
            raise _Fail(AnalysisStatus.CORRUPT, "truncated DHT symbols")
        decode: dict[tuple[int, int], int] = {}
        code, k = 0, 0
        for length in range(1, 17):
            for _ in range(counts[length - 1]):
                decode[(code, length)] = symbols[k]
                k += 1
                code += 1
            code <<= 1
        tables[class_id] = decode
        i += 17 + total
    return tables


def _parse_jpeg(
    data: bytes, limits: ParserLimits, start: float
) -> tuple[dict[str, Any], dict[str, Any], tuple[tuple[int, ...], ...]]:
    """Parse an 8-bit baseline 4:4:4 JPEG; return image, coverage, blocks."""
    _check_deadline(start, limits)
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise _Fail(AnalysisStatus.UNSUPPORTED_FORMAT, "not JPEG bytes")
    pos = 2
    sof: dict[str, Any] | None = None
    tables: dict[int, dict[tuple[int, int], int]] = {}
    has_dqt = False
    scan: bytes | None = None
    while pos < len(data):
        if data[pos] != 0xFF:
            raise _Fail(AnalysisStatus.CORRUPT, "corrupt JPEG marker stream")
        marker = data[pos + 1] if pos + 1 < len(data) else 0
        if marker == 0xD9:  # EOI
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if pos + 4 > len(data):
            raise _Fail(AnalysisStatus.CORRUPT, "truncated JPEG segment")
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if length < 2 or pos + 2 + length > len(data):
            raise _Fail(AnalysisStatus.CORRUPT, "truncated JPEG segment body")
        body = data[pos + 4 : pos + 2 + length]
        if marker == 0xDB:
            has_dqt = True
        elif marker == 0xC4:
            tables.update(_parse_huffman(body))
        elif marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if marker != 0xC0:
                raise _Fail(AnalysisStatus.UNSUPPORTED_ENCODING,
                            f"JPEG frame type 0xFF{marker:02X} outside "
                            "declared baseline (SOF0) subset")
            if len(body) < 6:
                raise _Fail(AnalysisStatus.CORRUPT, "short SOF0 segment")
            precision = body[0]
            height, width = struct.unpack(">HH", body[1:5])
            ncomp = body[5]
            if precision != 8:
                raise _Fail(AnalysisStatus.UNSUPPORTED_ENCODING,
                            f"JPEG precision {precision} outside declared 8-bit subset")
            if ncomp != 3:
                raise _Fail(AnalysisStatus.UNSUPPORTED_ENCODING,
                            f"JPEG with {ncomp} components outside declared "
                            "4:4:4 subset")
            sampling = [body[6 + i * 3 + 1] for i in range(ncomp)]
            if any(s != 0x11 for s in sampling):
                raise _Fail(AnalysisStatus.UNSUPPORTED_ENCODING,
                            f"JPEG sampling {sampling} outside declared "
                            "4:4:4 subset")
            _check_dimensions(width, height, limits)
            sof = {"width": width, "height": height, "precision": precision,
                   "components": ncomp, "sampling": "4:4:4"}
        elif marker == 0xDA:
            if sof is None:
                raise _Fail(AnalysisStatus.CORRUPT, "SOS before SOF0")
            if not has_dqt or not tables:
                raise _Fail(AnalysisStatus.CORRUPT,
                            "JPEG scan without quantisation/Huffman tables")
            scan = data[pos + 2 + length :]
            break
        pos += 2 + length
    if sof is None:
        raise _Fail(AnalysisStatus.CORRUPT, "JPEG missing SOF0 frame")
    if scan is None:
        raise _Fail(AnalysisStatus.CORRUPT, "JPEG missing SOS scan")
    # End the scan at EOI (entropy data byte-stuffs FF, so a bare FFD9
    # can only be the marker); bytes after EOI are not image data.
    eoi = scan.find(b"\xff\xd9")
    if eoi != -1:
        scan = scan[:eoi]
    _check_deadline(start, limits)
    width, height = int(sof["width"]), int(sof["height"])
    mcus_x, mcus_y = (width + 7) // 8, (height + 7) // 8
    if 0x00 not in tables or 0x10 not in tables:
        raise _Fail(AnalysisStatus.CORRUPT, "JPEG missing DC/AC Huffman tables")
    reader = _BitReader(scan)
    dc_table, ac_table = tables[0x00], tables[0x10]
    prev = [0, 0, 0]
    blocks: list[tuple[int, ...]] = []
    for mcu in range(mcus_x * mcus_y):
        if mcu % 16 == 0:
            _check_deadline(start, limits)
        for comp in range(3):
            coeffs = [0] * 64
            size = reader.read_code(dc_table)
            prev[comp] += reader.read_value(size)
            coeffs[0] = prev[comp]
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
                    raise _Fail(AnalysisStatus.CORRUPT, "JPEG AC run overflows block")
                coeffs[_ZIGZAG[k]] = reader.read_value(sz)
                k += 1
            blocks.append(tuple(coeffs))
    coverage = {"blocks_parsed": len(blocks),
                "coefficients_parsed": len(blocks) * 64}
    return sof, coverage, tuple(blocks)


def analyze_bytes(
    data: bytes,
    *,
    limits: ParserLimits | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
) -> AnalysisResult:
    """Boundedly parse exact original bytes; every input gets one result.

    Never raises for malformed image input (``TypeError`` only for
    non-bytes callers): failures return an explicit failure status with
    errors, coverage so far and limitations, and never any findings.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("analysis input must be bytes")
    raw = bytes(data)
    active = limits or DEFAULT_LIMITS
    start = time.monotonic()
    if len(raw) > active.max_input_bytes:
        return _result(raw, AnalysisStatus.OVERSIZED, active, start,
                       detail=f"input size {len(raw)} exceeds "
                              f"{active.max_input_bytes}",
                       artifact_id=artifact_id,
                       artifact_version_id=artifact_version_id)
    is_png = raw.startswith(_PNG_MAGIC)
    is_jpeg = raw.startswith(b"\xff\xd8")
    if not is_png and not is_jpeg:
        return _result(raw, AnalysisStatus.UNSUPPORTED_FORMAT, active, start,
                       detail="original must be PNG or JPEG bytes (eval scope)",
                       artifact_id=artifact_id,
                       artifact_version_id=artifact_version_id)
    try:
        if is_png:
            image, coverage, pixels = _parse_png(raw, active, start)
            _check_deadline(start, active)
            return _result(
                raw, AnalysisStatus.PARSED, active, start, media_kind="png",
                artifact_id=artifact_id, artifact_version_id=artifact_version_id,
                image=image, coverage=coverage, pixels=pixels,
                limitations=("parser subset: 8-bit non-interlaced PNG; "
                             "metadata channels scored separately (CL-23)",))
        image, coverage, blocks = _parse_jpeg(raw, active, start)
        _check_deadline(start, active)
        return _result(
            raw, AnalysisStatus.PARSED, active, start, media_kind="jpeg",
            artifact_id=artifact_id, artifact_version_id=artifact_version_id,
            image=image, coverage=coverage, coefficients=blocks,
            limitations=("parser subset: 8-bit baseline 4:4:4 JPEG, quantized "
                         "coefficient domain; metadata scored separately (CL-23)",))
    except _Fail as fail:
        kind = "png" if is_png else "jpeg"
        limits_note: tuple[str, ...] = ()
        if fail.status is AnalysisStatus.UNSUPPORTED_ENCODING:
            limits_note = ("declared subset only; see contract doc",)
        return _result(raw, fail.status, active, start, detail=fail.detail,
                       media_kind=kind, artifact_id=artifact_id,
                       artifact_version_id=artifact_version_id,
                       limitations=limits_note)


def analyze_version(
    store: ArtifactStore,
    artifact_version_id: str,
    *,
    actor_id: str,
    limits: ParserLimits | None = None,
) -> AnalysisResult:
    """Analyse one stored original via its audited, hash-checked read.

    Tampered backing bytes raise ``HashMismatchError`` from the store
    instead of being analysed; a failed check is never an access.
    """
    version = store._require(artifact_version_id)  # same-package lookup
    raw = store.get_original(artifact_version_id, actor_id=actor_id,
                             purpose="analysis")
    return analyze_bytes(raw, limits=limits, artifact_id=version.artifact_id,
                         artifact_version_id=artifact_version_id)
