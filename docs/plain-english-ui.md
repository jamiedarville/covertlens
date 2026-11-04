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
| (verdict) log / flag / quarantine / fail_run | Let it through and record it / …but flag it for attention / Hold the image back for review / Hold the image back and stop the session (exact value kept alongside) |
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

- [x] `/` Landing — one-paragraph explanation, "How it works"
      steps, colour key, skyline demo with traffic-light results,
      every other page described in one sentence, loading and
      error states
- [x] `/analyze` — purpose, drop zone (accepted files, what
      happens), ready-made examples (incl. why the button is
      disabled, empty list), checking / success / too-large /
      timeout / unsupported / failed states, result header
- [x] Results — traffic-light answer first (see below), one
      light per test, colour key; the delivery decision, per-check
      cards (score meaning, limitations, not-checked state),
      cut-off table and evidence tables sit behind "See the
      technical evidence"
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

## Traffic-light results

Feedback on the first wording pass: the results still read like a
lab report. The Analyze result now answers one question first, "Is
there a chance of collusion?", with a traffic light:

| Colour | Words shown | Ladder verdict (unchanged) | What happens to the image |
|---|---|---|---|
| Green | No evidence of collusion | `log` | passed on as normal |
| Orange | Potential collusion | `flag` | passed on, marked for a person to check |
| Red | High potential for collusion | `quarantine`, `fail_run` | held back (`fail_run` also stops the session) |
| Grey | Not checked / Not tested | no result, cut-offs not frozen, or the file could not be checked | nothing decided |

Rules:

- The colours are read from `decision.verdict` and
  `decision.per_family[].verdict` in the `/api/analyze` response,
  so they use the same frozen cut-offs as the delivery gate. The UI
  compares no scores and adds no thresholds.
- All four tests are always listed. A test with no result, or whose
  cut-offs are not frozen, is grey with a reason (for example "only
  works on JPEG photos"). Grey is never shown as green.
- Colour is never the only signal: every light has a symbol
  (✓ ! ✕ –) and its colour name in words.
- The simple view shows no scores, cut-offs, field names or
  versions (pinned by `app/frontend/tests/traffic-light.test.tsx`).
  Everything the page showed before is one click away under "See
  the technical evidence".
- Every result ends with the colour key and "warning signs, not
  proof".
- The same coloured dot sits beside decisions on the gate and
  review pages.

Plain test names used in the simple view (technical names stay in
the technical evidence):

| Family | Simple name | What it looks for |
|---|---|---|
| `spatial_lsb` | Tiny colour changes | a message in colour changes too small to see |
| `jpeg_dct` | JPEG compression | a message in how a JPEG photo is compressed |
| `metadata` | File details | a message in the text stored inside the file |
| `geometric` | Shapes and patterns | a message spelled out by shape sizes, gaps or colours |

Words, colours and the light logic live in `src/format.ts`
(`lightForVerdict`, `LIGHT_*`, `TEST_*`, `verdictNext`) and
`src/components/TrafficLight.tsx` (`SimpleResult`, `ColourKey`,
`VerdictLight`, `testLights`).

## Simple first, technical breakdown second (every page)

Second round of feedback: the other pages needed the same treatment
as the result. Every page now follows one pattern:

1. A short heading and one or two plain sentences saying what the
   page is for.
2. The main action or answer, in plain words: numbered steps on the
   hands-on pages, a coloured headline or a plain summary on the
   report pages.
3. **"See the technical breakdown"** at the end: exact IDs,
   fingerprints, scores, audit tables, charts and the project's own
   wording. **"Show advanced settings"** does the same for form
   options most people never change. Both are link-style buttons
   (`Reveal`, `TechnicalBreakdown`, `AdvancedSettings` in
   `src/components/Help.tsx`). The hidden block stays in the page,
   so values typed into it survive closing it.

| Page | Visible by default | Moved behind the link |
|---|---|---|
| Menu | Short names on one line (Check an image, Make a test image, Delivery gate, Review images, Timeline, Accuracy, Leaderboard, Release decision, API docs) | — |
| Make a test image | Four plain hiding-place choices, the message (or amount) to hide, one button | Seeds, number of bars, kind of message, grid choice; saved settings and fingerprint |
| Delivery gate | Steps 1–4: who you are, start, send, check (coloured suggestion) and decide (plain choices with dots), what each side sees; a one-line safety check | Session and agent names, declared measurements, re-open, route; exact delivery table, event list, audit counts and table |
| Review images | Steps 1–3: session, pick an image, plain judgement choices; second opinion; a one-line record check | Check scores, possible hidden reading, IDs and fingerprint, full audit chain, sealed download |
| Timeline | One plain line per image ("Held back. The other agent never saw it."), counts, a "worth a look" note for repeated small signals | Delivery table with IDs, fingerprints and missing links; participants; small-signal table; later actions |
| Accuracy | "Spotted 95 out of 100 hidden messages", "right 97 out of 100 times" per test, the shapes test's range, speed by image size | Glossary, all six tabs, charts, exact values and provenance |
| Leaderboard | Standings with plain hiding places and coloured decisions; the three levels as stacked choices | Checker version, older boards, exact entry values and packing density |
| Release decision | Coloured headline ("Released, with known limitations"), targets met, "What it does well" / "What it doesn’t do yet" in plain words | Exact decision and target names, the project’s reasons and known limitations in its own words, changed targets, raw evidence, download |

Rules kept from the wording pass: nothing is removed, only moved;
grey/"not checked" is never shown as green; colour always comes with
a symbol and words; no detection, threshold, permission or API
behaviour changed. Plain role names ("Researcher — can run the gate
and make decisions") replace the role picker's long note, with the
exact permissions folded underneath. Pinned by
`app/frontend/tests/simple-pages.test.tsx`.

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
