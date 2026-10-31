# Verdict ladder and threshold configuration (CL-17 · ENF-01/ENF-02)

Detector findings become a gate verdict in `covertlens.verdicts`,
and nowhere else. The decision record is versioned
(`covertlens.verdict-decision`, ladder v`1.0.0`, config v`1.0.0`);
machine contract:
[verdict-decision.schema.json](../../schemas/verdict-decision.schema.json).

## The ladder (ENF-01)

| Verdict | Delivery | Execution | Decided by |
|---|---|---|---|
| `log` | permit | continues | score below the triage point |
| `flag` | permit | continues | score at/above triage, below enforcement |
| `quarantine` | withhold | continues | score at/above enforcement quarantine point |
| `fail_run` | withhold | **halts** (`halt_execution: true`) | score at/above enforcement fail point |

`delivery_for_verdict` is the single mapping; `decide_and_record`
binds a decision to a pending CL-12 gate delivery, after which the
gate itself serves or withholds bytes. A decision is computed per
channel family and the most severe family verdict wins for the
artifact; every decision records the per-family max score, the
detectors (name@version) that produced it, and the points used.

## Two operating points, separately configured (C-06)

Each family in `ThresholdConfig` carries a **triage** point
(`flag_at`, high-recall) and an **enforcement** pair
(`quarantine_at`, `fail_run_at`, high-precision). They are configured
and validated separately: a frozen family must supply all three,
ordered `flag_at <= quarantine_at <= fail_run_at`.

The shipped config is built from the CL-7 manifest
(`threshold_config_from_manifest`) and stays
`unfrozen_placeholder` with null points. Unfrozen families are
log-only and the decision is marked `enforceable: false` — code must
treat a null point as "not yet enforceable", never as zero. Freezing
real numbers is CL-27, calibrated without held-out labels (C-07);
this module accepts frozen configs (tests exercise them) but ships
none.

## No lookahead (ENF-02, C-03)

`decide_verdict(findings, config, context=..., observed_events=...)`
takes only pre-delivery evidence. Any `recipient.action` in the
observed events — a recipient action is by definition post-delivery —
or any event with `seq` after `context.evidence_through_seq` raises
`LookaheadError`; nothing is silently filtered. Findings themselves
are validated against the DET-02 schema before use, and the decision
binds to one exact artifact version and original content hash
(C-05). A verdict is a gate outcome, never demonstrated collusion:
every record carries `equated_with_collusion: false` (C-02).

## Out of scope here

Quarantine enforcement on every access path (CL-18), run-failure
outcomes and finalization (CL-19), cache invalidation (CL-20) and
threshold freezing (CL-27) build on this ladder but are separate
tasks.
