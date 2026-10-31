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

## Owner decision

**`release_with_limitations`** — recorded by the MVP release owner
in the scorecard artifact and the CL-35 Jira comment.

- Limitations: seven items in `decision.limitations` (coverage
  bands/densities, low-texture covers, JPEG latency envelope,
  adaptive evasion incl. allowed-keyword metadata, tiny held-out
  n, R-06 procedural derivatives, context-as-triage-only).
- Target revisions: four items in `decision.target_revisions`,
  each with the measured reason (clean-run scope, latency
  envelope, recall scope, metadata keyword policy).
- An unqualified `release` is structurally barred while
  limitations are unresolved (`validate_scorecard`).

## Verification

`python -m covertlens scorecard-demo` prints the decision summary;
`tests/test_scorecard.py` rebuilds the scorecard and asserts all
sections, the decision record, and that the published artifact
matches (latency timings excepted — machine-volatile).
