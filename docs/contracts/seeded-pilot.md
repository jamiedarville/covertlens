# Seeded live-trace pilot and adjudication contract (CL-30)

Implements: CL-30. Schema:
[schemas/seeded-pilot.schema.json](../../schemas/seeded-pilot.schema.json).
The pilot is pinned (CL-26 `pin_hash`), runs the CL-27 frozen
config in enforcement mode, and adjudicates through the CL-25
researcher report.

## Design

- **Seeded traces** (33: 15 encoded attempts, 18 clean/negative
  controls from CL-9/CL-22 plus a repeated low-band sender) carry
  scorer-side ground truth that detectors/adjudicators never see
  (C-07). Each seeded trace runs twice: log/flag mode (unfrozen
  config — all `log`, log-only, all delivered) and enforcement mode
  (`frozen-1.0.0`).
- **Unseeded traces** (5 fresh artifacts) have no recorded labels.
  They are reviewed only via the CL-25 report; unreviewed or
  uncertain cases remain `unresolved`, and
  `demonstrated_transfer` still requires an independent basis.

## Pilot results (seeded run)

- Enforcement withheld 8/33 seeded traces (all `fail_run`);
  0 clean controls were withheld.
- **Disagreement named:** 7 seeded attempts were still delivered in
  enforcement — the low/medium-band attempts below the frozen
  quarantine point (6 flagged/logged). This is the CL-28 coverage
  limit appearing live, reported per trace, not averaged away.
- 14 verdicts changed between log/flag and enforcement modes.
- Review volume: unseeded triage queue 5, reviewed 2 in the demo
  adjudication, 3 left unresolved; 6 seeded traces flagged for
  review in enforcement.
- **Repeated weak signals:** `sender-repeat` produced 3
  sub-enforcement LSB signals (its low-band attempts), and baseline
  weak-band scores recur for the suite senders. Weak signals are
  review evidence only — they never withhold by themselves and are
  never equated with collusion (C-02).

## Verification

`python -m covertlens pilot-demo` prints the pilot summary;
`tests/test_pilot.py` asserts both modes, the named disagreements,
unresolved-by-default adjudication, and the basis requirement for
`demonstrated_transfer`.
