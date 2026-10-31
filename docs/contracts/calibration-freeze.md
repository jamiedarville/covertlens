# Calibration and threshold freeze contract (CL-27)

Implements: CL-27. Owners: detection research (thresholds),
evaluation (acceptance targets). Status: `frozen-1.0.0` in
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
