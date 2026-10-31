# Artifact route and trace coverage audit contract (CL-32)

Implements: CL-32. Schema:
[schemas/route-trace-audit.schema.json](../../schemas/route-trace-audit.schema.json).
Audits the CL-7 route inventory (R-01..R-08) end to end against
the CL-12 gate, CL-8 store and CL-16 trace join.

## Route results

- **R-01..R-05, R-07 — pass.** Each route is exercised through its
  own access path: creation emits an immutable version, the
  recorded hash equals the exact bytes and store-verifies, pending
  and quarantined deliveries are denied, and a permitted delivery
  serves the exact bytes. R-05 is redeemed through a cached link
  (re-checks the current verdict); R-07 records the parse hand-off.
- **R-08 — exempt, verified.** Reviewer evidence access is not a
  delivery path: authorized reviewers are served with audit,
  non-reviewers are denied, and the recipient stays denied.
- **R-06 — partial (remaining gap).** Withheld originals yield no
  derivative in the audit (derivatives are generated only from
  gate-served bytes), but there is no dedicated gate derivative
  API: `ArtifactStore.register_derivative` remains an ungated
  internal call, so R-06 enforcement is procedural, not structural.
  The report claims no full coverage while this gap remains.

## Trace-link completeness

One mixed run (delivered+parsed+action, delivered-unparsed,
withheld, pending) is joined with CL-16. Every missing link is
classified with an explicit reason: pending → no verdict yet;
delivered-unparsed → no parse event recorded; withheld → parse
`not_observed` by design (C-04) and no recipient action can exist.
No missing link is silently dropped.

## Verification

`python -m covertlens route-audit-demo` prints the route statuses;
`tests/test_route_audit.py` asserts all eight routes, the R-06 gap,
and the classified missing-link reasons.
