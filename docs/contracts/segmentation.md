# Segmentation and attribute extraction contract (CL-39)

Implements: CL-39 (GEO-01). Schema:
[schemas/segmentation.schema.json](../../schemas/segmentation.schema.json).
Detector-facing layer over the CL-38 geometric fixtures.

## Method (versioned: `geometric-segmenter` 1.0.0)

- **Original bytes only.** PNG is decoded losslessly at native
  resolution (never resized/recompressed). JPEG returns
  `unsupported_media` — its rasterization would blur the exact
  values being measured; a JPEG path needs its own fidelity
  study rather than silent degradation.
- Background = modal border colour; repeated elements are
  4-connected foreground components ≥ 8 px (connected-component
  labelling — deliberately a different implementation from the
  CL-38 column-projection fixture verifier).
- **Reading order:** components grouped into rows by ≥50%
  vertical overlap, rows top-to-bottom, left-to-right within a row.
- Per element: bbox (left/top/width/height), area, gap-to-next,
  tilt angle (row-centroid regression, tolerance ±3.5°), dominant
  colour with nearest declared-palette index and distance,
  brightness (attribute tolerance ±1.6 px).

## Recorded failure modes (explicit, never silent)

`no_foreground`, `too_few_elements`, `unsupported_media`,
`limit_exceeded` (10 MiB / 2 MP segmenter caps), `corrupt_input`.
Every result records the segmenter name/version, tolerances and
the failure-mode table. Extraction emits numeric sequences only —
`decoded_message` is always null (C-09); whether a sequence is
encoded is CL-40's question.

## Verification

`python -m covertlens segmentation-demo` prints per-subfamily
extraction on the CL-38 encoded fixtures;
`tests/test_segmentation.py` asserts reading order and the
height/gap/colour/angle sequences against scorer ground truth,
plus every failure mode.
