# Live Gate: persisted gate state and the Live Gate page (CL-53)

Traces EV-06, ENF-03, ENF-05. Blocked by CL-47; blocks CL-59, CL-60, CL-64.

## Why

`InterceptionGate` kept deliveries, references and cached links in
memory, and `ArtifactStore._save()` rewrote the whole `index.json` on
every served read. The web app needs a gate that survives restart, and
the live gate demo is the clearest way to show the ladder.

## Persistence

All new state uses SQLite from the standard library (`sqlite3`). No
new runtime dependency is added.

| State | Location | Notes |
|---|---|---|
| Store access history | `covertlens.sqlite3` (`store_access`) under the store root | Moved out of `index.json`; `get_original` appends one row instead of rewriting the index. Pre-CL-53 inline `access` rows migrate on first open. |
| Store derivatives | `covertlens.sqlite3` (`store_derivatives`) | `register_derivative` persists; reopening restores `derivatives()` / `get_derivative()`. Previously derivatives were memory-only. |
| Gate deliveries | `gate.sqlite3` (`gate_deliveries`) under the store root | Full `DeliveryRecord`, including verdict and infrastructure error. |
| Gate access attempts | `gate.sqlite3` (`gate_access_attempts`) | Includes the delivery state at attempt time. |
| Gate trace events | `gate.sqlite3` (`gate_trace_events`) | One row per `(run_id, seq)`; `TraceLog` invariants still enforced in memory on append. |
| References, cached links, version context, covered routes, known versions | `gate.sqlite3` (`gate_references`, `gate_cached_links`, `gate_version_context`, `gate_covered`, `gate_known_versions`) | Handles rebuild from the store's persisted versions on load. |

Version/verdict metadata stays in `index.json`; blobs stay
content-addressed under `blobs/`. In-memory stores (`root=None`) keep
the gate and store purely in memory, so existing library tests are
unchanged. Restarting mid-run — new `ArtifactStore` and
`InterceptionGate` objects over the same root — restores the run,
its deliveries, its trace, and its audit.

## Computed `unauthorized_served`

`access_attempt_report()` no longer returns a hard-coded 0. A
recipient serve (`outcome == "served"`) counts as unauthorized when
the delivery's state at serve time was not `permitted`. Reviewer
serves (R-08) are evidence reads, not recipient deliveries, and never
count. Correct gate behaviour therefore reports 0 in every test,
while a serve recorded against a withheld or pending delivery reports
1 and fails the audit.

## Live Gate API (`app/main.py`)

Persistent singleton gate over `COVERTLENS_DATA_DIR/gate/store`.
Reviewer identities for the demo are `researcher-1` and `reviewer`.

| Endpoint | Behaviour |
|---|---|
| `POST /api/gate/runs` | Return (or generate) a `run_id`. |
| `GET /api/gate/runs` | List known run IDs. |
| `POST /api/gate/deliveries` | Multipart sender post (`file`, `run_id`, `sender_id`, `recipient_id`, `route_id` R-01…R-07, optional `episode_id`). Creates a pending delivery; R-08 is rejected as a delivery route. |
| `POST /api/gate/deliveries/{id}/analyze` | Analyse the stored bytes (`gate-analyzer` / `analysis` read). Returns findings, decision and `suggested_verdict`; the delivery stays pending. |
| `POST /api/gate/deliveries/{id}/verdict` | Record `log` / `flag` / `quarantine` / `fail_run`. `log`/`flag` permit; `quarantine`/`fail_run` withhold. |
| `GET /api/gate/runs/{run_id}` | Deliveries (with `recipient_message`), events, `access_report`, `access_attempts`, coverage. |
| `GET /api/gate/deliveries/{id}/recipient-image` | Recipient view. Serves bytes only via `recipient_access` after a permitting verdict; pending → 409, withheld → 403, both with the gate's reason (`recipient_message`) and no image bytes. |
| `GET /api/gate/deliveries/{id}/reviewer-image` | Reviewer view (R-08). Audited `reviewer_access`; serves withheld originals to authorized reviewers only. |
| `GET /api/gate/runs/{run_id}/events/stream` | SSE timeline (`text/event-stream`): replay, then poll for new seqs; ends after ~5 s idle and browsers reconnect. |
| `GET /gate` | SPA shell for the Live Gate page. |

`recipient_message` is the exact text the recipient pane shows:
`delivered`, `pending — awaiting analysis and verdict`, or
`withheld — quarantine verdict` / `withheld — fail_run verdict`
(or the infrastructure error when withheld without a verdict).

## Live Gate page (`/gate`)

Create a run; post an image as the sender on R-01…R-07; analyse;
apply a verdict; then compare the recipient and reviewer panes. The
recipient pane fetches only the recipient path: permitted deliveries
render the served bytes, withheld deliveries render
**withheld** plus the gate's reason and no image — it never renders
withheld bytes. The reviewer pane renders the R-08 evidence view.
Below, the SSE timeline and the access-attempt audit (including
computed `unauthorized_served`) update from the same run detail.

With unfrozen thresholds the analysed suggestion is triage-only
(`log`); the page preselects it but lets the operator apply any
ladder verdict, which is how quarantine and `fail_run` withholding
are demonstrated.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| Restart mid-run leaves run, deliveries and trace intact | `tests/test_live_gate.py::test_gate_state_survives_restart_mid_run`, `test_live_gate_run_survives_gate_restart` |
| `unauthorized_served` computed, 0 in every test | `test_unauthorized_served_is_computed_not_hardcoded` (a synthetic withheld serve counts 1); all gate/quarantine/route/latency suites assert 0 |
| Recipient pane shows "withheld" with the gate's reason for quarantine and `fail_run` | `test_recipient_pane_contract_withheld_with_reason` (parametrized) against `recipient_message`; `LiveGate.tsx` renders that message with `data-testid="recipient-withheld"` and no `<img>` |
