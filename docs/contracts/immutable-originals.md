# Immutable originals and dataset-lifetime evidence (CL-8 · EV-03/04/05)

Every eval-generated PNG/JPEG is stored as the exact bytes presented at
creation, before any preview or analysis transform can touch them. Those
bytes, their lineage and every served read are evidence retained for the
dataset lifetime. Machine contract:
[artifact-store.schema.json](../../schemas/artifact-store.schema.json) and
`covertlens.store.ArtifactStore`. IDs and hashes reuse the CL-7 contracts
in [harness-events.md](harness-events.md).

## Guarantees

| Acceptance criterion | Guarantee | Mechanism |
|---|---|---|
| Creation and stored byte hashes match (EV-03) | The hash recorded at ingest equals the hash of the bytes later served | `content_hash = sha256:<hex>` over exact creation bytes; optional `declared_hash` is checked at ingest and a mismatch stores nothing; every `get_original` re-hashes the backing blob and raises `HashMismatchError` instead of serving corrupt bytes |
| Changed bytes create a new immutable version and invalidate prior verdicts (EV-04, C-05) | One logical `artifact_id` has an append-only chain of versions; only the head version can hold a current verdict | Identical bytes re-ingest idempotently; changed bytes append `<artifact_id>.v-<hash16>` with `supersedes` pointing at the prior version, prior blobs stay byte-identical, and verdicts bound to superseded versions (including late registrations) report `invalidated` |
| Originals, lineage and access history follow dataset-lifetime retention (EV-05, C-01) | Nothing in the store API deletes, purges or overwrites evidence | No delete/overwrite methods exist; records are frozen; blobs are content-addressed and write-once; `retention_policy` is `dataset_lifetime` on every exported record; removal is only via the approved dataset-retirement policy (CL-11/OP-01) |

## Rules downstream tasks rely on

1. **Originals before transforms.** Ingest happens at creation. A preview
   or analysis output is registered with `register_derivative` against its
   parent version and lives apart from originals; it can never overwrite
   or re-version the parent bytes (R-06 in the route inventory).
2. **Scope.** Only PNG/JPEG magic bytes are accepted; anything else raises
   `UnsupportedKindError`. Consumer uploads are out of scope (C-08).
3. **Audited reads.** Every successful `get_original` appends an
   `AccessRecord` (actor, purpose, version, hash). A read that fails its
   hash check serves nothing and is not recorded as an access.
4. **Verdict binding.** Gate verdicts (CL-7 `gate.verdict`) bind to one
   exact `artifact_version_id` via `register_verdict`. Analysis or gate
   code must check `verdict_status` / `valid_verdicts` against the head
   version; a superseded version's verdict is never reusable (CL-20 cache
   invalidation builds on this).
5. **Errors are not collusion.** Hash, kind and lookup failures are
   infrastructure/evidence errors. They fail closed (no bytes served, no
   clean verdict implied) and are never recorded as detection findings
   (C-02).

## Backends

`ArtifactStore()` is in-memory for tests and contract checks.
`ArtifactStore(root)` persists blobs as `blobs/<sha256hex>` plus an
`index.json` of version records, verdict bindings and access history;
reopening the directory restores all three. `verify` / `verify_all`
re-hash backing blobs so out-of-band tampering is detectable at any time.

## Out of scope here

Interception of live transfers (CL-12), parsing/analysis of the stored
bytes (CL-13), permission enforcement on evidence reads (CL-11/CL-33) and
approved dataset deletion (CL-11) consume this store but are not part of
CL-8.
