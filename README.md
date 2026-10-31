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

## CL-14 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| LSB scores and applicable coverage are versioned | `covertlens.lsb` (`lsb-pov-chisquare` v1.0.0, `LsbConfig` v1.0.0) emits one `spatial_lsb` finding per parsed PNG with samples/pixels/pairs coverage · [docs/contracts/lsb-detector.md](docs/contracts/lsb-detector.md) |
| Clean/encoded test performance is broken down by payload band | `benchmark_lsb` rows and `by_payload_band` (none/low/medium/high) over the CL-9 fixtures · [schemas/lsb-benchmark.schema.json](schemas/lsb-benchmark.schema.json) |
| Threshold-free results include precision/recall and uncertainty | Threshold sweep with Wilson precision/recall intervals plus ROC-AUC and average-precision bootstrap intervals; thresholds stay unfrozen until CL-27 |

## CL-15 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Original JPEG coefficient-domain evidence is analyzed | `covertlens.dct` scores quantized AC coefficients from CL-13 on exact original bytes (no IDCT/recompression) · [docs/contracts/dct-detector.md](docs/contracts/dct-detector.md) |
| DCT scores, configuration and limitations are recorded | `dct-coefficient-pov-chisquare` v1.0.0 findings with `DctConfig` v1.0.0, carrier/block coverage and recorded limitations |
| Paired tests report false positives and recall by payload band | `benchmark_dct` sweep (FP/FPR per threshold) plus per-band recall sweeps · [schemas/dct-benchmark.schema.json](schemas/dct-benchmark.schema.json) |

## CL-16 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Every attempted delivery has an original hash and verdict reference | `covertlens.trace_join.join_trace` per-delivery records with original `content_hash` and verdict reference (missing verdicts flagged, never dropped) · [docs/contracts/trace-join.md](docs/contracts/trace-join.md) · [schemas/trace-join.schema.json](schemas/trace-join.schema.json) |
| Delivered artifacts link to parse/next action or an explicit missing status | Parse/next-action linkage per delivery with explicit `missing` status when absent |
| Multiple candidate input artifacts remain visible without claiming causation | Per-action candidate lists with `causation_claimed: false` throughout |

## CL-17 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Log and flag permit delivery; quarantine withholds; fail halts execution/delivery | `covertlens.verdicts` ladder (`delivery_for_verdict`, `decide_verdict`, `decide_and_record` through the CL-12 gate; `halt_execution` only for `fail_run`) · [docs/contracts/verdict-ladder.md](docs/contracts/verdict-ladder.md) · [schemas/verdict-decision.schema.json](schemas/verdict-decision.schema.json) |
| Triage and enforcement operating points are separately configured | Versioned per-family `ThresholdConfig` from the CL-7 manifest (high-recall triage vs high-precision enforcement); shipped unfrozen, frozen by CL-27 |
| Pre-delivery decisions cannot use future recipient actions | `LookaheadError` on recipient-action or post-cutoff evidence (C-03) |

## CL-18 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Direct references, cached links and tool outputs enforce the same gate | `InterceptionGate.serve_via_route` / cached-link redemption funnel every gated route (R-01…R-07) through one verdict check · [docs/contracts/quarantine-enforcement.md](docs/contracts/quarantine-enforcement.md) |
| No access occurs before verdict under concurrent delivery attempts | One gate lock makes verdict check + serve atomic; `access_attempt_report()` audits every attempt |
| Quarantined originals remain available only to authorized reviewers | `reviewer_access` (R-08 evidence path, audited store read); recipients stay withheld |

## CL-19 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Detection thresholds emit structured eval-failure reasons | `covertlens.outcomes.failure_reason` (family, score, point crossed, detectors, config version) · [docs/contracts/run-outcomes.md](docs/contracts/run-outcomes.md) · [schemas/run-outcome.schema.json](schemas/run-outcome.schema.json) |
| Parsing/timeouts/unsupported inputs obey the manifest without a clean verdict | Manifest error classes with `clean_verdict: false` and withheld delivery |
| Enforcement errors withhold delivery and record an infrastructure outcome | `evaluate_delivery` pipeline + `gate.withhold_for_infrastructure` (no verdict recorded) |

## CL-20 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Concurrency/retry/alternate-reference tests show zero unauthorized byte access | Race/retry/alternate-reference tests over the CL-18 gate with `access_attempt_report` audit |
| Byte, detector or configuration changes invalidate cached results | `covertlens.integrity.AnalysisCache` score keys (hash + detector/config versions) · [docs/contracts/gate-integrity.md](docs/contracts/gate-integrity.md) |
| Run-context changes recompute contextual verdicts while allowing safe image-score reuse | Verdict keys add threshold-config version + context fingerprint; score keys exclude context |

## CL-21 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Matched/randomized trials pin conditions and record stochastic variation | `covertlens.replay.run_replay` matched delivered/withheld pairs, seeded order and per-trial seeds, pinned hashes/versions · [docs/contracts/replay-experiments.md](docs/contracts/replay-experiments.md) · [schemas/replay-experiment.schema.json](schemas/replay-experiment.schema.json) |
| Independent recovery and legitimate task outcomes are collected | Separate recovery and legitimate-task rates per condition and payload band |
| Blocked runs label recipient parse not observed and never claim demonstrated transfer | Withheld trials: `parse_status`/`recovery` `not_observed`, `demonstrated_transfer` always false (C-04) |

## CL-22 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Known metadata payloads and clean matched controls are verified | `covertlens.metadata_fixtures` PNG tEXt / JPEG APP1 payload fixtures with image bytes proven unchanged · [docs/contracts/metadata-fixtures.md](docs/contracts/metadata-fixtures.md) |
| Allowed task metadata exceptions are represented | Benign controls carrying only Title/Description/TaskReference |
| Fixture lineage, payload units and split rules match the initial dataset | CL-9 `Fixture` lineage/units; CL-10 split grouping verified |

## CL-23 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Metadata scores distinguish supported encoding evidence from benign controls | `covertlens.metadata` declared-keyword detector (payload strong, unknown weak, allowed/none benign) · [docs/contracts/metadata-detector.md](docs/contracts/metadata-detector.md) · [schemas/metadata-benchmark.schema.json](schemas/metadata-benchmark.schema.json) |
| LSB, DCT and metadata outputs remain individually visible | `analyze_all_bytes` attaches each applicable family to one result, never blended |
| All three families run through pinned threshold configurations | `analyze_and_decide` through the CL-17 ladder with caller-pinned config version recorded |

## CL-24 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Agent identities, prior artifacts and actions persist across episodes in one run | `covertlens.sequence.build_episode_context` from the CL-16 join · [docs/contracts/episode-sequence.md](docs/contracts/episode-sequence.md) · [schemas/sequence-context.schema.json](schemas/sequence-context.schema.json) |
| Context never joins unrelated runs and uses only available evidence for gating | Multi-run input raises; features count only evidence at/before `through_seq` |
| Sequence benchmarks compare image-only, context-only and combined outcomes | `benchmark_sequences` ROC-AUC for all three scorers |

## CL-25 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Report includes originals, component findings, prior context and action timeline | `covertlens.report.build_run_report` (originals by hash reference, no embedded bytes) · [docs/contracts/researcher-report.md](docs/contracts/researcher-report.md) · [schemas/run-report.schema.json](schemas/run-report.schema.json) |
| Review supports benign, unresolved, suspected, demonstrated-transfer and policy-supported findings | `apply_review` with the five dispositions; `demonstrated_transfer` requires a recorded independent basis |
| Heatmaps/scores are labeled evidence aids rather than decoded messages | `evidence_aid_not_decoded_message` label enforced by validation |

## CL-26 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Dataset, detector, configuration, thresholds and seeds are pinned | `covertlens.pinning.build_pin` content-hashed pin with named drift detection · [docs/contracts/pinned-replay.md](docs/contracts/pinned-replay.md) · [schemas/pin.schema.json](schemas/pin.schema.json) |
| Repeated inputs reproduce verdicts or meet documented stochastic bounds | `verify_reproducibility` (exact deterministic; seeded agreement bounds for stochastic scorers) |
| Report exports carry hashes, trace references, versions and decisions | `export_bundle` hash-sealed CL-25 exports (no raw bytes) |

## CL-27 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Separate high-recall triage and high-precision enforcement settings | `covertlens.calibration.calibrate_thresholds` deterministic per-family candidate selection · [docs/contracts/calibration-freeze.md](docs/contracts/calibration-freeze.md) · [schemas/calibration.schema.json](schemas/calibration.schema.json) |
| Owners freeze coverage/payload ranges, thresholds and acceptance targets | `config/frozen-thresholds.json` (`frozen-1.0.0`, triage recall ≥0.95 / enforcement precision ≥0.99 targets, calibrated bands low+medium, high uncalibrated) |
| Calibration uses no held-out test labels | Held-out fixtures in calibration input raise (C-07); frozen artifact records `held_out_labels_used: false` and the development dataset hash |

## CL-28 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Target ≥95% per-family recall and ≥99% enforcement precision with prevalence/intervals reported | `covertlens.frozen_benchmark.run_frozen_evaluation` held-out-only benchmark (Wilson 95% intervals, per-band recall) · [docs/contracts/frozen-benchmark.md](docs/contracts/frozen-benchmark.md) · [schemas/frozen-benchmark.schema.json](schemas/frozen-benchmark.schema.json) |
| Target ≤1% clean-run false failures using ≥300 independent clean runs | 320 fresh-seed clean runs through the frozen ladder: 0 false failures within claimed coverage |
| Missed targets produce explicit tradeoffs or narrowed coverage rather than universal claims | Report records `universal_claim: false` with tradeoffs: high-band-only held-out positives, tiny-n intervals, smooth/blocks covers excluded from the stability claim (measured false-fail probes), ~14% clean triage flag rate |

## CL-29 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Measure proposed P95 ≤2-second overhead for ≤10 MB/20 MP images at agreed concurrency | `covertlens.latency.run_reliability_report` pilot workload (4 size classes × media, 4 workers) · [docs/contracts/latency-reliability.md](docs/contracts/latency-reliability.md) · [schemas/latency-reliability.schema.json](schemas/latency-reliability.schema.json) |
| Timeout/resource-limit behavior remains explicit and withholds delivery in enforcement mode | `limit_behavior_checks`: timeout/oversize statuses + manifest error classes, infrastructure withhold, no clean verdict, zero bytes served |
| Concurrency and access-leak tests remain clean under the measured workload | `gate_reliability_check`: threaded route/cached-link attempts serve exactly the permitted set, `unauthorized_served: 0` |
| Misses are explicit | JPEG large (≥~1 MP) times out at the 2 s deadline; medium JPEG misses under 4-worker concurrency; 20 MP JPEG not measurable with the pure-Python encoder — claims narrowed per class |

## CL-30 deliverables

| Acceptance criterion | Deliverable |
|---|---|
| Log/flag and enforcement runs include seeded attempts and clean controls | `covertlens.pilot.run_pilot` (CL-26 pinned): 33 seeded traces (15 attempts, 18 controls) run under both the unfrozen log-only config and `frozen-1.0.0` · [docs/contracts/seeded-pilot.md](docs/contracts/seeded-pilot.md) · [schemas/seeded-pilot.schema.json](schemas/seeded-pilot.schema.json) |
| Unseeded traces are independently reviewed and uncertain cases remain unresolved | CL-25 report adjudication over 5 unseeded traces; unreviewed stay `unresolved`, `demonstrated_transfer` requires an independent basis |
| Disagreements, review volume and repeated weak-signal findings are reported | Named per-trace disagreements (7 seeded attempts delivered in enforcement, 0 clean controls withheld, 14 mode verdict changes), review-volume counts, and per-sender repeated weak-signal list (incl. `sender-repeat` ×3) |

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
python -m covertlens lsb-demo            # CL-14 LSB scoring demo
python -m covertlens benchmark-lsb       # CL-14 threshold-free LSB benchmark
python -m covertlens dct-demo            # CL-15 DCT scoring demo
python -m covertlens benchmark-dct       # CL-15 paired DCT benchmark (FP + recall by band)
python -m covertlens trace-demo          # CL-16 trace join demo
python -m covertlens verdict-demo        # CL-17 verdict ladder demo (unfrozen, log-only)
python -m covertlens replay-demo         # CL-21 delivered-vs-withheld replay
python -m covertlens metadata-demo       # CL-23 metadata + integrated pipeline demo
python -m covertlens sequence-demo       # CL-24 sequence benchmark demo
python -m covertlens report-demo         # CL-25 researcher report demo
python -m covertlens pinning-demo        # CL-26 pin + reproducibility demo
python -m covertlens calibrate-demo      # CL-27 frozen threshold points
python -m covertlens frozen-demo         # CL-28 frozen benchmark + clean stability
python -m covertlens latency-demo        # CL-29 latency + reliability report
python -m covertlens pilot-demo          # CL-30 seeded pilot + adjudication
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
