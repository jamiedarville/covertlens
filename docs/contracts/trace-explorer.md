# Trace explorer (CL-60)

Traces REV-01, REV-02, REV-03. Blocked by CL-53.

## View

`covertlens.trace_explorer.build_trace_explorer(events, results)`
joins one run into a single read-only view:

| Part | Source | Contents |
|---|---|---|
| Deliveries | CL-16 `join_trace` | Every attempted delivery: original `content_hash`, verdict reference (`linked`, with verdict ID/value) or explicit `missing` status, parse linkage and next-action linkage (each `linked` or explicitly `missing`). The join's `missing` keys are expanded to `missing_reasons` — one stated reason per absent link (`no gate verdict recorded for this delivery yet`, `no recipient parse recorded for this delivered artifact`, `no recipient action recorded after this delivery`, `no original content hash recorded for this delivery`). |
| Episode context | CL-24 `build_episode_context` | Participants (sent/received/actions per agent) and episodes for this run only. Multi-run input raises in the join (REV-02). |
| Repeated weak signals | Episode context scores | Per sender: delivery count, delivered count, deliveries in the weak band (strongest family score above 0, below the 0.75 structure-grade band), and `repeated_weak` at two or more. Labelled `triage_aid_not_verdict` (CL-31: sequence evidence is a triage aid only). |
| Actions | CL-16 join | Recipient actions with `candidate_delivery_ids` — deliveries served to that recipient before the action, plus the action's own delivery reference when present. |

`validate_trace_explorer` checks the schema, per-delivery hash
and linked-or-missing statuses, a reason for every missing link,
and that the underlying join and context validations pass.

## Causation

`causation_claimed` is `false` on the view and on every action
and next-action record. Candidate inputs are deliveries visible
to the recipient before an action; the view carries the note
"candidate inputs are deliveries visible to the recipient before
an action; they are not a cause of the action", and the page
uses candidate wording throughout. No element states or implies
that an artifact produced an action (REV-01).

## API and page

`GET /api/trace/runs/{run_id}` builds the view from the
persistent gate's trace plus fresh deterministic analysis of the
stored bytes (the CL-59 recompute pattern). It needs a demo role
with `trace.read` on the run (researcher or reviewer; viewer → 403,
CL-78). Unknown runs return an empty view for the requested ID.
The Trace explorer page
(`/trace`, SPA route in `app/main.py`) renders the deliveries
table with hashes, verdict references and explicit missing
statuses/reasons, the episode-context and per-sender weak-signal
views, and the actions table with candidate inputs and
`causation_claimed: false`.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| Every delivery in a demo run appears with content hash, verdict reference and parse/next-action link or explicit missing status | `tests/test_trace_explorer.py::test_every_delivery_has_hash_and_link_or_missing_reason`, `test_trace_api_covers_every_delivery_with_explicit_missing` (linked verdict for the decided delivery, `missing` + reason for the pending one; reasons match `missing` keys exactly) |
| No page element implies causation between an artifact and an action | `test_action_candidates_never_claim_causation` (`causation_claimed: false` on view, actions and next-action records; unserved delivery never listed as a candidate), `test_trace_spa_route_and_no_causal_wording` (page source guard over causal phrases) |
