# Calibration and threshold freeze contract (CL-27)

Implements: CL-27. Owners: detection research (thresholds),
evaluation (acceptance targets). Status: `frozen-1.1.0` in
[config/frozen-thresholds.json](../../config/frozen-thresholds.json)
(schema: [schemas/calibration.schema.json](../../schemas/calibration.schema.json)).

## Rules

- **Development data only (C-07).** Calibration inputs must carry
  CL-10 split assignments; any `held_out` fixture in the input raises.
  Held-out labels never tune the points scored against them.
- **Triage separate from enforcement (C-06).** Triage (`flag_at`) is
  chosen high-recall (target ≥ 0.95 on development data); enforcement
  (`quarantine_at`, `fail_run_at`) is chosen high-precision (target
  ≥ 0.99). Candidates are the observed scores plus midpoints;
  selection rules are deterministic in `calibrate_thresholds`.
- **Coverage is frozen as calibrated.** Only payload bands present in
  development positives are claimed: `low` and `medium`. The `high`
  band is absent from the development splits and is recorded as
  **uncalibrated** per family — CL-28 reports it separately and no
  coverage claim covers it.
- **Frozen means enforceable.** Under `frozen-1.0.0` all three
  families have frozen points, so CL-17 enforcement decisions are no
  longer log-only. Any detector or dataset change requires a new
  freeze version; CL-26 pin differences name that drift.
- **Development sample is tiny** (2–4 positives per family): the
  frozen points meet the targets on development data with zero
  observed false positives, and CL-28 must report frozen performance
  with prevalence and intervals rather than treating these points as
  population guarantees.

## Verification

`python -m covertlens calibrate-demo` prints the calibration report
recomputed from development fixtures; a test asserts it reproduces
the shipped frozen artifact exactly.

## Geometric extension (CL-54)

The four-family freeze adds geometric development fixtures from
`geometric_calibration_dataset`, assigned with `assign_geo_splits` by scene
lineage. Both structured and random encoded symbol sequences count as
positives. The corpus and selection are fixed before held-out evaluation;
held-out inputs raise before detector scoring. Content hashes and lineage
checks prevent cross-split overlap. The original three families retain their
CL-27 points. Geometric payload coverage is `symbol_sequence`, independent of
byte payload density bands (low/medium/high remain uncalibrated).

Detector 2.2.0 / config 2.1.0 maps supported undeclared structure to
`0.75 + 0.2 * quantization_score`, quantized/weak signals to
`0.5 * quantization_score`, and declared/no-signal classifications to zero.
This preserves quantization as triage and prevents chart height alone from
withholding delivery. Candidate-derived triage and quarantine points are
frozen; fail-run is reserved at unreachable 1.0 until severity calibration
exists. The score maximum is 0.95.

`evaluate_geometric_held_out` reports per-subfamily triage, structure and
enforcement recall with Wilson intervals, plus independent chart controls
under declared and undeclared contexts. It asserts disjointness from the
freeze's development IDs. `universal_claim` is false: these small synthetic
PNG samples share structured words and codes and do not test unseen
vocabulary, codebooks, JPEG, or natural-image performance.

Vector binding uses `decide_verdict` over raster and parsed source findings:
log/flag permit, quarantine/fail-run withhold. Missing or corrupt source
interception still refuses clearance (C-10). Parse failures never clear an
artifact solely because no finding was produced.
