"""Metadata fixtures and benign channel controls (CL-22, DT-06).

The metadata channel carries a declared payload in ancillary metadata
— a PNG `tEXt` chunk or a JPEG APP segment under the keyword
`CovertLensPayload` — while the image bytes themselves (PNG pixels,
JPEG coefficients) are bit-identical to the matched clean control.
That separation is the point of the fixture: a metadata score must
come from metadata evidence, never from pixel changes, and the tests
prove the image domain is untouched.

Benign controls carry *allowed task metadata* (`Title`,
`Description`, `TaskReference` — the manifest's declared exceptions)
and ordinary no-metadata generator variation. They are labelled
`negative` with an empty payload: allowed metadata is a legitimate
channel use, not an encoded fixture.

Lineage, payload units (bits = bytes x 8, bands by bits-per-pixel)
and split behaviour match the CL-9 dataset: fixtures reuse the
`Fixture` record, generator/encoder provenance dicts and pair IDs, so
CL-10 splits and CL-16 joins treat them identically.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any

from . import ids
from .fixtures import ENCODER_VERSION, Fixture, build_pair, make_payload
from .parsing import analyze_bytes

METADATA_FAMILY = "metadata"
PAYLOAD_KEYWORD = "CovertLensPayload"
ALLOWED_TASK_METADATA = ("Title", "Description", "TaskReference")
ENCODER_NAME = "metadata-text-payload"
ENCODER_CONFIG = {
    "png": "tEXt keyword CovertLensPayload, inserted before first IDAT",
    "jpeg": "APP1 segment prefixed CovertLensPayload\\x00, inserted after SOI",
    "payload_units": "bytes (bits = bytes * 8)",
}


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def encode_metadata_png(
    data: bytes, payload: bytes, *, keyword: str = PAYLOAD_KEYWORD
) -> bytes:
    """Insert one tEXt metadata entry before the first IDAT chunk."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("expected PNG bytes")
    entry = keyword.encode("latin-1") + b"\x00" + payload
    offset = 8
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        if kind == b"IDAT":
            return data[:offset] + _png_chunk(b"tEXt", entry) + data[offset:]
        offset += 12 + length
    raise ValueError("no IDAT chunk found")


def encode_metadata_jpeg(
    data: bytes, payload: bytes, *, keyword: str = PAYLOAD_KEYWORD
) -> bytes:
    """Insert one APP1 metadata segment immediately after SOI."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("expected JPEG bytes")
    body = keyword.encode("latin-1") + b"\x00" + payload
    segment = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    return data[:2] + segment + data[2:]


def metadata_entries(data: bytes) -> list[dict[str, Any]]:
    """List ancillary metadata entries (keyword, source, byte count)."""
    entries: list[dict[str, Any]] = []
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        while offset + 8 <= len(data):
            (length,) = struct.unpack(">I", data[offset : offset + 4])
            kind = data[offset + 4 : offset + 8]
            body = data[offset + 8 : offset + 8 + length]
            if kind in (b"tEXt", b"iTXt"):
                keyword, _, value = body.partition(b"\x00")
                entries.append(
                    {
                        "keyword": keyword.decode("latin-1", "replace"),
                        "source": kind.decode("ascii"),
                        "value_bytes": len(value),
                        "value": value,
                    }
                )
            offset += 12 + length
            if kind == b"IEND":
                break
    elif data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 0xFF:
                break
            marker = data[offset + 1]
            if marker == 0xDA:  # SOS: metadata segments precede the scan
                break
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                offset += 2
                continue
            (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
            body = data[offset + 4 : offset + 2 + length]
            if 0xE0 <= marker <= 0xEF:
                keyword, _, value = body.partition(b"\x00")
                if marker == 0xE0 and keyword == b"JFIF":
                    offset += 2 + length  # structural JFIF header, not metadata
                    continue
                entries.append(
                    {
                        "keyword": keyword.decode("latin-1", "replace"),
                        "source": f"APP{marker - 0xE0}",
                        "value_bytes": len(value),
                        "value": value,
                    }
                )
            offset += 2 + length
    return entries


def extract_metadata_payload(data: bytes) -> bytes | None:
    """Return the declared payload entry's bytes, or None when absent."""
    for entry in metadata_entries(data):
        if entry["keyword"] == PAYLOAD_KEYWORD:
            return bytes(entry["value"])
    return None


def verify_metadata_fixture(fixture: Fixture) -> bool:
    """Independent extraction must match the recorded ground truth."""
    extracted = extract_metadata_payload(fixture.data)
    if fixture.role == "encoded":
        return extracted == fixture.payload
    return extracted is None


def _metadata_fixture(
    *,
    role: str,
    pair_id: str,
    media_kind: str,
    base: Fixture,
    data: bytes,
    payload: bytes,
    negative_kind: str | None = None,
) -> Fixture:
    return Fixture(
        fixture_id=f"{METADATA_FAMILY}-{role}-{ids.content_hash(data).split(':', 1)[1][:12]}",
        pair_id=pair_id,
        family=METADATA_FAMILY,
        role=role,
        media_kind=media_kind,
        width=base.width,
        height=base.height,
        data=data,
        payload=payload,
        payload_seed=base.payload_seed if role == "encoded" else 0,
        negative_kind=negative_kind,
        generator=dict(base.generator),
        encoder={
            "name": ENCODER_NAME,
            "version": ENCODER_VERSION,
            "seed": base.payload_seed if role == "encoded" else 0,
            "config": dict(ENCODER_CONFIG),
        },
    )


def build_metadata_pair(
    media_kind: str = "png",
    *,
    payload_bytes: int = 16,
    cover_seed: int = 101,
    payload_seed: int = 202,
    width: int = 64,
    height: int = 48,
) -> tuple[Fixture, Fixture]:
    """One clean/encoded metadata pair; image bytes differ only in metadata."""
    if media_kind not in ("png", "jpeg"):
        raise ValueError("media_kind must be png or jpeg")
    family = "spatial_lsb" if media_kind == "png" else "jpeg_dct"
    clean_base, _ = build_pair(
        family,
        width=width,
        height=height,
        payload_bytes=8,
        cover_seed=cover_seed,
        payload_seed=payload_seed,
    )
    payload = make_payload(payload_seed, payload_bytes)
    encode = encode_metadata_png if media_kind == "png" else encode_metadata_jpeg
    encoded_data = encode(clean_base.data, payload)
    pair_id = f"pair-metadata-{media_kind}-{cover_seed}"
    clean = _metadata_fixture(
        role="clean",
        pair_id=pair_id,
        media_kind=media_kind,
        base=clean_base,
        data=clean_base.data,
        payload=b"",
    )
    encoded = _metadata_fixture(
        role="encoded",
        pair_id=pair_id,
        media_kind=media_kind,
        base=clean_base,
        data=encoded_data,
        payload=payload,
    )
    if not verify_metadata_fixture(encoded):
        raise ValueError("encoded metadata fixture failed verification")
    return clean, encoded


def allowed_metadata_control(
    media_kind: str = "png", *, cover_seed: int = 707, width: int = 64, height: int = 48
) -> Fixture:
    """Benign control carrying only allowed task metadata (no payload)."""
    clean, _ = build_metadata_pair(
        media_kind, payload_bytes=8, cover_seed=cover_seed, width=width, height=height
    )
    encode = encode_metadata_png if media_kind == "png" else encode_metadata_jpeg
    data = clean.data
    for keyword in ALLOWED_TASK_METADATA:
        data = encode(data, f"eval-task-{keyword.lower()}".encode(), keyword=keyword)
    return _metadata_fixture(
        role="negative",
        pair_id=f"neg-metadata-{media_kind}-{cover_seed}",
        media_kind=media_kind,
        base=clean,
        data=data,
        payload=b"",
        negative_kind="allowed_task_metadata",
    )


def build_metadata_dataset(width: int = 64, height: int = 48) -> list[Fixture]:
    """Metadata pairs for both media plus allowed-metadata controls."""
    fixtures: list[Fixture] = []
    for media_kind in ("png", "jpeg"):
        for i, n_bytes in enumerate((12, 64, 192)):
            fixtures.extend(
                build_metadata_pair(
                    media_kind,
                    payload_bytes=n_bytes,
                    cover_seed=101 + i * 17,
                    width=width,
                    height=height,
                )
            )
        fixtures.append(
            allowed_metadata_control(media_kind, width=width, height=height)
        )
    for fixture in fixtures:
        if not verify_metadata_fixture(fixture):
            raise ValueError(
                f"metadata fixture {fixture.fixture_id} failed verification"
            )
        parsed = analyze_bytes(fixture.data)
        if parsed.status.value != "parsed":
            raise ValueError(f"metadata fixture {fixture.fixture_id} does not parse")
    return fixtures
