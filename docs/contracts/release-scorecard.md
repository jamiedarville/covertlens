# MVP release scorecard and owner decision contract (CL-35)

Implements: CL-35. Schema:
[schemas/release-scorecard.schema.json](../../schemas/release-scorecard.schema.json).
Authoritative artifact:
[config/release-scorecard.json](../../config/release-scorecard.json),
built by `covertlens.scorecard.build_scorecard` from the merged
CL-28..CL-34 reports (figures extracted at build time, each
section citing its source schema/doc — never recomputed).

## Published headline results

| Area | Headline | Source |
|---|---|---|
| LSB / DCT / metadata | recall 1.0, precision 1.0 (point estimates) | CL-28 |
| Clean-run failures | 0 / 320 within claimed coverage | CL-28 |
| Latency proposal | met except large JPEG | CL-29 |
| Gate / trace | 6 routes pass, R-06 partial, R-08 exempt | CL-32 |
| Evidence exports | sealed, audited, permission-denied | CL-33 |
| Sequence value | image-led; context is triage only | CL-31 |
| Prevention | blocked counted as transfer: 0 | CL-31 |
| Robustness bounds | adaptive evades enforcement | CL-34 |

Detail that does not fit the table:

- Detection figures are held-out point estimates with wide Wilson
  intervals (1–2 positives/family, high band only); the claim
  scope in the scorecard states this verbatim.
- The latency miss is the large-JPEG class (explicit 2 s
  timeouts); the concurrent medium-JPEG P95 is published in the
  artifact as measured.
- Pilot and adjudication counts (withheld, disagreements,
  unresolved unseeded) are published in the `pilot_adjudication`
  section.

## Computed assessment (CL-56)

The builder computes `targets` and `decision` from section evidence. Failed
safety invariants (gate/trace, exports, prevention or infrastructure handling)
produce `no_release`; unresolved limitations or missed/narrowed targets produce
`release_with_limitations`; only an assessment meeting every target with no
limitations can produce `release`.

The validator recomputes target checks from section values rather than trusting
the published target booleans. It rejects unqualified release with any missed
target or limitation, and rejects `release_with_limitations` without limitations.
Handoff reads the published scorecard's decision instead of asserting its own.

Limitations and target revisions cite the measured source narratives. Volatile
latency figures also change the narratives derived from them; deterministic
source sections must match the published artifact exactly. The scorecard remains
a scoped assessment, not evidence of collusion or a universal detection claim.

Verification: `python -m covertlens scorecard-demo`, `tests/test_scorecard.py`
and `tests/test_report_conclusions.py`. A planted `TypeError` in gate methods
must escape the route, latency, pilot and handoff audits; only the documented
denial exception classes count as successful denial.
