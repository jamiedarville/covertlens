"""Immutable originals and dataset-lifetime evidence (CL-8).

The store records the exact creation bytes of an eval-generated PNG/JPEG
before any preview or analysis transform touches them (EV-03). Bytes are
content-addressed by ``content_hash`` (CL-7 ``covertlens.ids``), versions
are immutable, and lineage plus every served read are retained for the
dataset lifetime (EV-05, C-01). Changed bytes under one logical artifact
create a new version and invalidate verdicts bound to superseded versions;
prior bytes are never overwritten (EV-04, C-05).

There is deliberately no delete, purge or overwrite operation: removal is
possible only through the approved dataset-retirement policy owned by
CL-11/OP-01, never through this API. The store is internal evidence
handling only; no detector outcome is recorded here and nothing in this
module equates an error with collusion (C-02).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import ids

RETENTION_POLICY = "dataset_lifetime"

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


class HashMismatchError(ValueError):
    """Creation and stored byte hashes differ; the bytes are not evidence."""


class UnsupportedKindError(ValueError):
    """Only eval-generated PNG/JPEG originals are in scope."""


class UnknownVersionError(KeyError):
    """The requested artifact version is not in the store."""


def sniff_media_kind(data: bytes) -> str:
    """Return ``png``/``jpeg`` from magic bytes; reject everything else."""
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpeg"
    raise UnsupportedKindError("original must be PNG or JPEG bytes (eval scope)")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Lineage:
    """Creation lineage captured at ingest, before any transform."""

    run_id: str
    producer_id: str
    created_at: str
    episode_id: str | None = None
    source_route: str | None = None
    parent_version_id: str | None = None


@dataclass(frozen=True)
class ArtifactVersion:
    """One immutable byte sequence of one logical artifact."""

    artifact_id: str
    artifact_version_id: str
    content_hash: str
    media_kind: str
    size_bytes: int
    lineage: Lineage
    supersedes: str | None = None


@dataclass(frozen=True)
class AccessRecord:
    """One served read of an original; append-only audit history."""

    access_id: str
    artifact_version_id: str
    content_hash: str
    actor_id: str
    purpose: str
    accessed_at: str


@dataclass(frozen=True)
class Derivative:
    """A preview/analysis transform output; never an original."""

    derivative_id: str
    parent_version_id: str
    transform: str
    content_hash: str


class ArtifactStore:
    """Append-only, content-addressed store for immutable originals.

    With ``root=None`` the store is in-memory (tests, contract checks).
    With a directory ``root`` blobs are written once as
    ``blobs/<sha256hex>`` and metadata to ``index.json``; reopening the
    directory restores versions, verdict bindings and access history.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self._blobs: dict[str, bytes] = {}
        self._versions: dict[str, ArtifactVersion] = {}
        self._by_artifact: dict[str, list[str]] = {}
        self._access: list[AccessRecord] = []
        self._verdicts: dict[str, str] = {}  # verdict_id -> version_id
        self._invalidated: set[str] = set()  # verdict_ids superseded
        self._derivatives: dict[str, Derivative] = {}
        if self._root is not None:
            (self._root / "blobs").mkdir(parents=True, exist_ok=True)
            self._load()

    # -- ingest ---------------------------------------------------------

    def put_original(
        self,
        data: bytes,
        *,
        run_id: str,
        producer_id: str,
        occurred_at: str | None = None,
        episode_id: str | None = None,
        artifact_id: str | None = None,
        declared_hash: str | None = None,
        source_route: str | None = None,
    ) -> ArtifactVersion:
        """Store exact creation bytes; return their immutable version.

        Identical bytes for the same artifact return the existing version
        (idempotent re-ingest). Changed bytes append a new version and
        invalidate verdicts bound to earlier versions of that artifact.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("original must be bytes")
        raw = bytes(data)
        media_kind = sniff_media_kind(raw)
        digest = ids.content_hash(raw)
        if declared_hash is not None and declared_hash != digest:
            raise HashMismatchError(
                f"declared creation hash {declared_hash} != computed {digest}"
            )
        art_id = artifact_id or ids.new_artifact_id()
        version_id = ids.artifact_version_id(art_id, digest)
        existing = self._versions.get(version_id)
        if existing is not None:
            return existing
        siblings = self._by_artifact.get(art_id, [])
        version = ArtifactVersion(
            artifact_id=art_id,
            artifact_version_id=version_id,
            content_hash=digest,
            media_kind=media_kind,
            size_bytes=len(raw),
            lineage=Lineage(
                run_id=run_id,
                producer_id=producer_id,
                created_at=occurred_at or _now(),
                episode_id=episode_id,
                source_route=source_route,
                parent_version_id=siblings[-1] if siblings else None,
            ),
            supersedes=siblings[-1] if siblings else None,
        )
        self._write_blob(digest, raw)
        self._versions[version_id] = version
        self._by_artifact.setdefault(art_id, []).append(version_id)
        for old_id in siblings:  # changed bytes invalidate prior verdicts
            for verdict_id, bound in self._verdicts.items():
                if bound == old_id:
                    self._invalidated.add(verdict_id)
        self._save()
        return version

    def register_derivative(
        self, parent_version_id: str, data: bytes, *, transform: str
    ) -> Derivative:
        """Record a transform output against its gated original.

        Derivatives live apart from originals: registering one can never
        overwrite, re-version or otherwise mutate the parent bytes.
        """
        if parent_version_id not in self._versions:
            raise UnknownVersionError(parent_version_id)
        digest = ids.content_hash(bytes(data))
        derivative = Derivative(
            derivative_id=f"drv_{digest.split(':', 1)[1][:16]}",
            parent_version_id=parent_version_id,
            transform=transform,
            content_hash=digest,
        )
        self._derivatives[derivative.derivative_id] = derivative
        return derivative

    # -- reads ------------------------------------------------------------

    def get_original(
        self,
        artifact_version_id: str,
        *,
        actor_id: str,
        purpose: str = "read",
        occurred_at: str | None = None,
    ) -> bytes:
        """Serve exact stored bytes after a hash check; audit the read.

        Corrupted backing bytes raise instead of being served, and a
        failed check is never recorded as a successful access.
        """
        version = self._require(artifact_version_id)
        raw = self._read_blob(version.content_hash)
        if ids.content_hash(raw) != version.content_hash:
            raise HashMismatchError(
                f"stored bytes for {artifact_version_id} fail hash check"
            )
        self._access.append(
            AccessRecord(
                access_id=f"acc_{len(self._access) + 1:06d}",
                artifact_version_id=artifact_version_id,
                content_hash=version.content_hash,
                actor_id=actor_id,
                purpose=purpose,
                accessed_at=occurred_at or _now(),
            )
        )
        self._save()
        return raw

    def verify(self, artifact_version_id: str) -> bool:
        """True when stored bytes still hash to the recorded value."""
        version = self._require(artifact_version_id)
        return (
            ids.content_hash(self._read_blob(version.content_hash))
            == version.content_hash
        )

    def verify_all(self) -> bool:
        return all(self.verify(v) for v in self._versions)

    # -- lineage, versions, verdicts, history ----------------------------

    def version_ids(self) -> list[str]:
        return list(self._versions)

    def versions(self, artifact_id: str) -> list[ArtifactVersion]:
        return [self._versions[v] for v in self._by_artifact.get(artifact_id, [])]

    def head_version(self, artifact_id: str) -> ArtifactVersion:
        rows = self.versions(artifact_id)
        if not rows:
            raise UnknownVersionError(artifact_id)
        return rows[-1]

    def lineage(self, artifact_version_id: str) -> list[ArtifactVersion]:
        """Version chain for one artifact, oldest creation first."""
        version = self._require(artifact_version_id)
        return self.versions(version.artifact_id)

    def register_verdict(self, verdict_id: str, artifact_version_id: str) -> None:
        """Bind a gate verdict to one exact version (CL-7 ``gate.verdict``).

        A verdict bound to already-superseded bytes starts invalidated:
        only the head version of an artifact can hold a current verdict.
        """
        version = self._require(artifact_version_id)
        self._verdicts[verdict_id] = artifact_version_id
        siblings = self._by_artifact[version.artifact_id]
        if siblings[-1] == artifact_version_id:
            self._invalidated.discard(verdict_id)
        else:
            self._invalidated.add(verdict_id)
        self._save()

    def verdict_status(self, verdict_id: str) -> str:
        """``current``, ``invalidated`` (superseded bytes) or ``unknown``."""
        if verdict_id in self._invalidated:
            return "invalidated"
        return "current" if verdict_id in self._verdicts else "unknown"

    def valid_verdicts(self, artifact_version_id: str) -> list[str]:
        return sorted(
            v
            for v, bound in self._verdicts.items()
            if bound == artifact_version_id and v not in self._invalidated
        )

    def access_history(
        self, artifact_version_id: str | None = None
    ) -> tuple[AccessRecord, ...]:
        if artifact_version_id is None:
            return tuple(self._access)
        return tuple(
            r for r in self._access if r.artifact_version_id == artifact_version_id
        )

    # -- export -----------------------------------------------------------

    def export_record(self, artifact_version_id: str) -> dict[str, Any]:
        """JSON-ready evidence record for one version (see JSON Schema)."""
        version = self._require(artifact_version_id)
        return {
            "artifact_id": version.artifact_id,
            "artifact_version_id": version.artifact_version_id,
            "content_hash": version.content_hash,
            "media_kind": version.media_kind,
            "size_bytes": version.size_bytes,
            "supersedes": version.supersedes,
            "retention_policy": RETENTION_POLICY,
            "lineage": asdict(version.lineage),
        }

    def stats(self) -> dict[str, int]:
        return {
            "artifacts": len(self._by_artifact),
            "versions": len(self._versions),
            "derivatives": len(self._derivatives),
            "access_records": len(self._access),
            "verdicts": len(self._verdicts),
            "invalidated_verdicts": len(self._invalidated),
        }

    # -- internals --------------------------------------------------------

    def _require(self, artifact_version_id: str) -> ArtifactVersion:
        try:
            return self._versions[artifact_version_id]
        except KeyError:
            raise UnknownVersionError(artifact_version_id) from None

    def _read_blob(self, digest: str) -> bytes:
        if self._root is None:
            return self._blobs[digest]
        return (self._root / "blobs" / digest.split(":", 1)[1]).read_bytes()

    def _write_blob(self, digest: str, raw: bytes) -> None:
        if self._root is None:
            self._blobs.setdefault(digest, raw)
            return
        target = self._root / "blobs" / digest.split(":", 1)[1]
        if not target.exists():  # content-addressed blobs are write-once
            target.write_bytes(raw)

    def _save(self) -> None:
        if self._root is None:
            return
        payload = {
            "versions": [asdict(v) for v in self._versions.values()],
            "access": [asdict(r) for r in self._access],
            "verdicts": self._verdicts,
            "invalidated": sorted(self._invalidated),
        }
        tmp = self._root / "index.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._root / "index.json")

    def _load(self) -> None:
        if self._root is None:
            return
        index = self._root / "index.json"
        if not index.exists():
            return
        payload = json.loads(index.read_text(encoding="utf-8"))
        for row in payload.get("versions", []):
            row["lineage"] = Lineage(**row["lineage"])
            version = ArtifactVersion(**row)
            self._versions[version.artifact_version_id] = version
            self._by_artifact.setdefault(version.artifact_id, []).append(
                version.artifact_version_id
            )
        self._access = [AccessRecord(**row) for row in payload.get("access", [])]
        self._verdicts = dict(payload.get("verdicts", {}))
        self._invalidated = set(payload.get("invalidated", []))
