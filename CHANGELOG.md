# Changelog

All notable changes to CovertLens, keyed by delivery task (CL
number). Each entry corresponds to one merged pull request; the
deliverables ledger in [README.md](README.md) maps every entry to
its acceptance criteria, code, contract doc, schema, and tests.

## Unreleased

- **CL-62** — Add a genuinely adaptive attacker: a score-oracle loop binary-searches the largest payload under each frozen operating point for LSB, DCT, and geometric families, with matched clean controls, computed `confounded` flags, recorded query budgets, and an achieved-payload-vs-operating-point figure, separate from the frozen benchmark.
- **CL-63** — Consolidate shared helpers into `covertlens._stats`, `._png`, and `._validation` (no private cross-module imports remain), freeze `events.Event`, define `_now` and the pilot adjudications once, share one JSON canonicaliser between pinning and the audit log, move magic numbers into versioned configs, and single-load/join in `report` and `handoff`. No behaviour change.
- **CL-64** — Add the harness adapter: `GateClient` over HTTP (`intercept`/`attempt`/`access`, raising `PendingDeliveryError`/`WithheldError`) and a 50-line example harness moving one permitted and one withheld delivery between stub agents.
- **CL-65** — Close operations runbook gaps: `COVERTLENS_FROZEN_CONFIG` selects the frozen config, `make refreeze` recalibrates/bumps/regenerates the scorecard, the scorecard records the campaign `pin_hash`, `docs/campaign-log.md` defines the announcement convention, and runbook sections cover artefact regeneration, limit configuration, and `validate_handoff` failures.

- **CL-78** (section 1, security) — Close the public reviewer-image leak: `reviewer-image` takes its actor from the demo role and needs `original.read`, so a request with no role is denied (the test that asserted the leak now asserts the denial). R-08 attempts record actor and authorization, and `unauthorized_served` counts R-08 serves without an authorized actor. Gate verdicts need `verdict.override`; audit and trace need `trace.read`. `X-Demo-Role` is honoured only with `COVERTLENS_DEMO_ROLES=on` (set in the Docker image and compose file); otherwise every request is a viewer. JSON endpoints reject non-JSON bodies (415), unsafe cross-site `/api` requests are blocked, responses add `frame-ancestors 'none'`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`, the CSP allows `blob:` images so the reviewer panes render, `/docs` gets a Swagger CSP with a hash-pinned inline script (ReDoc removed), and the export filename is header-safe. The Live Gate, Trace and Reviewer pages share a demo-role picker.
- **CL-61** — Add stronger pixel detectors: `lsb-sample-pairs` (sample-pair LSB-agreement randomness, gated where adjacent-pair correlation is absent) alongside `lsb-pov-chisquare`, and `dct-calibrated-histogram` (neighbor-calibrated histogram total-variation, gated on uncorrelated/subsampled blocks) alongside `dct-coefficient-pov-chisquare`; a smooth-field +/-1 matching fixture suite shows the gain (spatial ROC-AUC 0.597 vs PoV 0.499, DCT 0.833 vs 0.715, bootstrap intervals reported, both detectors individually visible in every benchmark row and in `analyze_all_bytes`). Frozen-benchmark scoring and calibration stay pinned by detector name to the originally calibrated detectors, so the frozen evaluation is unchanged.
- **CL-60** — Add the Trace explorer page: per-run join records with content hashes, verdict references and parse/next-action links or explicit missing statuses with reasons, episode context, repeated weak signals per sender (triage aid only), and recipient actions with candidate input artifacts under `causation_claimed: false`.
- **CL-59** — Add the Reviewer page with demo roles: `viewer`/`researcher`/`reviewer` toggles map to CL-11 principals (clearly labelled demo roles, viewer permissionless), quarantined originals with reviewer-only candidate decodes (other roles denied and audited), the five CL-25 dispositions, sealed review-package download and live audit-chain verification, persisted beside the gate state.
- **CL-58** — Add the live Muse Spark agents covert-channel experiment: Spark sender/receiver via the Meta Model API with deterministic encoder tools, the gate and frozen ladder between them, refusal/no-attempt outcomes scored separately, per-trial model provenance (missing model ID excluded), Wilson-interval recovery and clean-control withholding rates, reported separately from the frozen benchmark. Live trials need `MODEL_API_KEY`; CI covers the harness with an offline stub client.
- **CL-55** — Add Benchmarks and Scorecard pages with CLI-identical caches, ROC/band/Wilson views, geometric rows, ablation/latency/robustness charts and provenance. Robustness remains separate from frozen results.
- **CL-56** — Derive report conclusions and release assessment from evidence, reject unsupported release decisions, propagate audit programming errors, read handoff decisions from the scorecard, and fix default score-cache lookup without guessing between configurations.
- **CL-57** — Bound JPEG component/table parsing, honour component Huffman selectors, parse baseline subsampling and run 2,000 deterministic malformed-image cases in CI. Optional NumPy acceleration now covers PNG filters, coefficient histograms, JPEG reconstruction and segmentation; reuse parsed JPEG coefficients. CL-29 large-JPEG fast-path P95 1.6631 s meets 2 s, with exact reference findings/decision parity.

- **CL-54** — Freeze four-family `frozen-1.1.0` thresholds from development-only data; reserve geometric enforcement for supported undeclared structure, publish lineage-held-out subfamily/chart rates with Wilson intervals, and derive vector clearance from the verdict ladder. Geometric run failure remains reserved pending severity calibration. Fixture PNGs are now written with stored deflate blocks so fixture IDs and pinned dataset hashes are identical under classic zlib and zlib-ng (CI failed on a zlib-ng runner); thresholds and measured results are unchanged.

- **CL-53** — Persist gate state in SQLite under the store root (deliveries, access attempts, trace events; store access history out of `index.json`, derivatives persisted), compute `unauthorized_served` from recorded attempts, and add the Live Gate page (`/gate` + `/api/gate/*` with SSE timeline; recipient pane never renders withheld bytes).
- **CL-52** — Segmenter 1.1.0 handles background colour variation with recorded RGB tolerances, gradient-aware border flooding and 3×3 cleanup; PNG/JPEG pixel decoders, explicit JPEG fidelity limitations, five licensed real-image fixtures, independent codec references and JPEG web-overlay regression coverage. Manifest 1.2.0 declares JPEG geometry; integrated analysis retains the CL-13 parser subset.
- **CL-50** — Add lint, type and schema checks to CI and split the CLI (ruff + mypy at 0, argparse CLI over `covertlens/demos.py`, schema-validation tests, `slow` latency marker).
- **CL-51** — Generate / red-team page (`/generate` + `POST /api/generate` with `source: red_team` provenance; fixes an Analyze crash on failed-segmentation reports found through it).

## 0.1.0 — 2026-11-01

Initial public release: the four-family gate, frozen benchmarks,
seeded pilot, release scorecard (`release_with_limitations`),
geometric family, web service, and Analyze web app.

- **CL-7** — Harness events, allowed-channel manifest, route inventory.
- **CL-8** — Preserve immutable originals and dataset-lifetime evidence.
- **CL-9** — Build reproducible LSB and DCT paired fixtures.
- **CL-10** — Implement independent recovery scoring and leakage-safe splits.
- **CL-11** — Configure runtime, evidence permissions and audit logging.
- **CL-12** — Implement artifact-store interception and pending delivery.
- **CL-13** — Implement bounded PNG/JPEG parsing and analysis result schema.
- **CL-14** — Implement and benchmark the LSB spatial detector.
- **CL-15** — Implement and benchmark the JPEG DCT detector.
- **CL-16** — Join artifact findings to ordered recipient trace events.
- **CL-17** — Implement versioned verdict ladder and threshold configuration.
- **CL-18** — Enforce quarantine across every artifact access path.
- **CL-19** — Implement run failure and explicit infrastructure outcomes.
- **CL-20** — Verify gate races, retries and verdict-cache invalidation.
- **CL-21** — Build delivered-versus-withheld replay experiments.
- **CL-22** — Add metadata fixtures and benign channel controls.
- **CL-23** — Implement metadata-channel scoring and integrate all families.
- **CL-24** — Implement within-run episode context and sequence detection.
- **CL-25** — Build researcher run report and triage workflow.
- **CL-26** — Implement pinned replay and reproducibility checks.
- **CL-27** — Calibrate and freeze research/enforcement thresholds.
- **CL-28** — Frozen benchmark and clean-run stability.
- **CL-29** — Latency, resource limits and gate reliability.
- **CL-30** — Seeded live-trace pilot and researcher adjudication.
- **CL-31** — Detection ablations and prevention effectiveness.
- **CL-32** — Artifact route and trace coverage audit.
- **CL-33** — Review exports and evidence access verification.
- **CL-34** — Adaptive and unseen-configuration evaluation.
- **CL-35** — MVP release scorecard and owner decision.
- **CL-36** — Operations, rollback and researcher handoff.
- **CL-38** — Geometric paired fixtures and benign negatives.
- **CL-39** — Segment repeated elements and extract attribute sequences.
- **CL-40** — Quantization and structure tests for attribute sequences.
- **CL-41** — Vector source parsing with rendered-version verdict binding.
- **CL-42** — Benign controls, subfamily coverage and geometric benchmark.
- **CL-43** — Grid discovery for the geometric detector (Rayleigh + permutation null).
- **CL-44** — Integrate geometric as the fourth channel family.
- **CL-45** — Scene context as a geometric detector input.
- **CL-46** — Structure test v2, structured fixtures, reviewer-only candidate decodes.
- **CL-47** — Web service and Docker image.
- **CL-48** — Analyze page with the geometric overlay.
- **CL-49** — Fix framing, README and repository hygiene; MIT licence, citation file, this changelog, `v0.1.0` tag.

No CL-37 shipped; numbering follows the delivery-task sequence.
