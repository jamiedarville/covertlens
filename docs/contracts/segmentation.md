# Segmentation and attribute extraction contract (CL-39, CL-52)

Implements: CL-39 (GEO-01), CL-52 robustness. Schema:
[schemas/segmentation.schema.json](../../schemas/segmentation.schema.json).
Detector-facing layer over original PNG/JPEG bytes and the CL-38 fixtures.

## Method (versioned: `geometric-segmenter` 1.1.0)

- **Original bytes only.** PNG is decoded losslessly at native
  resolution (never resized/recompressed). Baseline JPEG is
  reconstructed to pixels (`covertlens/jpeg_pixels.py`) and
  measured with a recorded fidelity limitation: results carry
  `media_kind: "jpeg"`, the segmentation `detail` notes the lossy
  reconstruction, and geometric findings append the CL-52
  fidelity limitation. Progressive or other out-of-subset JPEGs
  return `unsupported_media`.
- Background starts with a bucketed modal perimeter-colour vote
  (`background_bucket_shift`, default 4), followed by a 4-connected flood
  from matching border pixels. The flood absorbs
  smooth gradients with per-step RGB distance at most
  `background_step_tolerance` (4.0). Remaining foreground uses a
  two-threshold Euclidean-RGB distance decision (CL-52): pixels
  beyond `background_distance_floor` (3.0) form a candidate mask,
  cleaned by a 3×3 morphological open/close pass; a component is
  an element when any pixel exceeds
  `background_distance_tolerance` (24.0), or when it is a coherent
  flat region (≥ `coherent_colour_fraction` 0.9 of pixels sharing
  its modal colour) that does not touch the border — the
  lit-window case. The exact-colour foreground test is gone.
  `preserve_thin_components` (default true) restores coherent components
  narrower than the 3-pixel kernel, provided they meet the component area
  and colour-coherence thresholds. This retains thin chart axes and dashes
  while isolated speckles remain filtered.
  All tolerances are recorded in `SegmenterConfig` and in every
  result's `tolerances` block.
- **Declared pixel decoder subsets.** PNG supports non-interlaced 8/16-bit
  grey, RGB, grey+alpha and RGBA, and 8-bit palette PNG; 16-bit samples
  retain the high byte and alpha is ignored, not composited. JPEG supports
  8-bit sequential Huffman SOF0/SOF1, 4:4:4/4:2:2/4:2:0 and grayscale,
  optimized tables, restart intervals and Adobe-marked RGB. JPEG chroma
  uses nearest-neighbour upsampling. Other encodings fail explicitly.
  These geometry decoders do not expand the frozen CL-13 coefficient
  parser: the integrated four-family/web pipeline still requires its
  declared 8-bit baseline 4:4:4 JPEG subset. Wider pixel-decoder support
  is available through `segment_image` / `analyze_geometric_bytes`.
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
The crops isolate objects above connected baselines/rails; passing five
segmentation checks does not establish general natural-image detection.
`tests/test_png_pixels.py` checks ordinary row filters/colour types and bounded
inflation. `tests/test_jpeg_pixels.py` compares against independently authored
libjpeg reference outputs and checks explicit failures. `tests/test_webapp.py`
checks a supported JPEG upload's overlay, fidelity limitation and pixel cap.
