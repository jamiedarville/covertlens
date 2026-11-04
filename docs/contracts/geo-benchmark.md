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

- Height or size alone never triggers enforcement. Under the CL-54
  freeze (`frozen-1.2.0`) a `structure_claimed` finding is
  quarantined; every other finding is decided by the frozen ladder
  and the guard `height_or_size_alone_never_enforces` checks that
  none of them withholds (`enforcement.mode: frozen_ladder`).
- `general_geometric_coverage_claimed` is always `false` — no
  general geometric coverage is claimed from a single subfamily.
- Scores are evidence, never decoded messages (C-09) and never
  equated with collusion (C-02).

## Verification

## Rows added in CL-78 (benchmark 2.0.0)

- **Structured rows are varied.** `build_structured_pair` draws its
  payload from a development or held-out pool (disjoint, and no
  word is in the trigram model's word list) and its grid or palette
  from the index. Each row reports `distinct_images` and
  `distinct_payloads`; the check `structured_rows_use_distinct_images`
  replaces the old recall ≥ 0.8 check, which held only because the
  five pairs were one image.
- **Jittered attacker** (`jittered_attacker`): ±1, ±2 and ±3 px on
  height (10 px step) and gap (6 px step), structured and random
  payloads, with an unjittered baseline on the same payloads and
  `receiver_decodable` (jitter under half a step). Check: ±1 px costs
  at most one structure claim against the baseline.
- **Every-other-level attacker** (`every_other_level_attacker`):
  payloads that never use two adjacent levels; the discovered step
  may be twice the encoder's, and both count as a match.
- **Random-payload false structure** (`random_payload_structure`):
  100 random height payloads, the measured claim rate, and a
  one-sided binomial test against the stated level.
- **Scene context.** The positive control is the fixed DECAF scene,
  not the first random payload a seed scan happened to claim; the
  same scene with height declared must not log at score 0
  (`structured_declared_not_silently_logged`).

## Verification

`python -m covertlens geo-benchmark-demo`;
`tests/test_geo_benchmark.py` asserts all five subfamilies,
zero benign false claims, recall/false-claim separation with
intervals, and the enforcement guards.
