# Leakage-safe splits and independent scoring (CL-10 · DT-03/DT-04)

Deterministic split assignment and scorer-only ground truth for the
CL-9 fixture corpus, in `covertlens.splits`. Machine contract:
[split-manifest.schema.json](../../schemas/split-manifest.schema.json).

## Splits and grouping

Splits are `train`, `calibration` and `held_out`, assigned by a
versioned, seeded `SplitPolicy` (default ratios 0.50 / 0.25 / 0.25).
Assignment is a pure function of the policy seed and the fixture's
**cover-lineage group** (`pattern : cover seed : dimensions`): an
original and every derivative of the same cover — its encoded pair
member, benign edits of that cover, and re-encodings — always land in
one split. The same policy always reproduces the same assignment;
changing the dataset seed creates a new, separately recorded split.

`validate_no_leakage` fails the assignment if any lineage group, any
pair, or any identical `content_hash` appears in two splits, or if a
fixture is unassigned or in an unknown split.

## Held-out record

`held_out_record` (embedded in `assignments.json`) lists the held-out
fixture IDs and count, cover seeds, payload seeds, generator patterns
and full encoder configurations. Fixture records carry no task/agent
identity today, so those dimensions record empty with an explicit
note; they populate automatically when fixture records gain them.

## Label separation

- The **detector-facing** export (`detector/`) contains train and
  calibration images plus a hash-only manifest. Held-out fixtures are
  excluded entirely — not merely unlabelled.
- The **scorer-side** ground truth (`scorer/ground-truth.json`) holds
  held-out payloads, and `scorer_ground_truth(...)` raises
  `PermissionError` unless called with `role="scorer"`.
- Held-out labels are never used for calibration or threshold work
  (C-07; freezing stays with CL-27).

## Independent recovery

`verify_recovery` re-decodes every encoded fixture through the CL-9
independent read paths (PNG LSB reader; JPEG coefficient parser) and
requires bit-exact payload recovery, returning checked/passed counts
and any failing fixture IDs. A recovery failure is a fixture or
infrastructure error, never evidence of collusion (C-02).

## Out of scope here

Detector scoring against these splits (CL-14/CL-15), delivered-vs-
withheld replay experiments (CL-21) and threshold freezing (CL-27)
consume these artifacts but are separate tasks.
