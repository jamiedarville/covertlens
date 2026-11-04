# Plain-English UI (CL-79)

Record of the CL-79 wording pass: what was reviewed, the wording
rules applied, and what still needs people.

## Rule applied on every screen

Each screen answers, in visible text (never hover-only):

1. What am I looking at, and why does it exist?
2. What can I do here, and what happens when I do it?
3. What do I need to enter or choose (with examples)?
4. What does the result mean, and what do I do next?

Supporting rules:

- Plain word first, technical term in brackets or under
  "Technical details (exact values, for specialists)".
- "Nothing found", "not checked", "check failed" and "held back"
  are always distinguished.
- A score is evidence, never proof; a clear result never promises
  that nothing is hidden; nothing is described as "decoded" unless
  it was (only the reviewer-only candidate decode, labelled a
  hypothesis).
- Every error says what happened and gives a "What to do" step.
- Disabled controls say why, beside the control.
- Exact numbers, ids and settings versions are unchanged; only
  their framing changed. No detection, threshold, permission or
  backend behaviour changed.

## Wording map (main renames)

| Before | Now |
|---|---|
| Analyze | Check an image |
| Generate | Make a test image |
| Live Gate | Delivery gate (live) |
| Reviewer | Review held-back images |
| Trace | Timeline of a run |
| Benchmarks | How accurate is it? |
| Scorecard | Release decision |
| (verdict) log / flag / quarantine / fail_run | Let it through and record it / …but flag it for attention / Hold the image back for review / Hold the image back and stop the run (exact value kept alongside) |
| Artifact | Image / picture (file) |
| Run trace | Timeline of what happened |
| Spatial LSB | Tiny pixel changes (spatial LSB) |
| JPEG DCT | JPEG compression data (DCT) |
| Metadata | Information stored in the file (metadata) |
| Geometric | Shapes and patterns in the picture (geometric) |
| Quantized | Falls on a regular spacing |
| Run | Session ("run"), defined where first used |
| Content hash | File fingerprint |
| Disposition | Your judgement (each option explained beside the control) |
| Recall / false positive rate / Wilson 95% | Share caught / share of innocent pictures wrongly flagged / likely range (glossary box on the accuracy page) |

Shared wording helpers live in `app/frontend/src/format.ts`
(`verdictLabel`, `verdictMeaning`, `gateStateLabel`,
`DISPOSITION_LABELS`, `DISPOSITION_MEANINGS`, `scoreMeaning`,
`classificationLabel`, `classificationMeaning`, `humanizeKey`) so
every page uses the same words. Numbered "Start here" steps and
the collapsed technical-details block live in
`app/frontend/src/components/Help.tsx`.

## Coverage checklist

Every route in `app/frontend/src/App.tsx`, the static
(in-browser) build, and every shared component was reviewed:

- [x] `/` Landing — product explanation, 3-step start, skyline
      demo with explained measurements, loading and error states
- [x] `/analyze` — purpose, drop zone (accepted files, what
      happens), ready-made examples (incl. why the button is
      disabled, empty list), checking / success / too-large /
      timeout / unsupported / failed states, result header
- [x] Results (shared) — delivery decision first in plain words,
      per-check cards (what each looks for, score meaning,
      limitations, not-checked state), cut-off table, evidence
      tables with written-out field names
- [x] Geometric overlay + charts (shared) — every chart explained
      (sequence, spacing fit, distance-from-step, "just an ordinary
      chart?", "could this be coincidence?"), tables relabelled,
      preview-missing states
- [x] `/generate` — every input explained (hiding place, seeds,
      payload modes, grid choices incl. disabled state), result,
      leaderboard entry (incl. already-entered state)
- [x] `/gate` — 4-step flow, session/sender/recipient/episode and
      route explanations, verdict choices with consequences,
      deliveries table, recipient vs reviewer views (incl.
      refusals), timeline, audit counts and the
      must-stay-zero warning
- [x] `/review` — reviewing steps, role guidance, queue, original
      (incl. refused opening), candidate decode warning,
      judgements with meanings and the demonstrated-transfer
      evidence requirement, second opinion (off / unavailable /
      unparseable states), sealed download, audit chain
- [x] `/trace` — purpose, causation caution in plain words,
      deliveries table (decision / opened / next / missing),
      participants & episodes, repeated small signals, actions
- [x] `/benchmarks` — glossary box, all six tabs (main test,
      cut-off trade-offs, shape-pattern tests, checker-parts
      comparison, speed, sneak attempts), chart and table
      language, computing and error states, provenance lines
- [x] `/leaderboard` — what is ranked and why, strictness
      choices, checker-version boards, empty standings, loading
- [x] `/scorecard` — decision first, targets table, rationale,
      limitations, changed targets, evidence, loading/error
- [x] Header navigation, page titles, footer, skip link
- [x] Direct page loads: `/benchmarks` and `/scorecard` had no
      server route, so opening or bookmarking them showed a bare
      JSON "Not Found"; both now serve the app like every other
      page (`app/main.py`, covered by `test_spa_routes_and_assets`)
- [x] Role controls (demo picker and real sign-in states:
      not configured, signed out, signed in)
- [x] API error messages surfaced by the UI (`src/api.ts`)
- [x] Static in-browser build (`src/static/main.tsx`) — privacy,
      size limits, loading and offline states
- [x] `index.html` page description

Server-generated strings shown verbatim (for example a gate's
`recipient_message`, detector `limitations`, benchmark
trade-off/limitation lists, scorecard rationale) are unchanged —
CL-79 excludes backend behaviour — but each is now framed by a
plain-English introduction, and lists from reports are headed
"in the report's own words".

## Verification done

- `npm run typecheck`, `npm run build`, `npm test`
  (incl. new `tests/plain-english.test.tsx` pinning key
  newcomer sentences), `npm run test:prod-build`.
- `tests/test_static_build.py` text assertions updated to the
  new labels (same behaviour checks).
- Manual browser pass over the main journey (home → check an
  image) and each page rendering (see PR description).

## Still outstanding (needs people, not code)

CL-79 also asks for validation with at least three people who
have not worked on the project, completing the main journeys
unaided. That cannot be done by an automated change. The PR is
therefore submitted for the requester's review with this item
explicitly open: recruit three first-time users, ask each to
(1) say what CovertLens is for from the home page, (2) check an
image and explain the decision, (3) run the delivery gate and
explain what the recipient could and could not see, and
(4) explain what the timeline and review pages show. Record any
confusing wording here and fix it before closing CL-79.
