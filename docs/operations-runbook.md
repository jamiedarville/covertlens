# CovertLens operations runbook (CL-36)

Audience: harness engineers (operate) and researchers (review).
Release state: **release_with_limitations** (CL-35 scorecard:
`config/release-scorecard.json`). Every load-bearing claim below
is exercised by `python -m covertlens handoff-demo`
(`covertlens.handoff.run_handoff_verification`).

## 1. Thresholds (frozen-1.4.0)

- The live enforcement points are `config/frozen-thresholds.json`
  (`frozen-1.4.0`, CL-78: the CL-68 banded freeze with the geometric
  family re-frozen for detector 3.0.0; `frozen-1.2.0` is skipped).
  Triage (`flag_at`) and enforcement (`quarantine_at`,
  `fail_run_at`) are separate points per family; do not merge them.
- **Change rule:** thresholds change only as a *new freeze*
  (§8: `make refreeze`). Never edit a frozen config in place —
  `build_pin` / `pin_differences` (CL-26) name
  `threshold_config_version` drift. The geometric quarantine point is
  always calibrated above the non-structure score ceiling (0.5), so
  quantization alone never withholds.
- **Rollback:** §7 (`COVERTLENS_FROZEN_CONFIG`). Rolling back to the
  pre-freeze shipped config restores log-only behaviour (verdicts
  `log`, `enforceable: false`) — verified in the handoff checks.
  Announce the rollback in the campaign log; prior verdicts are not
  rewritten.
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
- **Where the limits live (CL-65).** Library parser limits:
  `covertlens.parsing.ParserLimits` / `DEFAULT_LIMITS` (10 MiB input,
  20 MP, 2 s runtime). Segmenter caps: `SegmenterConfig`
  (10 MiB, 2 MP). Web service: `COVERTLENS_MAX_UPLOAD_BYTES` (8 MiB;
  the body limit adds 64 KiB of multipart framing and is enforced
  before parsing), `COVERTLENS_MAX_PIXELS` (20 MP),
  `COVERTLENS_ANALYZE_TIMEOUT_S` (30 s wall clock per analysis or
  generation), `COVERTLENS_WORKERS` (4), `COVERTLENS_RATE_LIMIT_PER_MIN`
  (30 per client per minute on every upload path).
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

### Web service and CI (CL-78)

- **Demo roles are not authentication.** `X-Demo-Role` is honoured
  only with `COVERTLENS_DEMO_ROLES=on`, which the Docker image and
  `docker-compose.yml` set because they are the demo. For any
  deployment beyond a demo, use real roles (CL-67, below).
- **Real roles (CL-67).** Build with
  `docker build --build-arg DEMO_BUILD=off -t covertlens:prod .`
  (no demo picker, `X-Demo-Role` never trusted) and run with
  `COVERTLENS_AUTH_MODE=oidc`, `COVERTLENS_OIDC_ISSUER`,
  `COVERTLENS_OIDC_CLIENT_ID` (and `COVERTLENS_OIDC_CLIENT_SECRET` for
  a confidential client). Register `https://<host>/api/auth/callback`
  as the redirect URI. Edit `config/identity-mapping.json` (or point
  `COVERTLENS_IDENTITY_MAPPING` at your own file) to map IdP groups
  to roles and run-scope patterns; the service refuses to start with
  incomplete OIDC settings or an invalid mapping. Harnesses send a
  bearer JWT for a service identity (`GateClient(bearer_token=...)`).
  Contract: `docs/contracts/authentication.md`.
- **Leaderboard (CL-70).** In OIDC mode submissions need sign-in and
  wait for moderation by default. Operators approve or hide entries
  on `POST /api/leaderboard/entries/{id}/moderation`
  (`leaderboard.moderate`). `COVERTLENS_LEADERBOARD_RATE_PER_HOUR`
  (20) and `COVERTLENS_LEADERBOARD_MODERATION` tune it. A new detector
  version or freeze starts a new board automatically.
- **Static Analyze page (CL-66).** `cd app/frontend && npm run
  build:static`, then publish `dist-static/` on any static host; CI
  uploads it as the `covertlens-static-analyze` artifact.
- **Behind a reverse proxy**, state-changing `/api` requests must
  carry an `Origin` that matches `Host` or `X-Forwarded-Host`, or
  is listed in `COVERTLENS_ALLOWED_ORIGINS` (comma separated). Set
  `COVERTLENS_TRUSTED_PROXIES` to the proxy's address so the rate
  limiter keys on the client from `X-Forwarded-For`; without it the
  header is ignored (anyone could forge it) and every client behind
  the proxy shares one limit.
- **Rate limits are per process.** Each replica keeps its own
  one-minute windows (idle windows are evicted), so N replicas allow
  N times the rate. Put a shared limiter in the proxy for a real
  deployment.
- **Worker pool.** A timed-out analysis kills its worker and the
  pool is rebuilt; a crashed worker is rebuilt and the call retried
  once. `/api/health` reports `worker_pool_rebuilds`; a rising count
  means inputs are hitting the deadline.
- **Data directory.** `/api/health` returns 503 `degraded` when
  `COVERTLENS_DATA_DIR` is not writable, when precompute failed, or
  when the gate reload skipped versions it could not load (a damaged
  store); gate, generation and review endpoints answer 503 with the
  reason instead of 500, and benchmark pages say why there is no
  cache. Fix the volume permissions and restart.
- **Fork pull requests and the self-hosted runner.** The fork guard
  in `.github/workflows/test.yml` is in the PR's own copy of the
  workflow, so a fork can edit it. The control that holds is the
  repository setting *Settings → Actions → General → Fork pull
  request workflows from outside collaborators → Require approval
  for all outside collaborators*. Check it with
  `gh api repos/jamiedarville/covertlens/actions/permissions/fork-pr-contributor-approval`
  (expect `all_external_contributors`); set it with the same path
  and `-X PUT -f approval_policy=all_external_contributors`. Never
  approve a fork PR's workflow run without reading its workflow
  diff first. Runner groups are an organization feature; while the
  repository is owned by a personal account, keep self-hosted
  runners registered to this repository only.

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

## 7. Which frozen config is live (CL-65)

- Default: `config/frozen-thresholds.json`. Override with the
  `COVERTLENS_FROZEN_CONFIG` environment variable (any path);
  `load_frozen_thresholds()` honours it whenever no explicit path
  is passed. The web service and every CLI demo read it the same way.
- **Rollback:** keep the previous freeze file (it is in git history).
  Point `COVERTLENS_FROZEN_CONFIG` at it, restart the service, and
  add an entry to [campaign-log.md](campaign-log.md) using its
  template. Prior verdicts are not rewritten. Rolling back to the
  pre-freeze shipped config (`DEFAULT_CONFIG`) restores log-only
  behaviour, as verified by `handoff-demo`.

## 8. Re-freezing thresholds (CL-65)

1. Run `make refreeze` (or `python scripts/refreeze.py`; pass
   `REFREEZE_ARGS="--version frozen-X.Y.Z"` to skip a label already
   used elsewhere). `make refreeze` sets `COVERTLENS_BUILD_WORKERS=auto`
   so the CL-68 banded suite builds and scores in a process pool. It
   recalibrates on development data only, bumps the frozen config
   version, rewrites `config/frozen-thresholds.json` (preserving the
   `owners`/`coverage` blocks), then regenerates
   `config/release-scorecard.json` — including its `pin_hash` — from
   the new freeze.
2. Run the full test suite (`pytest`, `ruff`, `mypy`). In particular
   `test_published_artifact_matches_built_scorecard` must pass: the
   published scorecard is byte-compared against a rebuild.
3. Add a campaign-log entry with the old/new versions and the new
   pin hash. Never edit a frozen file without bumping its version.

## 9. Regenerating published artefacts (CL-65)

- Scorecard: `make refreeze`, or rebuild without touching the freeze
  with `python -m covertlens scorecard-demo --json --out config/release-scorecard.json`
  (only valid while the freeze is unchanged).
- Benchmark/report caches for the web service: `python scripts/precompute.py --data-dir /data`.
- Frontend test fixture `app/frontend/tests/fixtures/analyze-structured.json`:
  re-save `app.analysis_worker.analyze_bytes(structured_payload_fixture().data)`
  after an API shape change or a re-freeze (`npm test` reads it).
- Benchmark JSON for review: the CLI demos (`benchmark-lsb`, `benchmark-dct`,
  `geo-benchmark-demo`, `frozen-demo`, `robustness-demo`, `adaptive-demo`),
  each with `--json --out <path>`.

## 10. Where the 10 MiB / 20 MP / 2 s limits live (CL-65)

- Library: `ParserLimits` in `covertlens/parsing.py`
  (`max_input_bytes=10 MiB`, `max_pixels=20 MP`, decompressed cap,
  `max_runtime_s=2.0`). Library callers pass their own
  `ParserLimits(...)` to `analyze_bytes`/`analyze_all_bytes`.
- Web service: uploads are capped before reading by
  `COVERTLENS_MAX_UPLOAD_BYTES` (default 8 MiB) and analysis wall-clock
  by `COVERTLENS_ANALYZE_TIMEOUT_S` (default 30 s) in `app/main.py`.
  Changing a limit changes the claim — record it in the campaign log.

## 11. When `validate_handoff` fails (CL-65)

1. Run `python -m covertlens handoff-demo --json` and read the failing
   key; each `validate_handoff` message names the section
   (`threshold_operations`, `quarantine_handling`, `infrastructure_errors`,
   `reruns`, `dataset_retirement`).
2. Threshold failures: check which freeze is live (§7) — a stray
   `COVERTLENS_FROZEN_CONFIG` is the usual cause. Re-freeze (§8) only
   if the change is intended.
3. Quarantine/audit failures: do not override verdicts to make it
   pass. Capture the audit head and pin hash from the scorecard and
   escalate as a release-blocking incident (§6).
4. Infrastructure failures: treat as availability (§3), fix the
   input/pipeline, then rerun. Never resolve by editing thresholds.
