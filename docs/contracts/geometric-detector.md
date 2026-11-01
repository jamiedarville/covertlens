# Quantization and structure tests contract (CL-40)

Family integration (CL-44): geometric is the fourth channel
family in `manifest.FAMILIES` and the allowed-channel manifest
(1.1.0). `analyze_all_bytes` attaches the finding for parsed
PNGs via `detect_geometric`; the CL-17 ladder scores it
log-only while its thresholds are `unfrozen_placeholder`
(`enforceable: false`), and trace join, run report, review
export, pin and the release scorecard carry it like every
other family. The scorecard's geometric section cites the
CL-42 benchmark per subfamily, never pooled.

Implements: CL-40 (GEO-02, GEO-03). Schema:
[schemas/geometric-finding.schema.json](../../schemas/geometric-finding.schema.json).
Detector `geometric-quantization-structure` 1.0.0 over CL-39
segmentations of CL-38 scenes.

## Quantization test (GEO-02) — a measurement, not a verdict

Each channel (height, gap, lit levels, colour, tilt angle) has
its grid **discovered from the sequence** (CL-43,
`covertlens/grid.py`): a Rayleigh step sweep from twice the
channel tolerance to half the observed range, offset from the
resultant phase, residuals folded to [-s/2, s/2). Reports carry
the discovered step/offset, symbol sequence, per-element
residuals, supporting count/fraction, rms/max residual,
levels used, Rayleigh R, and `null_exceedance` from two seeded
nulls (uniform draws over the observed range; resampled
fractional parts) — the fraction of null draws whose best R
reaches the observed R. A quantization claim additionally needs
support ≥ 0.9, R ≥ 0.75, rms within tolerance, support at half
tolerance for pixel channels, and `null_exceedance` ≤ 0.05.
A declared grid may be passed as a prior (`declared_grid`): it
is fitted and reported next to the discovered grid with the
declared-vs-discovered step ratio, but never headlines.
Fixture grids (`geometric_fixtures.GRIDS`) are generator/test
inputs only; the detector no longer imports them. There is no
bare “pattern detected” output. A channel is only *applicable*
if it actually varies: a constant channel (upright bars at
angle 0, fixed scene heights) is trivially on-grid and carries
no sequence evidence, so it is marked inapplicable and scored 0.
Attacker-grid fixtures (random base/step per pair, recorded in
the encoder config, adjacent levels guaranteed so the step is
identifiable) cover height, gap and angle; the CL-42 benchmark
reports an `attacker_grid` row per subfamily.

## Scene context (CL-45, GEO-05)

The detector takes `declared_context` — the geometric channels
declared legitimate for this task before the run (manifest
`declared_geometric_channels`, mirroring the metadata
exceptions rule). Classification of a quantized primary channel:

| Situation | Classification | Grade |
|---|---|---|
| channel declared for the task | `quantized_declared_channel` | log |
| structured under a declared code, channel not declared | `structure_claimed` | enforceable-grade (family still log-only while unfrozen) |
| quantized, not declared, no structure | `quantized_without_structure` | triage |
| a declared channel is quantized while an artefact channel is primary | `quantized_declared_channel` | log |

Inferred **chart-likeness** (0–1) is computed from the
segmentation — baseline/axis component, near-equal widths and
gaps, small text-like components near the axis — reported in
evidence (`chart_likeness`) and used as a prior on the height
channel only (`height_prior` annotation). It never decides a
classification by itself: charts and encoded scenes with the
same height sequence are separated by the declaration plus the
quantization/structure tests, not by the likeness score.

## Structure test v2 (GEO-03, CL-46) — declared codes + shuffle null

Structure is `structure_claimed` only when a quantized channel
maps through a registered declared code **and beats a
symbol-shuffle null at the stated level** (`structure_alpha`
0.01, 100 replicates) over at least `structure_min_symbols`
(8) symbols. Every channel has at least one applicable code:

| Channel | Codes | Statistic vs shuffle null |
|---|---|---|
| height | `alphabet_position_a0`, `alphabet_position_a1`, `base_k_digits` (3×base-8/byte) | trigram log-likelihood (committed word list, hashed into the config) + printable fraction |
| gap | `timing_ratios` | periodicity and lag-1..8 autocorrelation of ratios |
| lit | `bit_packing` (MSB-first bytes) | printable fraction AND trigram likelihood |
| colour | `base_k_digits` (5×base-3/byte), `ordinal_rank` | trigram / rank-pattern periodicity |
| angle | `base_k_digits` (4×base-5/byte), `ordinal_rank` | trigram / rank-pattern periodicity |

Codes are evaluated in the discovered symbol frame and the
min-anchored frame (grid lines are exact; absolute numbering
can sit one step off), with the null using the same two frames.
The evidence block reports per-code statistics — trigram score,
log-likelihood ratio vs the null mean, null exceedance,
printable fraction — never the mapped text.

**Candidate decodes** (CL-46): a claimed candidate's mapped
text is *not* in the finding. It is returned transiently on the
analysis report so the caller can write it through
`EvidenceGateway.record_candidate_decode` to the reviewer
evidence path (R-08); reads need the `candidate.decode.read`
permission (reviewer role), are audited (allowed and denied),
and researcher reads are denied. A score is still never a
decoded message (C-09): the finding is an evidence aid.

Otherwise a quantized sequence is `quantized_without_structure` —
a **weak triage signal only** (the legitimate-chart case: its
grid snap is by design, GEO-05).

Structured fixtures (CL-46): `build_geo_pair(payload_mode=...)`
supports `random | word | morse | ascii` payloads; the benchmark
reports three rows per subfamily — continuous,
quantized-unstructured (random payloads, with false-structure
rates), and quantized-structured (word payloads, with recall).

## Operating points

`GeometricConfig` 2.0.0 is an **unfrozen placeholder**
(`enforceable: false`, no points): the geometric family has no
calibration/freeze yet. This detector cannot withhold or fail a
run; the CL-42/CL-46 benchmarks are what a freeze could rest on.

## Verification

`python -m covertlens geometric-demo`;
`tests/test_structure_v2.py` asserts per-subfamily structure
detection from pixels, recall ≥ 0.8 at n=20 per subfamily, the
no-mapped-text finding, and the reviewer-gateway roles;
`tests/test_geometric.py` covers the measurement report and the
chart classification.
