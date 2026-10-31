# Operations, rollback and researcher handoff contract (CL-36)

Implements: CL-36. Schema:
[schemas/ops-handoff.schema.json](../../schemas/ops-handoff.schema.json).
The deliverable runbook is
[docs/operations-runbook.md](../operations-runbook.md); this
contract records what the handoff verification proves about it.

## Verified claims (all exercised, not just documented)

- **Thresholds:** `frozen-1.0.0` decides enforceably
  (`fail_run` at 0.95, `enforceable: true`); a pin under it names
  `threshold_config_version` when the config changes; rollback to
  the shipped config restores log-only (`log`,
  `enforceable: false`).
- **Quarantine:** recipients denied, authorized reviewers served,
  recorded verdicts immutable, overrides only via the CL-11
  gateway with a reason (agent override denied), audit chain
  valid.
- **Infrastructure errors:** timeout/oversize are explicit,
  withhold delivery, and produce no clean verdict (CL-19/CL-29
  checks reused).
- **Reruns:** seeded replay repeats exactly; the deterministic
  pipeline reproduces verdicts within bounds (CL-21/CL-26).
- **Retirement:** request → non-requester approval
  (self-approval denied) → bundle-then-delete, reaching `deleted`
  with a valid audit chain (CL-11).

## Handoff contents

Runbook §6 gives harness engineers the gate integration path and
researchers the report/export review path, including the
`demonstrated_transfer` basis rule and the evidence-aid labelling
rule. Retention and dataset-scoped access rules are runbook §5.

## Verification

`python -m covertlens handoff-demo` prints the verification
summary; `tests/test_handoff.py` asserts each claim above.
