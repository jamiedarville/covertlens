# Quarantine enforcement on every access path (CL-18 · ENF-03)

The CL-12 gate is the single serving path, hardened in CL-18 so a
quarantine (or `fail_run`) verdict holds on every route, not just the
direct one. Implemented in `covertlens.gate.InterceptionGate`.

## Same gate on every path

- **Direct references, tool outputs, direct fetches, parse hand-off
  (R-01…R-04, R-06, R-07):** `serve_via_route(route_id, delivery_id)`
  validates the gated route and then runs the identical verdict
  check as `recipient_access`. There is no per-route shortcut.
- **Cached links (R-05):** `issue_cached_link` mints an opaque token
  that grants nothing by itself. `redeem_cached_link` resolves the
  token and re-checks the delivery's *current* verdict, so a link
  issued while pending — or before a quarantine verdict — can never
  serve withheld bytes.
- **Reviewer evidence (R-08):** `reviewer_access` is the evidence
  path, not a delivery. Only actors in the caller-supplied authorized
  reviewer set may read a quarantined original through it; the read
  goes through the CL-8 store's audited `get_original`
  (`purpose="review"`), and recipients gain nothing from it.
  Non-reviewers are denied (`ReviewerAccessError`).

## No access before verdict, including concurrently

All gate mutations and access decisions run under one re-entrant
lock: the verdict check and the byte serve are a single locked step,
so concurrent delivery/access attempts cannot observe a half-decided
delivery or interleave trace sequence numbers. Before a verdict,
every attempt raises `PendingDeliveryError`; after a withholding
verdict, `WithheldError`. Both are recorded.

## Audit

`access_attempt_report()` counts every recorded attempt by outcome
(`served`, `pending_denied`, `withheld_denied`, `reviewer_served`,
`reviewer_denied`) and by route. `unauthorized_served` is zero by
construction — `served` is only recorded after the permitting check
passes inside the lock — and the concurrency tests in
`tests/test_quarantine.py` assert that property under parallel load.

## Out of scope here

Gate race/cache-invalidation verification (CL-20), run-failure
outcomes (CL-19) and route-by-route end-to-end audit (CL-32) build
on this enforcement but are separate tasks.
