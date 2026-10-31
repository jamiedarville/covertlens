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

## CL-9 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Clean and encoded pairs have verified payloads with declared size units | `covertlens.fixtures` (seeded procedural covers, LSB-PNG and DCT-JPEG embedders, independent decode verification) · [docs/contracts/synthetic-fixtures.md](docs/contracts/synthetic-fixtures.md) · [schemas/fixture-manifest.schema.json](schemas/fixture-manifest.schema.json) |
| Generator and encoder versions, configurations and seeds are recorded | Per-fixture provenance in the JSON fixture manifest; raw payloads recorded by hash only, scorer ground truth kept separate |
| Benign edits and generator variation are included as negatives | Default dataset ships brightness/flip benign edits and alternate-pattern/seed generator variations with zero payload bits |

## CL-10 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Each original and all derivatives remain in one split | `covertlens.splits` (deterministic lineage-grouped assignment + leakage validator) · [docs/contracts/leakage-safe-splits.md](docs/contracts/leakage-safe-splits.md) · [schemas/split-manifest.schema.json](schemas/split-manifest.schema.json) |
| Held-out seeds, tasks, agent and encoder configurations are recorded | Auditable held-out record in `assignments.json` (seeds, patterns, encoder configs; task/agent dimensions recorded when present) |
| Agents/detectors cannot access held-out labels; independent recovery checks pass | Detector export excludes held-out fixtures and all payloads; scorer ground truth requires the scorer role; bit-exact recovery checks over every encoded fixture |

## CL-11 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Dataset/project permissions protect originals, traces, payloads and exports | `covertlens.runtime` deny-by-default, dataset-scoped gateway over the CL-8 store · [config/runtime-policy.json](config/runtime-policy.json) · [docs/contracts/runtime-evidence-access.md](docs/contracts/runtime-evidence-access.md) · [schemas/runtime-policy.schema.json](schemas/runtime-policy.schema.json) |
| Evidence reads, configuration changes and overrides are audited | Append-only hash-chained `AuditLog`; versioned `RuntimeConfig` changes and reasoned verdict overrides recorded |
| Dataset retirement policy preserves reproducibility until approved deletion | Governed request → separate-approver → bundled-deletion lifecycle; reproducibility bundle captured before any bytes are removed |

## CL-12 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| All inventoried image paths reach the gate before recipient access | `covertlens.gate.InterceptionGate` single hook for gated routes R-01…R-07 (R-08 rejected as a delivery route) with coverage reporting · [docs/contracts/interception-gate.md](docs/contracts/interception-gate.md) · [schemas/delivery-record.schema.json](schemas/delivery-record.schema.json) |
| Stable run, episode, sender, recipient and artifact version/hash are emitted | CL-7 events (`artifact.created` → `delivery.attempted` → `gate.verdict` → `artifact.accessed`/`artifact.parsed`) in the per-run trace, deliveries pending until a permitting verdict |
| Repeated references and retries are handled idempotently | Reference resolution cached to one immutable version/creation event; delivery retries reuse the deterministic `delivery_id` |

## CL-13 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| No resize or recompression occurs before native analysis | `covertlens.parsing` parses exact CL-8 original bytes (`transform_applied: false`, original `content_hash` on every result) · [docs/contracts/bounded-parsing.md](docs/contracts/bounded-parsing.md) · [schemas/analysis-result.schema.json](schemas/analysis-result.schema.json) |
| Corrupt, unsupported, oversized and timeout cases have explicit results | One versioned result per input with status `parsed` / `corrupt` / `unsupported_format` / `unsupported_encoding` / `oversized` / `timeout`; failures carry errors and never findings |
| Worker memory/runtime limits and channel finding/version schema are tested | Versioned `ParserLimits` (10 MiB, 20 MP, decompressed and 2 s deadline bounds, checked before unbounded work) plus validated `Finding` schema for CL-14/CL-15/CL-23; PNG rows/pixels and JPEG blocks/coefficients coverage |

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m covertlens validate-manifest   # manifest + route inventory checks
python -m covertlens list-events
python -m covertlens list-routes
python -m covertlens store-demo          # CL-8 immutable-store round trip
python -m covertlens build-fixtures      # CL-9 synthetic paired fixtures
python -m covertlens split-dataset       # CL-10 leakage-safe splits + scoring
python -m covertlens validate-runtime    # CL-11 runtime policy checks
python -m covertlens runtime-demo        # CL-11 permissioned evidence read demo
python -m covertlens gate-demo           # CL-12 interception + pending delivery demo
python -m covertlens parse-demo          # CL-13 bounded parsing demo
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
