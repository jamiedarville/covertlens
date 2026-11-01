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

## Structure test (GEO-03) — declared codes only

Structure is `structure_claimed` only when a quantized channel
(support ≥ 0.9 over ≥ 4 elements) maps through a registered
declared code and passes its validator:

| Channel | Code | Validator |
|---|---|---|
| height | alphabet_position | mapped text is/begins with a ≥3-letter word from the declared lexicon |
| gap | timing_ratios | ratios (symbol+1) form a period ≤ 4 motif repeated at least twice |
| lit | bit_packing | bits (MSB-first bytes) decode to printable ASCII |

Otherwise a quantized sequence is `quantized_without_structure` —
a **weak triage signal only** (the legitimate-chart case: its
grid snap is by design, GEO-05). Candidate mapped previews are
labelled `evidence_aid_not_decoded_message`; they are hypotheses
under a declared code, never recovered messages (C-09).

## Operating points

`GeometricConfig` 1.0.0 is an **unfrozen placeholder**
(`enforceable: false`, no points): the geometric family has no
calibration/freeze yet. This detector cannot withhold or fail a
run; CL-42 produces the benchmark on which a freeze could rest.

## Verification

`python -m covertlens geometric-demo`;
`tests/test_geometric.py` asserts the measurement report, the
low clean scores, the chart classification, and the declared-code
structure claim.
