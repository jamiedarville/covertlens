# CovertLens

Inline steganalysis / covert-channel gate for the Meta AI internal eval
harness. Agents may not encode task-relevant information in image pixels
or metadata outside the allowed channel; every inter-agent image is
intercepted at the artifact store, scored on its original bytes, and
subject to a verdict ladder before any recipient access.

Project source of truth: Jira project **CL** (Covert Lens) and
[REQUIREMENTS.md](REQUIREMENTS.md). This repository currently contains
the **CL-7 foundation contracts** and the **CL-8 immutable originals
store** that every later task builds on.

## CL-7 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Manifest specifies allowed channels, owner, detector mode, thresholds and error behaviour | [config/allowed-channel-manifest.json](config/allowed-channel-manifest.json) · [docs/contracts/allowed-channel-manifest.md](docs/contracts/allowed-channel-manifest.md) · [schemas/allowed-channel-manifest.schema.json](schemas/allowed-channel-manifest.schema.json) |
| Creation, attempted-delivery, access/parse, action and run-finalization events have stable IDs | `covertlens.events` · `covertlens.ids` · [docs/contracts/harness-events.md](docs/contracts/harness-events.md) · [schemas/harness-events.schema.json](schemas/harness-events.schema.json) |
| Every file-reference and tool-output image route is inventoried | `covertlens.routes` · [docs/contracts/route-inventory.md](docs/contracts/route-inventory.md) |

## CL-8 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Creation and stored byte hashes match | `covertlens.store.ArtifactStore` (content-addressed, hash-checked reads) · [docs/contracts/immutable-originals.md](docs/contracts/immutable-originals.md) · [schemas/artifact-store.schema.json](schemas/artifact-store.schema.json) |
| Changed bytes create a new immutable version and invalidate prior verdicts | Append-only version chain per `artifact_id`; verdicts bind to one exact version and superseded verdicts report `invalidated` |
| Originals, lineage and access history follow dataset-lifetime retention | No delete/overwrite API; frozen records; audited `AccessRecord` history; `retention_policy: dataset_lifetime` |

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m covertlens validate-manifest   # manifest + route inventory checks
python -m covertlens list-events
python -m covertlens list-routes
python -m covertlens store-demo          # CL-8 immutable-store round trip
pytest
```

## Layout

- `covertlens/` — manifest loader/validator, event contracts, route registry, ID helpers, immutable originals store, CLI
- `config/` — the versioned allowed-channel manifest (owner: Agent Evaluation / AI Safety)
- `schemas/` — JSON Schemas for cross-language consumers
- `docs/contracts/` — human-readable contract documents
- `tests/` — acceptance tests, one file per CL-7 criterion

## Working agreements

- Jira (project CL) is the source of truth; see
  [REQUIREMENTS.md](REQUIREMENTS.md) §7 for the working protocol.
- Scope is eval-generated PNG/JPEG only. Consumer uploads/transports are
  out of scope. Thresholds freeze in CL-27; until then the manifest
  carries explicit unfrozen placeholders, never invented numbers.
