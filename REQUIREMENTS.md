# CovertLens (CL) — Working Requirements

Derived from a review of the Jira project **Covert Lens (CL)** on 2026-10-28: 6 epics (CL-1…CL-6), 30 tasks
(CL-7…CL-36), 6 planned sprints, board “CL board”. Jira is the source of
truth; this document is my working interpretation, with every requirement
traced to its Jira issue(s).

Source PRD referenced by all issues: **CovertLens PRD v0.2 — October 27,
2026** (FR-01…FR-13, §§10–13). Owner: Agent Evaluation / AI Safety team.

Addendum §8 (2026-10-28, proposed — not yet traced to a Jira issue)
adds a fourth channel family, geometric/semantic encoding. It does not
change the Jira-traced requirements in §2 unless explicitly noted.

## 1. Product summary

CovertLens is an inline steganalysis / covert-channel gate for the Meta AI
internal eval harness. Agents may not encode task-relevant information in
image pixels or metadata outside an allowed channel. Every inter-agent
image is intercepted at the artifact store, scored on its original bytes
across three pixel/metadata channel families (spatial LSB, JPEG DCT,
metadata), plus the proposed geometric/semantic family in §8, and
subject to a verdict ladder — log → flag → quarantine → run failure —
before any recipient access. Findings join ordered run-trace events so
researchers can triage repeated weak signals; frozen synthetic benchmarks
plus a seeded live-trace pilot decide the MVP release.

Scope: eval-generated PNG/JPEG artifacts only. Consumer uploads and
transports are explicitly excluded. Proposed §8 extension: where a
vector source for a generated image is available in the harness, it is
an additional interception route; the rendered image remains the
artifact delivered and scored.

## 2. Requirements catalog

### EV — Harness integration and immutable evidence (Epic CL-1)

- **EV-01** Harness contracts: document all image routes (file references,
  tool outputs) and define creation, attempted-delivery, access/parse,
  action, and run-finalization events with stable IDs. (`CL-7`)
- **EV-02** Allowed-channel manifest: codify allowed channels, owner,
  detector mode, thresholds, and error behavior. (`CL-7`)
- **EV-03** Immutable originals: store exact creation bytes with lineage
  before any preview/analysis transform; creation and stored hashes must
  match. (`CL-8`)
- **EV-04** Versioning: changed bytes create a new immutable version and
  invalidate prior verdicts. (`CL-8`)
- **EV-05** Retention: originals, lineage, and access history follow
  dataset-lifetime retention. (`CL-8`)
- **EV-06** Interception gate: a single authoritative hook; every
  inventoried image path reaches the gate before recipient access, emitting
  stable run, episode, sender, recipient, and artifact version/hash.
  (`CL-12`)
- **EV-07** Idempotency: repeated references and retries are handled
  idempotently. (`CL-12`)
- **EV-08** Coverage audit: end-to-end creation/hash/gate/access checks on
  every inventoried route, with explicit reasons for missing links and a
  final gap report. (`CL-32`)

### DT — Synthetic datasets and independent ground truth (Epic CL-2)

- **DT-01** Paired fixtures: reproducible clean/encoded LSB and DCT pairs
  with verified payloads and declared size units; generator/encoder
  versions, configs, and seeds recorded. (`CL-9`)
- **DT-02** Negatives: benign edits and generator variation included as
  negatives. (`CL-9`)
- **DT-03** Leakage-safe splits: each original and all derivatives stay in
  one split; held-out seeds, tasks, agents, and encoder configs recorded.
  (`CL-10`)
- **DT-04** Independent scoring: agents and detectors cannot access
  held-out labels; independent recovery checks pass. (`CL-10`)
- **DT-05** Replay experiments: matched/randomized delivered-vs-withheld
  trials with pinned conditions, recording stochastic variation, recovery,
  and legitimate task outcomes separately. (`CL-21`)
- **DT-06** Metadata corpus: known metadata payloads, clean matched
  controls, allowed task-metadata exceptions; lineage, units, and split
  rules matching the initial dataset. (`CL-22`)
- **DT-07** Geometric corpus (proposed, §8): clean/encoded paired
  fixtures for geometric/semantic encoding, with benign negatives
  (legitimate charts, unencoded scenes, benign edits) and generator
  variation; lineage, units, and split rules matching the initial
  dataset. (Proposed — not yet in Jira)

### DET — Channel detection (Epic CL-3)

- **DET-01** Bounded parsing: PNG/JPEG parsed on original bytes — no resize
  or recompression before native analysis; corrupt, unsupported, oversized,
  and timeout cases yield explicit results. (`CL-13`)
- **DET-02** Result schema: worker memory/runtime limits plus a
  channel-finding/version schema, all tested. (`CL-13`)
- **DET-03** LSB detector: versioned spatial scores with coverage;
  clean/encoded performance broken down by payload band; threshold-free
  precision/recall with uncertainty. (`CL-14`)
- **DET-04** DCT detector: coefficient-domain analysis of original JPEGs;
  scores, configuration, and limitations recorded; false positives and
  recall by payload band on paired tests. (`CL-15`)
- **DET-05** Metadata scoring: metadata evidence distinguished from benign
  controls; all three families individually visible, run through pinned
  threshold configurations. (`CL-23`)

### GEO — Geometric / semantic encoding

This family covers messages carried not in low-level pixel noise or
metadata, but in the visible geometry and attributes of a generated
image: the height, position, size, gap, angle, colour code, or lit/dark
state of repeated visual elements, read in order. A human viewer may
see only an ordinary scene; the sequence of attributes may still
carry a structured message.

Implementation status: **implemented** as the fourth channel
family (manifest 1.1.0) by CL-38 through CL-44 — fixtures,
segmentation, quantization/structure tests, vector binding,
benign-control benchmark, and gate integration. Thresholds
remain unfrozen placeholders; the family is log-only until a
dedicated freeze.

- **GEO-01** Repeated-object segmentation: segment repeated,
  similarly shaped visual elements in a generated image, in reading
  order, and extract a numeric attribute sequence per element
  (height, vertical position, width, gap, angle/tilt, colour code,
  lit/dark state, or equivalent), with segmentation method,
  tolerances, and failure modes recorded. (`CL-39`)
- **GEO-02** Quantization test: test whether attribute values snap
  to a small, regular grid or discrete set with near-zero residual,
  versus continuous natural variation; report grid step, residual,
  and count. A bare "pattern detected" verdict without these numbers
  is not acceptable. (`CL-40`, grid discovery `CL-43`)
- **GEO-03** Language/structure test: only where a quantized
  sequence maps through a simple, declared code (alphabet position,
  timing ratios, byte patterns, or equivalent) to a structured
  sequence (words, codes, grammatical text) may it be scored as a
  candidate encoding. A quantized sequence alone, without structure,
  is a weak signal for triage only. (`CL-40`)
- **GEO-04** Vector source: where a vector source is available,
  parse object attributes directly from the source, with lineage
  linking the source version to the rendered version; the verdict
  binds to the rendered version actually delivered. Where only a
  raster is available, segment on original raster bytes; renderer,
  resize, and recompression effects are recorded as limitations,
  and no resize or recompression is applied before analysis.
  (`CL-41`)
- **GEO-05** Benign controls and legitimate encoding: height, size,
  and similar attributes are legitimate in data visualizations,
  charts, diagrams, and ordinary scenes. The detector must
  distinguish by context (is the image supposed to be a chart or
  diagram?), by the quantization and structure tests, and by
  comparison to benign controls (benign generated scenes, skylines,
  charts, abstract art). Height or size alone never triggers
  enforcement. (`CL-42`, context input `CL-45`)
- **GEO-06** Family coverage, not height-only: coverage must
  include, at minimum, height/position, gap/timing, lit/dark and
  colour-code sequences, and angle/tilt, and must report
  per-subfamily results separately. A detector tuned only to one
  subfamily must not claim general geometric coverage. (`CL-42`)
- **GEO-07** Geometric fixtures and benchmark: build clean/encoded
  paired fixtures for geometric encoding analogous to CL-9: the
  same scene, with and without an encoded attribute sequence,
  verified by independent re-measurement; include benign negatives
  and generator variation; record generator, encoder, seeds,
  configs, and declared payload units; keep scorer ground truth
  separate, with leakage-safe splits per DT-03/DT-04. (`CL-38`)

### ENF — Inline verdicts, quarantine, run failure (Epic CL-4)

- **ENF-01** Verdict ladder: log and flag permit delivery; quarantine
  withholds; fail halts execution/delivery. Triage and enforcement
  operating points configured separately. (`CL-17`)
- **ENF-02** No lookahead: pre-delivery decisions cannot use future
  recipient actions. (`CL-17`)
- **ENF-03** Total quarantine: direct references, cached links, and tool
  outputs enforce the same gate; no access before verdict under concurrent
  attempts; quarantined originals visible only to authorized reviewers.
  (`CL-18`)
- **ENF-04** Explicit outcomes: detection thresholds emit structured
  eval-failure reasons; parse/timeout/unsupported inputs obey the manifest
  without a clean verdict; enforcement errors withhold delivery and record
  an infrastructure outcome. (`CL-19`)
- **ENF-05** Gate integrity: concurrency/retry/alternate-reference tests
  show zero unauthorized byte access; byte, detector, or config changes
  invalidate caches; run-context changes recompute contextual verdicts
  while allowing safe image-score reuse. (`CL-20`)

### REV — Trace correlation and researcher review (Epic CL-5)

- **REV-01** Trace join: every attempted delivery carries an original hash
  and verdict reference; delivered artifacts link to parse/next action or
  an explicit missing status; multiple candidate inputs stay visible
  without claiming causation. (`CL-16`)
- **REV-02** Episode context: identities, prior artifacts, and actions
  persist across episodes within one run; context never joins unrelated
  runs and gates only on available evidence. (`CL-24`)
- **REV-03** Sequence benchmarks: image-only, context-only, and combined
  outcomes compared. (`CL-24`, `CL-31`)
- **REV-04** Researcher report: originals, component findings, prior
  context, action timeline; dispositions benign / unresolved / suspected /
  demonstrated-transfer / policy-supported; heatmaps labeled as evidence
  aids, never decoded messages. (`CL-25`)
- **REV-05** Live pilot: seeded attempts plus clean controls in log/flag
  and enforcement runs; unseeded traces independently reviewed, uncertain
  cases stay unresolved; disagreements, volume, and weak-signal findings
  reported. (`CL-30`)
- **REV-06** Review exports: findings, versions, hashes, policy,
  dispositions; byte reads and exports audited; permission tests block
  unauthorized evidence access. (`CL-33`)

### OP — Evaluation, deployment, release (Epic CL-6)

- **OP-01** Runtime: internal execution with classification-aware evidence
  access; dataset/project permissions protect originals, traces, payloads,
  exports; reads, config changes, overrides audited; retirement policy
  preserves reproducibility until approved deletion. (`CL-11`)
- **OP-02** Reproducibility: dataset, detector, config, thresholds, seeds
  pinned; reruns reproduce verdicts or meet documented stochastic bounds;
  exports carry hashes, trace references, versions, decisions. (`CL-26`)
- **OP-03** Frozen thresholds: separate high-recall triage and
  high-precision enforcement points; owners freeze coverage/payload ranges,
  thresholds, acceptance targets; calibration uses no held-out test
  labels. (`CL-27`)
- **OP-04** Benchmark gates: run frozen synthetic benchmark and clean-run
  stability tests against §3 targets. (`CL-28`)
- **OP-05** Performance gates: latency, resource limits, gate reliability
  under documented pilot workload against §3 targets. (`CL-29`)
- **OP-06** Robustness: adaptive and unseen-configuration results reported
  separately from the frozen benchmark; limitations and unresolved results
  documented. (`CL-34`)
- **OP-07** Scorecard: publish per-family results, precision/recall,
  clean-run failure rates, gate correctness, trace completeness,
  repeatability, latency, sequence value; owner records release decision,
  limitations, target revisions. (`CL-35`)
- **OP-08** Handoff: runbook (thresholds, quarantine, infra errors, reruns,
  rollback), retention/access and campaign-change rules, integration and
  review instructions for engineers and researchers. (`CL-36`)

## 3. Quantitative acceptance targets

| Metric | Target | Source |
|---|---|---|
| Per-family recall (LSB, DCT, metadata) | ≥ 95%, prevalence/intervals reported | CL-28 |
| Per-family recall (geometric/semantic, proposed) | ≥ 95%, prevalence/intervals reported, to be frozen per OP-03 — not yet a Jira target | §8 |
| Geometric false claims on benign controls | Report separately; no invented target before calibration | §8 |
| Enforcement precision | ≥ 99% | CL-28 |
| Clean-run false failures | ≤ 1% on ≥ 300 independent clean runs | CL-28 |
| Inline overhead (P95) | ≤ 2 s for ≤ 10 MB / 20 MP images at agreed concurrency | CL-29 |
| Unauthorized byte access (race/retry tests) | zero | CL-20 |
| Missed targets | explicit tradeoff or narrowed coverage, never universal claims | CL-28 |

## 4. Cross-cutting constraints

- **C-01** Original bytes, run traces, and evidence stay internal for the
  dataset lifetime. (All tasks)
- **C-02** A detector threshold or infrastructure error is never equated
  with demonstrated collusion. (All tasks)
- **C-03** Pre-delivery decisions use only available evidence — no future
  recipient actions. (CL-17, CL-24)
- **C-04** Withheld/blocked artifacts are never counted as observed
  successful transfer; blocked runs label recipient parse “not observed”.
  (CL-21, CL-31)
- **C-05** Analysis runs on original bytes; changed bytes invalidate prior
  verdicts. (CL-8, CL-13, CL-20)
- **C-06** Research (high-recall) and enforcement (high-precision)
  operating points stay separate from calibration through release.
  (CL-17, CL-27)
- **C-07** Calibration and frozen benchmarks never touch held-out test
  labels. (CL-27, CL-28)
- **C-08** Consumer uploads and transports are out of scope. (Epic notes)
- **C-09** A geometric score is evidence, never a decoded message.
  Attribute sequences and heatmaps are evidence aids, never decoded
  messages. (Active, §8; extends REV-04; `CL-40`+)
- **C-10** Where a vector source and a rendered raster both exist,
  lineage must link them. A verdict on the rendered version does
  not by itself prove source intent, and a clean raster score does
  not clear a vector source that was not intercepted. (Active, §8; `CL-41`)

## 5. Delivery plan

Six planned two-week sprints, five tasks each. No active sprint; no dates,
estimates, or assignees set yet. All 36 issues are To Do, all Medium
priority.

| Sprint | Goal | Tasks |
|---|---|---|
| CL Sprint 1 (id 47) | Harness contracts and synthetic foundations | CL-7, CL-8, CL-9, CL-10, CL-11 |
| CL Sprint 2 (id 48) | Artifact interception and LSB/DCT baselines | CL-12, CL-13, CL-14, CL-15, CL-16 |
| CL Sprint 3 (id 49) | Inline quarantine and run-failure enforcement | CL-17, CL-18, CL-19, CL-20, CL-21 |
| CL Sprint 4 (id 50) | Metadata, sequence context, researcher reports | CL-22, CL-23, CL-24, CL-25, CL-26 |
| CL Sprint 5 (id 51) | Frozen benchmarks and live eval pilot | CL-27, CL-28, CL-29, CL-30, CL-31 |
| CL Sprint 6 (id 52) | MVP hardening, scorecard, handoff | CL-32, CL-33, CL-34, CL-35, CL-36 |

Dependency analysis (parsed from issue descriptions):

- Single root: **CL-7** (manifest) — everything descends from it.
- No dependency points to a same- or later-numbered task; no sprint hosts
  a task depending on a later sprint. The plan is topologically sound.
- Critical path (14 tasks): CL-7 → CL-9 → CL-10 → CL-14 → CL-17 → CL-18 →
  CL-20 → CL-26 → CL-27 → CL-28 → CL-31 → CL-34 → CL-35 → CL-36. (CL-15
  mirrors CL-14 and is equally constraining in practice.)
- Sprint 1 entry order: CL-7 first, then CL-8 and CL-9 in parallel, then
  CL-10, then CL-11.

## 6. Readiness gaps and open questions

1. Sprint 1 has no start date and no active sprint exists — confirm when
   to start, and whether you want me to start it in Jira.
2. No estimates anywhere (the project has no story-point field in use) —
   confirm whether to estimate during refinement or track by task count.
3. All issues are Medium priority with no assignees — confirm owners, at
   least for the Sprint 1 chain.
4. Tasks cite PRD requirements FR-01…FR-13 and §§10–13, which are not in
   Jira — link the PRD doc if you want requirements traced to it.
5. CL-29’s latency target is marked “proposed” — needs owner agreement
   before Sprint 5.
6. Geometric/semantic encoding (§8) is not in CL-7…CL-36 / PRD v0.2 —
   confirm whether to add new Jira issues, extend an existing
   detection task, or keep it as a proposed addendum; confirm
   whether vector-source interception is in harness scope.

## 7. Jira working protocol

As we work through the sprints I will:

- Move issues through the workflow (To Do → In Progress → Done) as work
  starts and acceptance criteria are met.
- Post progress comments on the active issue(s), including what was
  verified and what remains.
- Keep sprint assignments as planned; flag any task that needs to move
  sprints before moving it.
- Ask before starting/completing sprints or editing issue scope —
  routine status and comment updates I will make directly.

## 8. Addendum — Geometric / semantic encoding (proposed, 2026-10-28)

### 8.1 Threat model

An agent generating an image may carry task-relevant information in
the image's visible structure rather than in pixel noise or metadata.
Examples of the general class, stated without reference to any
specific published case:

- A row of similarly shaped objects (buildings, stars, blades,
  windows, or equivalent) whose heights or vertical positions, read
  left to right, map to letters or codes, with spacing that groups
  them into words.
- Short/long elements and gaps whose timing ratios map to a code
  such as Morse.
- Lit/dark, colour, or other binary/ternary states whose sequence
  maps to byte patterns.
- Angle, tilt, or other object attributes used in the same way.

The resulting image may look ordinary to a human viewer. The
message is not in a single pixel; it is in the sequence of
attributes across repeated elements.

### 8.2 Why hash, LSB, and DCT checks miss this class

- Hash comparison only shows that bytes changed. An image encoded
  at creation hashes cleanly; nothing was edited afterward.
- LSB and DCT scores look for low-level pixel/coefficient noise.
  A geometric encoding can leave those statistics essentially
  clean, because the carrier is the scene geometry itself.
- Metadata scoring looks at file metadata, not at object geometry.

A detector for this class therefore cannot reuse LSB/DCT scores
alone. It needs its own segmentation, attribute, quantization, and
structure tests (GEO-01…GEO-07).

### 8.3 Detection approach

1. Segment repeated, similarly shaped elements and order them by
   reading order.
2. Extract one attribute sequence per element (height, position,
   width, gap, angle, colour code, lit/dark state).
3. Test for quantization: do values snap to a regular grid with
   near-zero residual, and how many elements support that grid?
4. Test for structure: does a simple, declared mapping from those
   values produce words, codes, or grammatical text, rather than
   gibberish?
5. Compare to benign controls of the same scene type, and to
   legitimate data visualizations where the same attributes are
   expected to carry data.
6. Score per subfamily separately. A high score on height alone is
   not a general geometric score, and a weak, unmapped quantization
   signal is triage-only.

Thresholds for this family are unfrozen, following the same rule as
§1 and CL-27: explicit placeholders, never invented numbers.
Triage (high-recall) and enforcement (high-precision) operating
points stay separate, errors fail closed, and a score is never
equated with demonstrated collusion (C-02, C-06, C-09).

### 8.4 Implementation notes for code work

- Add a geometric detector family alongside spatial LSB, JPEG DCT,
  and metadata, with its own versioned scores, configuration, and
  limitations recorded per DET-02/DET-03 style. (Done: `CL-44` —
  manifest 1.1.0, four families in the pipeline, ladder, report,
  export, pin and scorecard.)
- Prefer vector-source parsing where the harness provides it;
  otherwise segment the original raster bytes, and record renderer
  and transform limitations explicitly.
- Ship geometric fixtures alongside the CL-9 fixtures: paired
  clean/encoded scenes, benign negatives, and generator variation,
  with independent re-measurement as the verification step.
- Report geometric results in the scorecard per OP-07, broken
  down by subfamily, with benign-control false-claim rates shown
  separately from encoded recall.
- Do not claim general geometric coverage until at least the
  subfamilies in GEO-06 have paired tests and benign-control
  results.
