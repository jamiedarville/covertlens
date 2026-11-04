# Quantization and structure tests contract (CL-40)

Family integration (CL-44): geometric is the fourth channel
family in `manifest.FAMILIES` and the allowed-channel manifest
(1.1.0). `analyze_all_bytes` attaches the finding for parsed
PNGs and baseline JPEGs. Under the CL-54 freeze
(`config/frozen-thresholds.json`, now `frozen-1.4.0`) a
`structure_claimed` finding is quarantined; quantization alone
never withholds (the quarantine point is calibrated above the
non-structure score ceiling, CL-78). Trace join, run report, review
export, pin and the release scorecard carry it like every
other family. The scorecard's geometric section cites the
CL-42 benchmark per subfamily, never pooled.

Implements: CL-40 (GEO-02, GEO-03). Schema:
[schemas/geometric-finding.schema.json](../../schemas/geometric-finding.schema.json).
Detector `geometric-quantization-structure` 3.0.0 (config 3.0.0,
CL-78) over CL-39 segmentations.

## Quantization test (GEO-02) — a measurement, not a verdict

Each channel (height, gap, lit levels, colour, tilt angle) has
its grid **discovered from the sequence** (CL-43,
`covertlens/grid.py`): a Rayleigh step sweep from twice the
channel tolerance to half the observed range, offset from the
resultant phase, residuals folded to [-s/2, s/2). Reports carry
the discovered step/offset, a digest of the symbol sequence (never
the sequence, CL-78), per-element residuals, supporting
count/fraction, rms/max residual, levels used, Rayleigh R, and
`null_exceedance` from two seeded nulls (uniform draws over the
observed range; resampled fractional parts) — the fraction of null
draws whose best R reaches the observed R.

**Decode margin (CL-78).** A receiver that rounds to the nearest
level reads any value within half a step of it, so ±1–2 px of
jitter costs an attacker nothing. Support is therefore measured at
`decode_tolerance = max(channel tolerance, 0.25 × step)`. A channel
is **decodable** when support at that margin is ≥ 0.9 with at least
two levels used; decodable channels get the structure test. A
channel is **quantized** (the triage signal) when it is decodable
and also: `null_exceedance` ≤ 0.05, R ≥ 0.6, rms within the decode
tolerance, and (except angle) ≥ 0.9 of residuals inside half the
decode tolerance. At small steps that last gate is the measurement
rounding band, which keeps few-level integer sequences and "clean"
scenes whose values bunch between grid lines from passing as grids.

**Colour (CL-78)** has no fixture palette any more. Element colours
are clustered (radius 12, Euclidean RGB); clusters used by two or
more elements are the palette, in canonical hue-then-value order.
A palette is a grid only when its levels are ≥ 24 apart, and an
element supports a level within a quarter of that separation. A
continuous run of shades splits into near-touching clusters and
fails; three distinct blues pass. The structure test tries every
relabelling of up to four levels, and the null takes the same
maximum.
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
reports an `attacker_grid` row per subfamily, plus an
every-other-level attacker (`level_stride=2`, CL-78) whose step is
only identifiable up to a factor of two, and jittered attackers
(±1, ±2, ±3 px).

## Scene context (CL-45, GEO-05)

The detector takes `declared_context` — the geometric channels
declared legitimate for this task before the run (manifest
`declared_geometric_channels`, mirroring the metadata
exceptions rule). Classification of a quantized primary channel:

`analyze_all_bytes(declared_context=...)` passes it in production
(CL-78); with no argument the shipped manifest's declarations are
used (none). The gate records a run's declaration
(`InterceptionGate.declare_scene_context`, refused once the run has
a delivery) and the web API takes it on `POST /api/gate/runs` and
`POST /api/analyze` (`declared_channels`).

| Situation | Classification | Grade |
|---|---|---|
| structure on any undeclared channel | `structure_claimed` | enforceable-grade (quarantined) |
| structure on a declared channel at the stricter level | `structure_claimed` | enforceable-grade |
| structure on a declared channel at the undeclared level only | `quantized_declared_channel` | `triage_declared_structure` (flags; score in the triage band) |
| a declared channel is quantized, no structure claim | `quantized_declared_channel` | log (score 0) |
| quantized, nothing declared, no structure | `quantized_without_structure` | triage |

A declaration lowers the prior; it is never a blanket bypass
(CL-78). Before CL-78 a declared channel that spelled a word logged
with score 0.

Inferred **chart-likeness** (0–1) is computed from the
segmentation — baseline/axis component, near-equal widths and
gaps, small text-like components near the axis — reported in
evidence (`chart_likeness`) and used as a prior on the height
channel only (`height_prior` annotation). It never decides a
classification by itself: charts and encoded scenes with the
same height sequence are separated by the declaration plus the
quantization/structure tests, not by the likeness score.

## Structure test v2 (GEO-03, CL-46) — declared codes + shuffle null

Structure is `structure_claimed` only when a decodable channel
maps through a registered declared code **and beats a
symbol-shuffle null at the stated level** over at least
`structure_min_symbols` (8) symbols. Every decodable channel is
tested, not just the top-scoring one (CL-78), and the most severe
result wins. The level is family-wise: `structure_alpha` (0.01) is
split (Bonferroni) over the tests in the image, where one test is
one statistic (trigram or periodicity) maximised over a channel's
codes and symbol frames, with the shuffle null taking the same
maximum. 1,999 shuffles, stopped early once the hit count rules out
the level. Measured on 2,000 rendered random 12-bar payloads: 1.15%
claimed, against the stated 1%. Mapped text below 90% printable
scores −∞ in the observed sequence and in every shuffle; the old
`?` marker for invalid symbols counted as printable (CL-78).

**Minimum length.** Below 8 symbols the shuffle null cannot reach
the level for a five-letter word (5! = 120 orderings), so shorter
sequences are not tested and top out at quantization (triage).

Every channel has at least one applicable code:

| Channel | Codes | Statistic vs shuffle null |
|---|---|---|
| height | `alphabet_position_a0`, `alphabet_position_a1`, `base_k_digits` (3×base-8/byte) | trigram log-likelihood (committed word list, hashed into the config) + printable fraction |
| gap | `timing_ratios` | periodicity and lag-1..8 autocorrelation of ratios |
| lit | `bit_packing` (MSB-first bytes) | printable fraction AND trigram likelihood |
| colour | `base_k_digits` (ceil(log_k 128) base-k digits/byte over the k discovered levels; 5 for k=3), `ordinal_rank` | trigram / rank-pattern periodicity, every relabelling |
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

`GeometricConfig` holds measurement parameters only
(`status: measurement_parameters`). The ladder points are the
CL-54 freeze in `config/frozen-thresholds.json` (`frozen-1.4.0`
since CL-78). Score bands: a structure claim scores 0.75–0.95; any
other finding scores at most 0.5. The freeze calibrates the
geometric quarantine point strictly above 0.5, so structure is
quarantined and quantization alone can only flag. Run failure stays
reserved (fail_run at 1.0, unreachable).

**Known weakness.** The A–H letter-position height code is weak
with the 313-word trigram model: on varied A–H words about half
beat the shuffle null (DECAF, HEADED and BEADED do; FACADE, BADGE
and HEDGE do not). ASCII text in base-8 digits is detected far more
reliably. The benchmark reports this per subfamily.

## Verification

`python -m covertlens geometric-demo`;
`tests/test_structure_v2.py` asserts per-subfamily structure
detection from pixels, varied structured rows (distinct images and
payloads), the no-mapped-text and no-symbols finding, and the
reviewer-gateway roles; `tests/test_geometric_cl78.py` covers
jitter, every-channel structure, declared-channel priors, the
printable fix, palette discovery and the minimum length;
`tests/test_geometric.py` covers the measurement report and the
chart classification.
