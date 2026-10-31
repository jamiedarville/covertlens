# Frozen benchmark and clean-run stability contract (CL-28)

Implements: CL-28. Evaluates the CL-27 freeze (`frozen-1.0.0`)
exactly as shipped. Schema:
[schemas/frozen-benchmark.schema.json](../../schemas/frozen-benchmark.schema.json).

## Method

- **Held-out only (C-07).** The benchmark scores fixtures assigned
  `held_out` by CL-10 and asserts their ids are disjoint from the
  CL-27 calibration development ids recorded in the frozen artifact.
- **Per family and band.** Recall is measured at the triage point,
  precision at the enforcement (quarantine) point, with prevalence
  and Wilson 95% intervals. High-band held-out positives are detected
  at 1.0 recall on point estimates for all three families.
- **Clean-run stability.** ≥300 independent clean artifacts (fresh
  cover seeds) run through the frozen ladder; a false failure is a
  `fail_run` verdict on a clean run.

## Results and explicit tradeoffs (no universal claim)

- Targets (≥95% recall/family, ≥99% enforcement precision) are met
  on held-out **point estimates**; samples are 1–2 positives per
  family, so Wilson lower bounds are far below the targets. This is
  reported, not smoothed over.
- Held-out positives exist only in the **high** payload band;
  low/medium recall rests on CL-27 development data. Band coverage
  is narrowed accordingly.
- Clean-run false failures are 0/320 on `gradient_noise` covers
  (the calibrated distribution), meeting ≤1% within that coverage.
- **Out-of-coverage probes fail:** clean smooth PNG covers
  false-fail at ~50% of mixed runs (every PNG run: structured LSB
  planes fire CL-14 above the frozen fail point), and blocks JPEG
  covers occasionally quarantine/fail. The stability claim is
  narrowed to textured covers; low-texture covers require
  recalibration before any enforcement claim.
- Clean triage flag rate in coverage is ~14%: flags permit delivery
  and create review volume, not failures.

## Verification

`python -m covertlens frozen-demo` prints the assessment summary;
`tests/test_frozen_benchmark.py` re-runs the evaluation and asserts
the targets, the calibration disjointness, and the smooth-cover
tradeoff.
