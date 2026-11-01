# Segmentation and attribute extraction contract (CL-39, CL-52)

Implements: CL-39 (GEO-01), CL-52 robustness. Schema:
[schemas/segmentation.schema.json](../../schemas/segmentation.schema.json).
Detector-facing layer over the CL-38 geometric fixtures.

## Method (versioned: `geometric-segmenter` 1.1.0)

- **Original bytes only.** PNG is decoded losslessly at native
  resolution (never resized/recompressed). Baseline JPEG is
  reconstructed to pixels (`covertlens/jpeg_pixels.py`) and
  measured with a recorded fidelity limitation: results carry
  `media_kind: "jpeg"`, the segmentation `detail` notes the lossy
  reconstruction, and geometric findings append the CL-52
  fidelity limitation. Progressive or other out-of-subset JPEGs
  return `unsupported_media`.
- Background = modal perimeter colour. Foreground is a
  two-threshold Euclidean-RGB distance decision (CL-52): pixels
  beyond `background_distance_floor` (3.0) form a candidate mask,
  cleaned by a 3×3 morphological open/close pass; a component is
  an element when any pixel exceeds
  `background_distance_tolerance` (24.0), or when it is a coherent
  flat region (≥ `coherent_colour_fraction` 0.9 of pixels sharing
  its modal colour) that does not touch the border — the
  lit-window case. The exact-colour foreground test is gone.
  All tolerances are recorded in `SegmenterConfig` and in every
  result's `tolerances` block.
- Repeated elements are 4-connected foreground components ≥ 8 px
  (connected-component labelling — deliberately a different
  implementation from the CL-38 column-projection fixture
  verifier).
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
plus every failure mode; `tests/test_real_images.py` asserts
element counts ±1 on five committed real images
(`tests/data/real/`, licences in its README).
