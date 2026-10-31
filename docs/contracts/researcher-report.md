# Researcher run report and triage workflow (CL-25 · REV-05)

`covertlens.report.build_run_report` assembles one run for review
from the CL-16 join and CL-24 episode context. Machine contract:
[run-report.schema.json](../../schemas/run-report.schema.json).

## What the report contains

- **Originals by reference:** artifact ID, exact version and
  `content_hash` per original, with its component findings. Original
  bytes are never embedded in the report — byte access stays on the
  audited CL-18/R-08 reviewer path.
- **Component findings and verdicts:** every delivery carries its
  per-family findings (family, detector name@version, score,
  coverage, limitations) and its gate verdict reference, so no family
  is hidden inside a blended score.
- **Prior context:** participants (agent identities with sent /
  received / action history) and episodes from the CL-24 context.
- **Action timeline:** the run's events in `seq` order, with the
  CL-16 candidate linkage (`causation_claimed: false` throughout).

## Triage workflow

`triage_queue` lists every delivery, highest max-score first,
starting at disposition `unresolved`. `apply_review` records a
reviewer disposition — `benign`, `unresolved`, `suspected`,
`demonstrated_transfer`, or `policy_supported` — and returns an
updated, revalidated report copy (the input is not mutated).
`demonstrated_transfer` requires a recorded `demonstrated_basis` in
independent recovery/action evidence: a detector score can never
create that disposition, and `validate_run_report` rejects a basis-
free claim.

## Evidence aids, not decoded messages

Score bars ("heatmaps") and scores carry the label
`evidence_aid_not_decoded_message` at report and per-aid level, and
validation requires it. They summarise detector evidence for
prioritisation; they are not decoded content, and the report never
equates them with demonstrated collusion (C-02).

## Out of scope here

Adjudication pilots (CL-30), export packaging (CL-33) and
prevention ablations (CL-31) consume this report but are separate
tasks.
