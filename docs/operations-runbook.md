# CovertLens operations runbook (CL-36)

Audience: harness engineers (operate) and researchers (review).
Release state: **release_with_limitations** (CL-35 scorecard:
`config/release-scorecard.json`). Every load-bearing claim below
is exercised by `python -m covertlens handoff-demo`
(`covertlens.handoff.run_handoff_verification`).

## 1. Thresholds (frozen-1.0.0)

- The live enforcement points are `config/frozen-thresholds.json`
  (`frozen-1.0.0`, calibrated in CL-27). Triage (`flag_at`) and
  enforcement (`quarantine_at`, `fail_run_at`) are separate points
  per family; do not merge them.
- **Change rule:** thresholds change only as a *new freeze*
  (recalibrate on development data, bump the version, rebuild the
  pin). Never edit a frozen config in place — `build_pin` /
  `pin_differences` (CL-26) name `threshold_config_version` drift.
- **Rollback:** point the campaign back at the previous pin/config.
  Rolling back to the pre-freeze shipped config restores log-only
  behaviour (verdicts `log`, `enforceable: false`) — verified in
  the handoff checks. Announce the rollback in the campaign log;
  prior verdicts are not rewritten.
- Coverage honesty: the freeze claims calibrated bands
  (low/medium) on `gradient_noise` covers at suite-like densities.
  Outside that (CL-34), enforcement may miss — treat misses as
  expected, not as incidents.

## 2. Quarantine handling

- `quarantine` / `fail_run` verdicts withhold delivery on every
  route (CL-18/CL-32). Recipients get `WithheldError`; bytes are
  never served pending or withheld (`unauthorized_served: 0`).
- Reviewers read quarantined originals only via the audited R-08
  path (`reviewer_access`, authorized reviewer ids) or the CL-11
  gateway (`original.read`). Both are audit-logged.
- A recorded verdict is **immutable**. To change an outcome, a
  researcher records a CL-11 verdict override **with a reason**
  (`verdict.override` permission; agents cannot). The override is
  an audit entry, not an edit.
- Withheld artifacts record parse `not_observed` (C-04) and can
  never count as successful transfers (CL-31).

## 3. Infrastructure errors (not detection failures)

- Classes (CL-19): `corrupt_input`, `unsupported_format`,
  `oversized_input`, `analysis_timeout`, `detector_error`,
  `gate_error`. Behaviour: withhold delivery, run outcome
  `failed_infrastructure`, **no clean verdict**, never a detection
  failure and never collusion evidence.
- Triage order: check the error class first, then limits
  (CL-13: 10 MiB / 20 MP / 2 s runtime), then detector health.
  Large JPEGs hitting the 2 s deadline are an availability issue
  (CL-29), not a detection event — see the scorecard limitation.
- Fix the input/pipeline, then rerun (§4). Do not "resolve" an
  infrastructure failure by overriding a verdict.

## 4. Reruns and pinned campaigns

- Campaigns are pinned (CL-26): dataset hash, detector versions,
  threshold config, seeds. Before a rerun, `pin_differences`
  must be empty; a difference means the campaign definition
  changed — bump the campaign, don't silently rerun.
- Seeded replay (CL-21) is exactly repeatable; the deterministic
  pipeline reproduces verdicts (verified). Stochastic scorers
  must state their agreement bound in the experiment config.
- Changed bytes are a new artifact version; verdicts bind to the
  exact version+hash and never carry over (C-05).

## 5. Dataset retention and access

- Retention is the dataset lifetime (C-01): original bytes and
  evidence remain internal; exports carry hashes, versions,
  findings and dispositions — never bytes (CL-33).
- Permissions are dataset-scoped and deny-by-default (CL-11):
  agents hold no evidence permissions; `payload.read` is
  scorer-only; permission on one dataset grants nothing on
  another. Denials are audit-logged.
- Retirement is governed: operator requests → a *different*
  approver approves (self-approval is denied) → execution first
  captures the reproducibility bundle (artifact hashes/versions,
  config/policy versions, audit head), then deletes. There is no
  other deletion path.

## 6. Handoff

**Harness engineers:** integrate at the gate (`InterceptionGate`)
— intercept every route in the CL-7 inventory, record verdicts
before any access, and surface infrastructure outcomes separately
from verdicts. Start from `python -m covertlens gate-demo`,
`route-audit-demo`, `latency-demo`.

**Researchers:** work from the CL-25 run report / CL-33 export
package. Dispositions start `unresolved`; `demonstrated_transfer`
requires a recorded basis in independent recovery/action
evidence — a score is never sufficient. Scores are evidence aids
(`evidence_aid_not_decoded_message`), not decoded messages and
not collusion proof. Start from `python -m covertlens
report-demo`, `export-demo`, `pilot-demo`, `scorecard-demo`.

**Escalation:** detector misses inside claimed coverage, any
unauthorized serve, or a broken audit chain / package seal are
release-blocking incidents; file them against the frozen config
version and pin hash from the scorecard.
