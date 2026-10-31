# Detection ablations and prevention effectiveness contract (CL-31)

Implements: CL-31. Schema:
[schemas/ablations-prevention.schema.json](../../schemas/ablations-prevention.schema.json).
Runs over the CL-30 seeded traces (33) under `frozen-1.0.0`, with
the CL-21 matched replay arms as a cross-check.

## Ablation arms (operating points fixed a priori)

- **image-only:** artifact findings through the frozen enforcement
  points. AUC 0.94; at enforcement: TP 8, FP 0, FN 7, TN 18
  (precision 1.0, recall 0.53 — the low/medium-band limit).
- **context-only:** CL-24 repetition pressure from the sender's
  prior traces only (cutoff-safe, C-03), operating point 0.5.
  AUC 0.43 — worse than chance here because suite senders mix
  attempts and controls; context alone must never withhold.
- **combined:** CL-24 noisy-OR, operating point 0.5. Recall rises
  to 0.87, but AUC falls to 0.47 and FPR to 0.78: prior sender
  scores contaminate later clean traces. Enforcement stays
  image-led; context is a triage aid.

## Prevention effectiveness (delivered vs withheld kept separate)

- Attempts (15): 8 withheld (blocked), 7 delivered — and all 7
  delivered attempts were independently recovered, i.e. the only
  observed successful transfers. **Blocked artifacts counted as
  transfer: 0**, by construction and by assertion (withheld
  recovery is `not_observed`, C-04).
- Clean controls (18): all delivered, legitimate task success
  18/18 — no collateral withholding in this pilot. Recovery and
  legitimate task success are different quantities and are never
  merged: controls have nothing to recover, attempts have no
  legitimate-success claim.
- The CL-21 replay cross-check agrees: withheld arm shows zero
  demonstrated transfers and `not_observed` parses throughout.

## Verification

`python -m covertlens ablation-demo` prints arms + prevention;
`tests/test_ablations.py` asserts the three arms, the image >
context ordering, and the never-count-blocked invariant.
