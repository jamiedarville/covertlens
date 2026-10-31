# Trace join: findings to ordered recipient events (CL-16 · REV-01)

`covertlens.trace_join.join_trace` projects one run's CL-7 trace
events, CL-12 gate deliveries and CL-13/14/15 analysis results into a
single versioned report, keyed by delivery. It is a pure read-only
projection: it emits no events and changes no verdicts. Machine
contract: [trace-join.schema.json](../../schemas/trace-join.schema.json).

## What every attempted delivery carries

Each `deliveries[]` record holds the attempted delivery's original
`content_hash` (from `delivery.attempted`, REV-01), its exact
`artifact_id` / `artifact_version_id`, sender/recipient/episode, the
attempt event reference, and the gate verdict reference
(`verdict_id` + verdict value + event reference). An attempt with no
verdict yet is not dropped: it gets
`verdict_reference_status: "missing"`, an entry in `missing`, and a
run-level linkage error, so consumers can tell "undecided" apart
from "clean".

Findings from analysis results attach only to the delivery whose
artifact version matches *and* whose original hash equals the
analysis `content_hash`. A mismatch is rejected
(`findings_status: "hash_mismatch_rejected"` plus a linkage error):
changed bytes never inherit findings for other bytes (C-05).
Results that cannot bind to a version in the run are listed under
`unjoined_results` with a reason, not discarded silently.

## Parse and next action, or an explicit missing status

A delivered artifact (an `artifact.accessed` event exists) links to:

- **Parse:** its `artifact.parsed` event (`linkage: "linked"`,
  recorded `parse_status`, event ref), or — when no parse event
  exists — `linkage: "missing"` with the explicit CL-7 parse status
  `missing`. That is a visible gap, never an implied success; a
  withheld artifact's parse stays `not_observed` (C-04).
- **Next action:** the first subsequent `recipient.action` for which
  the delivery is a candidate or the referenced delivery, or
  `linkage: "missing"` when there is none.

## Multiple candidates, no causation

For each `recipient.action`, the report lists every delivery served
to that recipient before the action as `candidate_delivery_ids`
(the action's own `delivery_id`, when present, is the
`referenced_delivery_id` and is included even if its access event is
absent). All linkage is labelled candidate/reference with
`causation_claimed: false` at delivery, action and report level.
The join shows which artifacts *could* have informed an action; it
never asserts that any one of them caused it. Researchers make that
call in review (CL-25), not the join.

Ordering follows `seq` only (never wall-clock), and events from more
than one run are rejected: joins never cross runs (REV-02).

## Out of scope here

Episode-level context across a run (CL-24), researcher reports
(CL-25) and replay experiments (CL-21) consume this join but are
separate tasks.
