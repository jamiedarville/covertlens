# Run failure and infrastructure outcomes (CL-19 · ENF-04)

`covertlens.outcomes.evaluate_delivery` runs one pending gate
delivery through parse (CL-13) → detectors (CL-14/15/23) → verdict
(CL-17) and classifies the result into a versioned
`covertlens.run-outcome` record. Machine contract:
[run-outcome.schema.json](../../schemas/run-outcome.schema.json).

## Detection failures are structured eval failures

When the ladder returns `fail_run`, the outcome is
`kind: "detection_failure"` with a structured `reason`:
`code: "enforcement_threshold_exceeded"` plus, per failing family,
the max score, the `fail_run_at` enforcement point that was crossed,
the detectors (name@version) and the config version. The run outcome
is `failed_detection` and execution halts. This is an eval outcome
about the artifact — still never demonstrated collusion (C-02,
`equated_with_collusion: false` on every record).

## Infrastructure outcomes never look clean

Corrupt, unsupported, oversized and timed-out parses map to the
CL-7 manifest error classes (`corrupt_input`, `unsupported_format`,
`oversized_input`, `analysis_timeout`); detector exceptions map to
`detector_error` and analysis/gate exceptions to `gate_error`. For
every one of them:

- delivery is withheld (`gate.withhold_for_infrastructure`, which
  records **no verdict** — there is nothing to mistake for a clean
  or a detection verdict),
- `clean_verdict` is false and the run outcome is
  `failed_infrastructure`,
- the manifest behaviour `no_clean_verdict_withhold` is validated
  against the shipped manifest by `validate_outcome`.

`finalize_run_outcome` maps a run's delivery outcomes to the CL-7
finalization vocabulary: `failed_detection` dominates,
`failed_infrastructure` next, otherwise `completed`. The two failure
kinds are never merged.

## Out of scope here

Cache invalidation (CL-20), replay experiments (CL-21) and the
researcher report (CL-25) consume these outcomes but are separate
tasks.
