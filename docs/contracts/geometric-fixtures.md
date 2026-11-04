# Geometric paired fixtures contract (CL-38)

Implements: CL-38 (GEO-07, DT-07), per REQUIREMENTS.md Addendum
§8. The geometric family sits alongside `spatial_lsb`, `jpeg_dct`
and `metadata`; the rendered PNG raster is the delivered, scored
artifact.

## What is built

`covertlens.geometric_fixtures.build_geo_dataset()` — 24 fixtures:

- Five subfamilies × two seeds of clean/encoded pairs:
  `height_position` (8-level height grid, px), `gap_timing`
  (4-level gap grid, px), `lit_dark` (binary lit states),
  `colour_code` (ternary palette), `angle_tilt` (5-level degree
  grid). Encoded attributes sit exactly on the declared grid;
  clean attributes are continuous and kept off-grid by a recorded
  clearance.
- Benign negatives: a legitimate chart (heights grid-snapped *by
  design*; the recorded `chart` context is the discriminator —
  geometry alone must never trigger enforcement, GEO-05), an
  unencoded scene, a benign brightness edit, and a generator
  variation (element count/background).

## Verification model

- Every fixture is verified by **independent re-measurement**
  (`measure_attributes`): column-projection segmentation over the
  raster recovers the attribute sequence and, for encoded
  fixtures, the exact symbol sequence. Renderer parameters are
  never read back.
- The declared payload unit is the symbol sequence per subfamily;
  there is no byte payload and nothing is decoded into a message
  (C-09).
- `geo_manifest` is detector-facing (provenance, hashes, encoder
  config — no ground truth). `geo_ground_truth` requires the
  explicit `scorer` role (DT-04).
- Splits follow the CL-10 lineage-group policy
  (`assign_geo_splits` / `validate_geo_splits`): a scene pair and
  its derivatives never span splits.
- CL-38 shipped fixtures and measurement only; segmentation and
  scoring are CL-39/CL-40, the benchmark CL-42, and the family's
  thresholds froze in CL-54 (re-frozen as `frozen-1.2.0` in CL-78).
- CL-78 generator options, recorded in the encoder config like the
  attacker grid: `alphabet_base` (height letter code A=0 or A=1),
  `level_stride` (every-other-level attacker), `jitter_px` (uniform
  integer jitter on encoded heights and gaps; such fixtures are
  verified by attribute, since past half a step no receiver can read
  them) and a custom colour `palette`. The payload text is never
  recorded: the encoder config is part of the detector-facing
  manifest.

## Verification

`python -m covertlens geo-fixtures-demo` prints the dataset
summary; `tests/test_geometric_fixtures.py` asserts coverage,
re-measurement, ground-truth gating, and split safety.
