# Larger fixture bands across cover textures (CL-68)

Implements: CL-68 (DT-01, DT-02, OP-03, OP-04). Freeze:
`frozen-1.3.0` in
[config/frozen-thresholds.json](../../config/frozen-thresholds.json).
Updates [calibration-freeze.md](calibration-freeze.md) and
[frozen-benchmark.md](frozen-benchmark.md).

## Why

The `frozen-1.1.0` points rested on two development positives per
pixel family and the held-out set on one or two; the high payload band
was uncalibrated, and clean-run stability covered `gradient_noise`
covers only.

## The banded suite (`covertlens.banded_fixtures`)

- Dozens of clean/encoded pairs per family, payload band and texture
  (`gradient_noise`, `smooth`, `blocks`) at 64×48, from the CL-9/CL-22
  builders, so every encoded fixture is verified by independent
  decode. Payload sizes are drawn per pair inside the band's byte
  range (low ≤ 0.05 bpp, medium ≤ 0.25 bpp, high above).
- **Sizing never looks at labels or scores.** Each cell adds pairs in
  a fixed seed order until the CL-10 split hash has placed
  `HELD_OUT_TARGET` (20) pairs in `held_out`. CL-10 lineage groups
  keep each pair in one split.
- **Capacity limits are named.** The CL-9 DCT encoder embeds only in
  |AC| ≥ 2 coefficients; smooth and blocks covers at 64×48 cannot hold
  a high-band payload, so those two cells are `not_constructible` with
  the reason. Metadata is texture-independent: one cell per band,
  cycling textures and both media.
- 2,936 fixtures. `COVERTLENS_BUILD_WORKERS=auto` builds and scores in
  a process pool with byte-identical results (opt-in; CI and
  `make refreeze` set it).

## Recalibration (`calibration_version` 1.1.0)

Development data = banded + CL-9/CL-22 development splits, restricted
to each family's calibrated textures. The measurement behind that
restriction (development-calibrated points, held-out scored):

| Calibrated on | Spatial LSB result |
|---|---|
| `gradient_noise` only | triage 0.217, quarantine 0.244: gradient recall low 17/20, medium 20/20, high 20/20; **every clean smooth PNG false-fails** |
| all three textures | triage 0.101, quarantine 0.523: flags every clean gradient/smooth PNG, enforcement recall ~0 everywhere |

One per-family operating point cannot serve every texture, because
the PoV detectors' clean baselines depend on texture (clean smooth
PNGs score 0.33–0.42, above gradient-noise encoded medium-band
scores). So `spatial_lsb` and `jpeg_dct` calibrate on
`gradient_noise`; `metadata` calibrates on all three. Texture-
conditioned operating points are the follow-up, not this ticket.

Two selection rules change for the three CL-27 families, because real
sample sizes expose them (geometric keeps its CL-54 rules and points):

- **Free-recall triage:** after the highest candidate meeting the
  recall target, triage moves down to the lowest candidate admitting
  no additional development negative. Metadata positives are
  perfectly separable; the CL-27 rule dropped ~5% of them by design.
- **Fail-run above every development negative:** the CL-27 rule put
  fail-run on the next candidate above quarantine, which with dozens
  of samples is quarantine + 0.0002 (one of 60 clean gradient JPEGs
  false-failed in the simulation). Fail-run is now the first
  candidate above the quarantine point and above the highest
  development negative.

Both are recorded per family as `selection_rules`. The rule that
would drop the low band from triage is computed and recorded as
`alternative_triage_without_low_band` (`shipped: false`): it is an
owners' decision (below).

| Family | `frozen-1.1.0` (flag / quarantine / fail-run) | `frozen-1.3.0` |
|---|---|---|
| `spatial_lsb` | 0.2247 / 0.2724 / 0.3201 | 0.2167 / 0.2436 / 0.2487 |
| `jpeg_dct` | 0.0934 / 0.1221 / 0.1508 | 0.0728 / 0.1156 / 0.1205 |
| `metadata` | 0.9023 / 0.9074 / 0.9125 | 0.4506 / 0.9012 / 0.9013 |
| `geometric` | 0.5 / 0.7083 / 1.0 | unchanged |

`frozen-1.2.0` is skipped: the unmerged CL-78 branch uses that label,
and one label must never name two freezes.

The CL-61 second detectors must stay unable to withhold on their own.
The spatial quarantine point fell below `lsb-sample-pairs`' 0.25 cap,
so `SpaConfig` 1.1.0 scales to 0.23 (ROC-AUC is unchanged; scaling
keeps the ranking). `dct-calibrated-histogram`'s 0.09 cap stays below
the DCT quarantine point. A test pins both caps between triage and
quarantine.

## Held-out results (`frozen-1.3.0`, calibrated textures)

| Family | Recall at triage | Low / medium / high | Enforcement precision |
|---|---|---|---|
| `spatial_lsb` | 58/61 = 0.951 [0.865, 0.983] | 17/20, 20/20, 21/21 | 43/43 = 1.0 |
| `jpeg_dct` | 60/61 = 0.984 [0.913, 0.997] | 19/20, 20/20, 21/21 | **37/38 = 0.974 (misses 0.99)** |
| `metadata` | 62/62 = 1.0 [0.942, 1.0] | 20/20, 20/20, 22/22 | 62/62 = 1.0 |

The DCT precision miss is one clean held-out JPEG crossing the
quarantine point. It is reported and the scorecard's `precision`
target is false; it is not tuned away on held-out data (C-07).
Out-of-coverage textures are measured per band (20 positives each
where constructible) in `held_out.families.*.by_texture`.

## Clean-run stability, all three textures

320 fresh clean artifacts per texture (160 PNG, 160 JPEG). A
(texture, medium) cell is claimed when its false-failure rate is
≤ 1%:

| Cell | Verdicts | Claimed |
|---|---|---|
| gradient_noise PNG | 100 log, 58 flag, 1 quarantine, 1 fail-run | yes (0.6%) |
| gradient_noise JPEG | 57 log, 103 flag | yes |
| smooth PNG | 160 fail-run | **no: false-fail 1.0** |
| smooth JPEG | 160 flag | yes (every run flagged) |
| blocks PNG | 160 log | yes |
| blocks JPEG | 103 log, 53 flag, 4 fail-run | **no: false-fail 0.025** |

Claimed cells: 1 false failure in 640 runs (0.16%). The scorecard
lists the two exclusions with their measured rates
(`stability_exclusions`), so the acceptance criterion's second branch
holds; the first (stability over all three textures) does not.

## Owners' decision left open: the low band

Claiming the low payload band (≤ 0.05 bpp) is what sets the triage
points this low: the clean triage flag rate on claimed runs is 0.50
(JPEG 0.64, PNG 0.38). Without the low band, triage would flag 1.3%
of clean JPEGs and 0.6% of clean PNGs, at a development low-band
recall of 0.17 (DCT) and 0.13 (LSB). The shipped freeze keeps the
CL-27 policy (claim every band with development positives); changing
it is a policy decision recorded in `triage_alternatives`.

## Verification

`python -m covertlens calibrate-demo`, `frozen-demo`;
`tests/test_banded_fixtures.py` (sizing, decode, leakage,
determinism), `tests/test_calibration.py` (refined rules, freeze
reproduction, second-detector caps), `tests/test_frozen_benchmark.py`
(≥ 20 held-out positives per calibrated band, stability on all
textures with named exclusions), `tests/test_scorecard.py`
(exclusions named in the scorecard).
