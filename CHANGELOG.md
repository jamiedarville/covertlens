# Changelog

All notable changes to CovertLens, keyed by delivery task (CL
number). Each entry corresponds to one merged pull request; the
deliverables ledger in [README.md](README.md) maps every entry to
its acceptance criteria, code, contract doc, schema, and tests.

## Unreleased

- **CL-54** — Freeze four-family `frozen-1.1.0` thresholds from development-only data; reserve geometric enforcement for supported undeclared structure, publish lineage-held-out subfamily/chart rates with Wilson intervals, and derive vector clearance from the verdict ladder. Geometric run failure remains reserved pending severity calibration.

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
