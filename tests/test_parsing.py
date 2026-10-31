"""CL-13 acceptance tests: bounded PNG/JPEG parsing and result schema.

AC1 no resize or recompression occurs before native analysis (DET-01)
AC2 corrupt, unsupported, oversized and timeout cases have explicit results (DET-01)
AC3 worker memory/runtime limits and channel finding/version schema are tested (DET-02)
"""

import struct
import zlib

import pytest

from covertlens import ids
from covertlens.fixtures import build_pair
from covertlens.parsing import (
    DEFAULT_LIMITS,
    AnalysisStatus,
    Finding,
    ParserLimits,
    analyze_bytes,
    analyze_version,
    validate_finding,
    validate_result,
)
from covertlens.store import ArtifactStore, HashMismatchError

TS = "2026-10-28T12:00:00Z"


def png_fixture():
    clean, _ = build_pair("spatial_lsb", width=32, height=24, payload_bytes=8)
    return clean


def jpeg_fixture():
    clean, _ = build_pair("jpeg_dct", width=32, height=24, payload_bytes=8)
    return clean


def stored_version(data: bytes):
    store = ArtifactStore()
    version = store.put_original(
        data, run_id="run_test", producer_id="agent-a", occurred_at=TS,
    )
    return store, version


def minimal_png_header(width=8, height=8, depth=8, color=2, interlace=0) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace)

    def chunk(kind: bytes, body: bytes) -> bytes:
        import binascii

        crc = binascii.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x00" * (width * 3)))
        + chunk(b"IEND", b"")
    )


def filtered_png(pixels: bytes, width: int, height: int) -> bytes:
    """Save RGB pixels exercising PNG filters 1-4 (Sub/Up/Average/Paeth)."""
    import binascii

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = binascii.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    stride = width * 3
    rows = [pixels[y * stride : (y + 1) * stride] for y in range(height)]

    def paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)

    raw = bytearray()
    prev = bytes(stride)
    for y, row in enumerate(rows):
        ftype = (y % 4) + 1  # cycle filters 1,2,3,4,1,... (never none)
        raw.append(ftype)
        bpp = 3
        for i, val in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:
                pred = left
            elif ftype == 2:
                pred = up
            elif ftype == 3:
                pred = (left + up) // 2
            else:
                pred = paeth(left, up, up_left)
            raw.append((val - pred) & 0xFF)
        prev = row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def test_png_parses_exact_original_bytes_without_transform():
    fixture = png_fixture()
    result = analyze_bytes(fixture.data)
    assert result.status == AnalysisStatus.PARSED
    assert result.transform_applied is False
    assert result.content_hash == ids.content_hash(fixture.data)
    assert result.media_kind == "png"
    assert result.image["width"] == 32 and result.image["height"] == 24
    assert result.coverage["rows_parsed"] == 24
    assert result.coverage["pixels_parsed"] == 32 * 24
    assert result.errors == ()
    assert result.findings == ()
    assert result.pixels is not None and len(result.pixels) == 32 * 24 * 3
    assert validate_result(result) == []
    assert validate_result(result.to_dict()) == []


def test_jpeg_parses_coefficient_domain_without_transform():
    fixture = jpeg_fixture()
    result = analyze_bytes(fixture.data)
    assert result.status == AnalysisStatus.PARSED
    assert result.transform_applied is False
    assert result.content_hash == ids.content_hash(fixture.data)
    assert result.media_kind == "jpeg"
    # 32x24 -> 4x3 MCU grid, 3 components (4:4:4), 64 coefficients per block.
    assert result.coverage["blocks_parsed"] == 4 * 3 * 3
    assert result.coverage["coefficients_parsed"] == 4 * 3 * 3 * 64
    assert result.coefficients is not None
    assert len(result.coefficients) == 4 * 3 * 3
    assert all(len(block) == 64 for block in result.coefficients)
    assert validate_result(result) == []


def test_filtered_png_rows_are_unfiltered_to_original_pixels():
    width, height = 12, 8
    pixels = bytes((i * 37 + 11) % 256 for i in range(width * height * 3))
    result = analyze_bytes(filtered_png(pixels, width, height))
    assert result.status == AnalysisStatus.PARSED
    assert result.pixels == pixels
    assert result.coverage["rows_parsed"] == height


def test_store_version_analysis_uses_audited_original_read():
    fixture = png_fixture()
    store, version = stored_version(fixture.data)
    result = analyze_version(store, version.artifact_version_id, actor_id="detector")
    assert result.status == AnalysisStatus.PARSED
    assert result.artifact_id == version.artifact_id
    assert result.artifact_version_id == version.artifact_version_id
    assert result.content_hash == version.content_hash
    history = store.access_history(version.artifact_version_id)
    assert [(h.actor_id, h.purpose) for h in history] == [("detector", "analysis")]
    # Hash drift in the backing blob is never analysed as evidence.
    store._blobs[version.content_hash] = b"\x89PNG\r\n\x1a\n" + b"tampered"
    with pytest.raises(HashMismatchError):
        analyze_version(store, version.artifact_version_id, actor_id="detector")


def test_corrupt_png_and_jpeg_have_explicit_results():
    good_png = png_fixture().data
    truncated = analyze_bytes(good_png[: len(good_png) // 2])
    assert truncated.status == AnalysisStatus.CORRUPT
    assert truncated.findings == () and truncated.errors
    assert truncated.content_hash == ids.content_hash(good_png[: len(good_png) // 2])
    bad_crc = bytearray(good_png)
    bad_crc[20] ^= 0xFF  # inside IHDR body; CRC no longer matches
    assert analyze_bytes(bytes(bad_crc)).status == AnalysisStatus.CORRUPT
    good_jpeg = jpeg_fixture().data
    assert analyze_bytes(good_jpeg[:40]).status == AnalysisStatus.CORRUPT
    for result in (truncated, analyze_bytes(good_jpeg[:40])):
        assert result.transform_applied is False
        assert validate_result(result) == []


def test_unsupported_format_and_encodings_have_explicit_results():
    assert analyze_bytes(b"GIF89a-not-in-scope").status == AnalysisStatus.UNSUPPORTED_FORMAT
    assert analyze_bytes(b"").status == AnalysisStatus.UNSUPPORTED_FORMAT
    depth16 = analyze_bytes(minimal_png_header(depth=16))
    assert depth16.status == AnalysisStatus.UNSUPPORTED_ENCODING
    assert depth16.limitations
    interlaced = analyze_bytes(minimal_png_header(interlace=1))
    assert interlaced.status == AnalysisStatus.UNSUPPORTED_ENCODING
    # Progressive JPEG (SOF2) and subsampled JPEG sit outside the subset.
    fixture = jpeg_fixture().data
    progressive = fixture.replace(b"\xff\xc0", b"\xff\xc2", 1)
    assert analyze_bytes(progressive).status == AnalysisStatus.UNSUPPORTED_ENCODING
    subsampled = bytearray(fixture)
    sof = fixture.index(b"\xff\xc0")
    subsampled[sof + 9] = 0x22  # first component sampling 2x2
    assert analyze_bytes(bytes(subsampled)).status == AnalysisStatus.UNSUPPORTED_ENCODING
    for result in (depth16, interlaced):
        assert result.errors and result.findings == ()
        assert validate_result(result) == []


def test_oversized_and_timeout_cases_have_explicit_results():
    fixture = png_fixture()
    by_input = analyze_bytes(fixture.data, limits=ParserLimits(max_input_bytes=16))
    assert by_input.status == AnalysisStatus.OVERSIZED
    by_pixels = analyze_bytes(fixture.data, limits=ParserLimits(max_pixels=100))
    assert by_pixels.status == AnalysisStatus.OVERSIZED
    by_decompressed = analyze_bytes(
        fixture.data, limits=ParserLimits(max_decompressed_bytes=64))
    assert by_decompressed.status == AnalysisStatus.OVERSIZED
    timed_out = analyze_bytes(fixture.data, limits=ParserLimits(max_runtime_s=0))
    assert timed_out.status == AnalysisStatus.TIMEOUT
    for result in (by_input, by_pixels, by_decompressed, timed_out):
        assert result.errors and result.findings == ()
        assert result.transform_applied is False
        assert validate_result(result) == []
    with pytest.raises(TypeError):
        analyze_bytes("not-bytes")  # type: ignore[arg-type]


def test_finding_and_result_schema_validation():
    result = analyze_bytes(jpeg_fixture().data)
    finding = Finding(
        family="jpeg_dct",
        detector_name="dct-baseline",
        detector_version="0.1.0",
        score=0.25,
        coverage={"blocks": 36},
        evidence={"coefficients": 36 * 64},
        limitations=("baseline only",),
    )
    assert validate_finding(finding) == []
    assert validate_finding(finding.to_dict()) == []
    assert validate_finding({**finding.to_dict(), "score": 1.5}) != []
    assert validate_finding({**finding.to_dict(), "family": "nope"}) != []
    assert validate_finding({**finding.to_dict(), "score": True}) != []
    doc = result.to_dict()
    doc["findings"] = [finding.to_dict()]
    assert validate_result(doc) == []
    failed = analyze_bytes(b"GIF89a")
    bad = {**failed.to_dict(), "findings": [finding.to_dict()]}
    assert validate_result(bad) != []  # failures never carry findings


def test_defaults_match_planned_worker_bounds():
    assert DEFAULT_LIMITS.max_input_bytes == 10 * 1024 * 1024
    assert DEFAULT_LIMITS.max_pixels == 20_000_000
    assert DEFAULT_LIMITS.max_runtime_s == 2.0
    with pytest.raises(ValueError):
        ParserLimits(max_pixels=0)
