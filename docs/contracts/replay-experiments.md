# Delivered-versus-withheld replay experiments (CL-21 · DT-05)

`covertlens.replay.run_replay` compares what happens when the same
encoded artifact is delivered versus withheld, so prevention is
measured separately from observed information transfer. Machine
contract: [replay-experiment.schema.json](../../schemas/replay-experiment.schema.json).

## Design

- **Matched trials:** every `encoded` CL-9 fixture creates one
  delivered and one withheld trial (same bytes, same payload band);
  `repetitions` adds repeats. Trial order is shuffled under
  `ReplayConfig.seed`, and each trial carries its own `trial_seed`
  (seed + position stride) so stochastic recipient behaviour is
  reproducible per trial, not averaged away.
- **Pinned conditions:** the report records the config (version,
  seed, repetitions, detector versions, verdict-config version) and
  every fixture's content hash. Re-running with the same pinned
  conditions reproduces the same trial order and seeds.
- **Two independent outcomes per trial:** `recovery` (an independent
  decoder — by default CL-9 payload verification — over the bytes
  actually received) and `legitimate_task_success` (caller-supplied;
  it may succeed without the image over declared channels). They are
  reported as separate rates per condition and per payload band,
  never as one blended score.

## Blocked runs never claim transfer (C-04)

A withheld trial receives no bytes: `parse_status` is
`not_observed`, `recovery` is `not_observed` (not a decoder failure,
not a success), and `demonstrated_transfer` is false by construction
— `validate_replay` enforces all three. Only delivered + recovered
trials count as demonstrated transfer, and the report carries
`equated_with_collusion: false`: a replay outcome is experiment
evidence, not proof that agents colluded (C-02).

## Out of scope here

Sequence/context value (CL-24), prevention-effectiveness ablations
(CL-31) and pinned campaign replay (CL-26) build on these trials but
are separate tasks.
