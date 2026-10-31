# Pinned replay and reproducibility (CL-26 · OPS-01)

`covertlens.pinning` makes an eval configuration content-addressed
and its outcomes checkable.

## The pin

`build_pin(fixtures, threshold_config, seeds, detector_versions)`
records and hashes:

- **Dataset:** every fixture ID → content hash, folded into one
  `dataset_hash` (sorted, so order cannot hide drift);
- **Detectors:** `name@version` for LSB, DCT and metadata, plus the
  threshold-config version and per-family thresholds status;
- **Seeds:** the caller's seed map (fixture, replay, calibration).

`pin_hash` seals the pin. `pin_differences` rebuilds the pin from
current inputs and names each drifted field; `validate_pin`
recomputes the seal and every hash, so a tampered or stale pin fails
structurally before it fails scientifically.

## Reproducibility

`verify_reproducibility` repeats the integrated pipeline
(`analyze_and_decide`) over the fixtures:

- deterministic scoring must reproduce identical verdicts exactly
  (`exact_reproduction`), across all repetitions;
- a stochastic scorer runs under derived seeds
  (`base_seed + repetition`, recorded) and is judged against the
  documented `agreement_min` bound on stable verdicts — variation is
  bounded and reproducible, never silent.

## Exports

`export_bundle(report, pin)` seals a CL-25 run report for export:
pin and dataset hashes, detector and threshold-config versions,
seeds, trace references (run ID + timeline event IDs), original
hashes (never bytes), and per-delivery verdicts/dispositions, closed
by `bundle_hash`. `validate_export` recomputes the seal, so an
export that no longer matches its pin or contents is rejected.

## Out of scope here

Threshold freezing (CL-27) and the frozen benchmark (CL-28) consume
pins; export access control and audit (CL-33) builds on the bundle.
