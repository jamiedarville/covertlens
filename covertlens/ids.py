"""Stable identifiers for CovertLens harness contracts (CL-7).

ID rules:
- Entity IDs are prefixed UUIDs assigned once and never reassigned.
- ``content_hash`` is ``sha256:<hex>`` over the exact original bytes.
- Event IDs are deterministic: the same logical event (same run, sequence,
  type and idempotency key) always yields the same ID, so retries and
  repeated references deduplicate instead of double-counting (EV-07).
"""

from __future__ import annotations

import hashlib
import re
import uuid

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVENT_RE = re.compile(r"^evt_[0-9a-f]{32}$")


def content_hash(data: bytes) -> str:
    """Return ``sha256:<hex>`` for exact original bytes."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("content_hash expects bytes")
    return "sha256:" + hashlib.sha256(bytes(data)).hexdigest()


def is_content_hash(value: object) -> bool:
    return isinstance(value, str) and bool(_HASH_RE.match(value))


def _entity(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def new_run_id() -> str:
    return _entity("run")


def new_episode_id() -> str:
    return _entity("ep")


def new_artifact_id() -> str:
    return _entity("art")


def new_verdict_id() -> str:
    return _entity("vrd")


def artifact_version_id(artifact_id: str, digest: str) -> str:
    """Version ID binds an artifact to one exact byte sequence (EV-04)."""
    if not artifact_id:
        raise ValueError("artifact_id is required")
    if not is_content_hash(digest):
        raise ValueError("digest must be a sha256:<hex> content hash")
    short = digest.split(":", 1)[1][:16]
    return f"{artifact_id}.v-{short}"


def delivery_id(run_id: str, artifact_version: str, recipient_id: str, attempt: int) -> str:
    """Deterministic delivery ID; retries of one attempt reuse it."""
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    raw = f"{run_id}|{artifact_version}|{recipient_id}|{attempt}"
    return "dlv_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def event_id(run_id: str, seq: int, event_type: str, idempotency_key: str | None = None) -> str:
    """Deterministic event ID derived from run, order, type and key."""
    if seq < 0:
        raise ValueError("seq must be >= 0")
    raw = f"{run_id}|{seq}|{event_type}|{idempotency_key or ''}"
    return "evt_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def is_event_id(value: object) -> bool:
    return isinstance(value, str) and bool(_EVENT_RE.match(value))
