# Requirements traceability and planning history

Planning material moved here from `REQUIREMENTS.md` in CL-49 so the
requirements file stays a requirements record. Nothing in this file
changes a requirement; the traceability mapping itself lives in
[REQUIREMENTS.md](../../REQUIREMENTS.md) §2, and the shipped result
of each delivery task is recorded in
[CHANGELOG.md](../../CHANGELOG.md).

## How trace keys work

Requirements are grouped as EV (harness integration and evidence),
DT (datasets and ground truth), DET (channel detection), GEO
(geometric/semantic encoding), ENF (verdicts and enforcement), REV
(trace correlation and review), and OP (evaluation and release).
The parenthetical key after each requirement (for example `CL-7`)
is the delivery task that implements it. The same keys head the
deliverables ledger in the README and the entries in
`CHANGELOG.md`, so any requirement can be followed from statement
to shipped code, tests, contract doc, and schema.

## Derivation record (2026-10-28)

The requirements were derived from a review of the Covert Lens
(CL) tracker project on 2026-10-28: 6 epics (CL-1…CL-6), 30 tasks
(CL-7…CL-36), and 6 planned sprints. The source product document
referenced throughout is **CovertLens PRD v0.2 — October 27,
2026** (FR-01…FR-13, §§10–13); owner: Agent Evaluation / AI
Safety team. `REQUIREMENTS.md` records each requirement once, with
its delivery-task key.

The geometric/semantic addendum (`REQUIREMENTS.md` §8) was added
the same day as a proposal without delivery tasks. It has since
been delivered as the fourth channel family (CL-38…CL-44, with
scene context in CL-45 and structure test v2 in CL-46), and §8 is
retained as the threat-model and detection-approach record.

## Delivery plan as recorded at planning time

Historical record: six planned two-week sprints, five tasks each.
Every task listed here, and the later CL-38…CL-49 sequence, has
since shipped; see `CHANGELOG.md` for the as-built order.

| Sprint | Goal | Tasks |
|---|---|---|
| CL Sprint 1 | Harness contracts and synthetic foundations | CL-7, CL-8, CL-9, CL-10, CL-11 |
| CL Sprint 2 | Artifact interception and LSB/DCT baselines | CL-12, CL-13, CL-14, CL-15, CL-16 |
| CL Sprint 3 | Inline quarantine and run-failure enforcement | CL-17, CL-18, CL-19, CL-20, CL-21 |
| CL Sprint 4 | Metadata, sequence context, researcher reports | CL-22, CL-23, CL-24, CL-25, CL-26 |
| CL Sprint 5 | Frozen benchmarks and live eval pilot | CL-27, CL-28, CL-29, CL-30, CL-31 |
| CL Sprint 6 | MVP hardening, scorecard, handoff | CL-32, CL-33, CL-34, CL-35, CL-36 |

Dependency analysis (parsed from the task descriptions at
planning time):

- Single root: **CL-7** (manifest) — everything descends from it.
- No dependency points to a same- or later-numbered task; no
  sprint hosts a task depending on a later sprint. The plan is
  topologically sound.
- Critical path (14 tasks): CL-7 → CL-9 → CL-10 → CL-14 → CL-17 →
  CL-18 → CL-20 → CL-26 → CL-27 → CL-28 → CL-31 → CL-34 → CL-35 →
  CL-36. (CL-15 mirrors CL-14 and is equally constraining in
  practice.)
- Sprint 1 entry order: CL-7 first, then CL-8 and CL-9 in
  parallel, then CL-10, then CL-11.

## Open questions recorded on 2026-10-28

Retained as the planning record; several were overtaken by
delivery (the geometric addendum shipped, CL-29's target was
measured with documented misses). Current status lives in the
release scorecard, not here.

1. Sprint 1 had no start date and no sprint was active: when to
   start, and who activates sprints?
2. No estimates existed (no story-point field in use): estimate
   during refinement, or track by task count?
3. All tasks carried default priority with no assignees: confirm
   owners, at least for the Sprint 1 chain.
4. Tasks cite PRD requirements FR-01…FR-13 and §§10–13, which are
   not in the tracker: link the PRD if requirements should trace
   to it directly.
5. CL-29's latency target was marked "proposed": owner agreement
   needed before Sprint 5.
6. Geometric/semantic encoding (§8) was not in CL-7…CL-36 or PRD
   v0.2: add new tasks, extend an existing detection task, or
   keep it a proposed addendum? Is vector-source interception in
   harness scope?

## Working protocol

Delivery was tracked task by task under the CL keys:

- Each task moves To Do → In Progress → Done as work starts and
  its acceptance criteria are met, with progress comments
  recording what was verified and what remains.
- Code lands per task on its own branch through a reviewed pull
  request; a task closes only after its checks are green and the
  pull request is merged.
- Sprint assignments stay as planned; a task that needs to move
  sprints is flagged before it is moved.
- Starting or completing sprints and editing task scope are owner
  decisions; routine status and comment updates accompany the
  work directly.
