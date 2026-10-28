"""CL-8 acceptance tests: immutable originals and dataset-lifetime evidence.

AC1 creation and stored byte hashes match (EV-03)
AC2 changed bytes create a new immutable version and invalidate prior verdicts (EV-04, C-05)
AC3 originals, lineage and access history follow dataset-lifetime retention (EV-05, C-01)
"""

import dataclasses

import pytest

from covertlens import ids
from covertlens.store import (
    RETENTION_POLICY,
    ArtifactStore,
    HashMismatchError,
    UnsupportedKindError,
)

PNG_V1 = b"\x89PNG\r\n\x1a\n" + b"synthetic-clean-png-v1"
PNG_V2 = b"\x89PNG\r\n\x1a\n" + b"synthetic-encoded-png-v2-changed-bytes"
JPEG_V1 = b"\xff\xd8\xff\xe0" + b"synthetic-jpeg-v1" + b"\xff\xd9"
TS = "2026-10-28T12:00:00Z"


def put(store, data=PNG_V1, **kw):
    kw.setdefault("run_id", "run_test")
    kw.setdefault("producer_id", "agent-a")
    kw.setdefault("occurred_at", TS)
    return store.put_original(data, **kw)


def test_creation_and_stored_hashes_match():
    store = ArtifactStore()
    version = put(store)
    assert version.content_hash == ids.content_hash(PNG_V1)
    assert version.artifact_version_id == ids.artifact_version_id(
        version.artifact_id, version.content_hash
    )
    assert store.get_original(version.artifact_version_id, actor_id="gate") == PNG_V1
    assert store.verify(version.artifact_version_id) is True


def test_declared_hash_must_match_creation_bytes():
    store = ArtifactStore()
    version = put(store, declared_hash=ids.content_hash(PNG_V1))
    assert version.content_hash == ids.content_hash(PNG_V1)
    with pytest.raises(HashMismatchError):
        put(store, declared_hash=ids.content_hash(PNG_V2))
    assert store.stats()["versions"] == 1  # rejected bytes stored nothing


def test_only_png_and_jpeg_originals_are_accepted():
    store = ArtifactStore()
    assert put(store, JPEG_V1).media_kind == "jpeg"
    with pytest.raises(UnsupportedKindError):
        put(store, b"GIF89a-not-in-scope")
    with pytest.raises(UnsupportedKindError):
        put(store, b"")


def test_same_bytes_reingest_idempotently_without_new_version():
    store = ArtifactStore()
    first = put(store)
    again = put(store, artifact_id=first.artifact_id)
    assert again.artifact_version_id == first.artifact_version_id
    assert len(store.versions(first.artifact_id)) == 1


def test_changed_bytes_create_new_immutable_version():
    store = ArtifactStore()
    v1 = put(store)
    v2 = put(store, PNG_V2, artifact_id=v1.artifact_id)
    assert v2.artifact_version_id != v1.artifact_version_id
    assert v2.supersedes == v1.artifact_version_id
    assert [v.artifact_version_id for v in store.versions(v1.artifact_id)] == [
        v1.artifact_version_id,
        v2.artifact_version_id,
    ]
    # The prior version is untouched and still serves its exact bytes.
    assert store.get_original(v1.artifact_version_id, actor_id="reviewer") == PNG_V1
    assert store.get_original(v2.artifact_version_id, actor_id="reviewer") == PNG_V2
    assert store.head_version(v1.artifact_id).artifact_version_id == v2.artifact_version_id


def test_new_version_invalidates_prior_verdicts_only():
    store = ArtifactStore()
    v1 = put(store)
    store.register_verdict("vrd_1", v1.artifact_version_id)
    assert store.verdict_status("vrd_1") == "current"
    again = put(store, artifact_id=v1.artifact_id)  # identical bytes: no invalidation
    assert again.artifact_version_id == v1.artifact_version_id
    assert store.verdict_status("vrd_1") == "current"
    v2 = put(store, PNG_V2, artifact_id=v1.artifact_id)
    assert store.verdict_status("vrd_1") == "invalidated"
    assert store.valid_verdicts(v1.artifact_version_id) == []
    store.register_verdict("vrd_2", v2.artifact_version_id)
    assert store.verdict_status("vrd_2") == "current"
    assert store.valid_verdicts(v2.artifact_version_id) == ["vrd_2"]


def test_stored_bytes_are_tamper_evident():
    store = ArtifactStore()
    version = put(store)
    # Simulate out-of-band corruption of the backing blob.
    store._blobs[version.content_hash] = b"\x89PNG\r\n\x1a\n" + b"tampered"
    assert store.verify(version.artifact_version_id) is False
    with pytest.raises(HashMismatchError):
        store.get_original(version.artifact_version_id, actor_id="gate")


def test_records_are_frozen_and_store_has_no_delete_or_overwrite():
    store = ArtifactStore()
    version = put(store)
    with pytest.raises(dataclasses.FrozenInstanceError):
        version.content_hash = ids.content_hash(PNG_V2)  # type: ignore[misc]
    for forbidden in ("delete", "remove", "purge", "overwrite", "update_original"):
        assert not hasattr(store, forbidden), forbidden


def test_lineage_chain_is_preserved_in_creation_order():
    store = ArtifactStore()
    v1 = put(store)
    v2 = put(store, PNG_V2, artifact_id=v1.artifact_id)
    chain = store.lineage(v2.artifact_version_id)
    assert [v.artifact_version_id for v in chain] == [
        v1.artifact_version_id,
        v2.artifact_version_id,
    ]
    assert chain[0].lineage.parent_version_id is None
    assert chain[1].lineage.parent_version_id == v1.artifact_version_id
    assert chain[1].lineage.producer_id == "agent-a"


def test_every_served_read_joins_the_access_history():
    store = ArtifactStore()
    version = put(store)
    store.get_original(version.artifact_version_id, actor_id="gate", purpose="analysis")
    store.get_original(version.artifact_version_id, actor_id="reviewer", purpose="triage")
    history = store.access_history(version.artifact_version_id)
    assert [(h.actor_id, h.purpose) for h in history] == [
        ("gate", "analysis"),
        ("reviewer", "triage"),
    ]
    assert all(h.content_hash == version.content_hash for h in history)
    assert store.access_history() == history  # unfiltered view sees the same rows


def test_preview_derivative_never_overwrites_the_original():
    store = ArtifactStore()
    version = put(store)
    derivative = store.register_derivative(
        version.artifact_version_id, b"thumbnail-bytes", transform="preview_thumbnail"
    )
    assert derivative.parent_version_id == version.artifact_version_id
    assert derivative.content_hash == ids.content_hash(b"thumbnail-bytes")
    assert store.get_original(version.artifact_version_id, actor_id="gate") == PNG_V1
    assert store.verify(version.artifact_version_id) is True


def test_filesystem_store_round_trips_exact_bytes(tmp_path):
    root = tmp_path / "evidence"
    store = ArtifactStore(root)
    v1 = put(store)
    v2 = put(store, PNG_V2, artifact_id=v1.artifact_id)
    store.register_verdict("vrd_1", v1.artifact_version_id)
    store.get_original(v1.artifact_version_id, actor_id="gate")

    reopened = ArtifactStore(root)
    assert reopened.get_original(v1.artifact_version_id, actor_id="gate") == PNG_V1
    assert reopened.get_original(v2.artifact_version_id, actor_id="gate") == PNG_V2
    assert reopened.verify_all() is True
    assert reopened.verdict_status("vrd_1") == "invalidated"
    assert len(reopened.access_history()) >= 1
    assert [v.artifact_version_id for v in reopened.versions(v1.artifact_id)] == [
        v1.artifact_version_id,
        v2.artifact_version_id,
    ]


def test_filesystem_blobs_are_content_addressed_and_immutable_on_disk(tmp_path):
    root = tmp_path / "evidence"
    store = ArtifactStore(root)
    version = put(store)
    blob = root / "blobs" / version.content_hash.split(":", 1)[1]
    assert blob.read_bytes() == PNG_V1
    blob.write_bytes(b"\x89PNG\r\n\x1a\n" + b"tampered-on-disk")
    assert store.verify(version.artifact_version_id) is False


def test_export_record_carries_dataset_lifetime_retention():
    store = ArtifactStore()
    version = put(store)
    record = store.export_record(version.artifact_version_id)
    assert record["retention_policy"] == RETENTION_POLICY == "dataset_lifetime"
    assert record["content_hash"] == version.content_hash
    assert record["lineage"]["producer_id"] == "agent-a"
    assert record["lineage"]["run_id"] == "run_test"
