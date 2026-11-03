# Genuinely adaptive attacker contract (CL-62)

Implements: CL-62 (extends CL-34). Schema:
[schemas/adaptive-robustness.schema.json](../../schemas/adaptive-robustness.schema.json).

CL-34's adaptive rows were fixed variants. CL-62 adds the missing
feedback loop: the attacker queries the detector score (the oracle
a real adversary gets from flagged runs) and binary-searches the
largest payload that stays just under each operating point, for
`spatial_lsb`, `jpeg_dct`, and the geometric family (payload =
symbol count on `height_position` scenes).

## Rules

- Every experiment carries matched clean controls (same cover
  seeds, no payload); `confounded` is computed from them — an
  experiment whose controls are withheld makes no detection claim.
- Every detector query is recorded; each (family, point) search is
  capped by `query_budget_per_point`.
- The `figure` block is the achieved-payload-vs-operating-point
  data (family, point, threshold, achieved payload, queries used).
- Results stay separate from the frozen benchmark
  (`separate_from_frozen_benchmark: true`,
  `merged_into_frozen_claim: false`) and are never equated with
  collusion (C-02).

## Verification

`python -m covertlens adaptive-demo` prints the figure points;
`tests/test_adaptive.py` asserts validity, budgets, controls, and
the confounded computation.
