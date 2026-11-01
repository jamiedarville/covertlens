# Benign controls, subfamily coverage and geometric benchmark (CL-42)

Implements: CL-42 (GEO-05, GEO-06). Schema:
[schemas/geo-benchmark.schema.json](../../schemas/geo-benchmark.schema.json).

## What is measured

`run_geo_benchmark` scores the CL-38 dataset plus additional
generated pairs per subfamily, and the benign controls below, with
the CL-40 detector. Ground truth (fixture roles, control
expectations) stays scorer-side (C-07).

- **Per subfamily** (height/position, gap/timing, lit/dark,
  colour-code, angle/tilt — always all five, always separate):
  encoded recall at any-signal and structure levels, benign
  false-structure-claim rate, each with Wilson 95% intervals,
  plus full classification tallies.
- **Prevalence:** encoded vs benign counts and fraction over
  everything scored.
- **Pooled row** is labelled context-only; it never supports a
  coverage claim.

## Benign controls

New generators emit skylines (continuous building heights),
legitimate charts/data visualizations (grid-snapped data values
with a baseline, `data_visualization` context), abstract art
(scattered rectangles), and benign generated scenes (continuous
heights/gaps). They are distinguished by **scene context plus**
the quantization/structure tests: charts legitimately quantize,
so grid snap alone is triage (`quantized_without_structure`);
a *false claim* is specifically a benign item classified
`structure_claimed`. Current run: zero false structure claims
across all controls and benign fixtures; encoded any-signal
recall is reported per subfamily in the benchmark output.

## Guards

- Height or size alone never triggers enforcement: the detector
  remains log-only triage with unfrozen thresholds
  (`enforceable: false`); the benchmark never marks it
  enforceable.
- `general_geometric_coverage_claimed` is always `false` — no
  general geometric coverage is claimed from a single subfamily.
- Scores are evidence, never decoded messages (C-09) and never
  equated with collusion (C-02).

## Verification

`python -m covertlens geo-benchmark-demo`;
`tests/test_geo_benchmark.py` asserts all five subfamilies,
zero benign false claims, recall/false-claim separation with
intervals, and the enforcement guards.
