# Quantization and structure tests contract (CL-40)

Implements: CL-40 (GEO-02, GEO-03). Schema:
[schemas/geometric-finding.schema.json](../../schemas/geometric-finding.schema.json).
Detector `geometric-quantization-structure` 1.0.0 over CL-39
segmentations of CL-38 scenes.

## Quantization test (GEO-02) — a measurement, not a verdict

Each channel (height, gap, lit levels, colour palette distance,
tilt angle) is fitted to its declared CL-38 grid. Reports carry
grid base/step, the recovered symbol sequence, per-element
residuals, supporting count/fraction, and residual statistics —
there is no bare “pattern detected” output. A channel is only
*applicable* if it actually varies: a constant channel (upright
bars at angle 0, fixed scene heights) is trivially on-grid and
carries no sequence evidence, so it is marked inapplicable and
scored 0.

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
