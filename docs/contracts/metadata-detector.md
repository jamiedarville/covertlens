# Metadata scoring and three-family integration (CL-23 · DET-05)

`covertlens.metadata` scores the metadata family and provides the
integrated analysis pipeline. The detector reads ancillary entries
from the exact original bytes (PNG `tEXt`/`iTXt`, JPEG APP segments,
per CL-22) on a CL-13 parsed result; payload entry *values* are never
copied into findings — keyword, source, byte count and classification
only.

## Scoring rule (versioned)

`metadata-ancillary-entries` v`1.0.0`, `MetadataConfig` v`1.0.0`:

| Entries present | Classification | Score |
|---|---|---|
| Declared payload keyword (`CovertLensPayload`) | `declared_payload` | strong (0.9 base, size-nudged to 1.0) |
| Only unknown keywords | `unknown_metadata` | weak (0.3 per entry, capped below the payload base) |
| Only allowed task metadata, or none | `allowed_task_metadata` / absent | 0.0 (benign) |

Allowed task metadata is the CL-22 exception set (`Title`,
`Description`, `TaskReference`): presence of metadata alone never
scores. That is what separates supported encoding evidence from
benign controls — and the recorded limitation is symmetric: a payload
hidden under an allowed keyword evades the strong rule. Absence of
metadata on a parsed image is recorded as a score-0 finding, not
silence; failed parses get no finding (C-02).

## Integration: all families, individually visible

`analyze_all_bytes(data)` performs one CL-13 parse and attaches every
applicable finding — LSB for PNG, DCT for JPEG, metadata for both —
to the single `AnalysisResult`. Families are never blended:
`analyze_and_decide(data, config)` runs the result through the CL-17
ladder with the caller's pinned `ThresholdConfig` (version recorded
on the decision; all three families present in the config, shipped
unfrozen until CL-27) and the decision's `per_family` rows keep each
family's score, detectors and verdict separate.

`benchmark_metadata` mirrors the CL-14/15 paired benchmarks over the
CL-22 fixtures: false positives and recall by payload band over a
threshold sweep with Wilson intervals, per-band ROC-AUC against all
negatives (`schemas/metadata-benchmark.schema.json`).

## Out of scope here

Sequence/context scoring (CL-24), threshold freezing (CL-27) and
researcher presentation (CL-25) consume these findings but are
separate tasks.
