# Stronger pixel detectors (CL-61)

Traces DET-03, DET-04, OP-06. No dependencies.

## Why

The CL-14/CL-15 pairs-of-values (PoV) chi-square detectors are
defeated by LSB matching (+/-1 embedding), which their own
limitations list admits: matching moves a sample/coefficient by one
step instead of rewriting its LSB in place, so value pairs are not
equalised the way the PoV statistic expects. CL-61 adds a second,
individually visible detector to each pixel family, plus a +/-1
fixture suite to show the gain. No thresholds are refrozen: the
CL-27/CL-54 frozen points stay calibrated on the original PoV
detectors (see "Frozen-benchmark pinning" below).

## Fixtures (+/-1 suite)

`covertlens.fixtures.build_matching_dataset()` builds clean/encoded
pairs on a new `smooth_field` cover pattern (low-frequency sinusoid
field, no per-sample noise). Pair-based detection needs spatially
correlated covers — the CL-9 noisy patterns destroy adjacent-sample
correlation at the LSB level, which is recorded as a limitation,
not worked around silently.

| Family | Encoder | Embedding | Suite |
|---|---|---|---|
| `spatial_lsb` | `lsb-matching-png` | Scattered +/-1 sample matching; LSB ends as the payload bit, verified by seeded independent decode | 8 cover seeds × 12/64/192 payload bytes at 64×48 (low/medium/high bands) |
| `jpeg_dct` | `dct-matching-jpeg` | +/-1 matching on \|AC\| ≥ 2 magnitudes; the carrier set cannot shrink (magnitude 2 steps to 3), so the CL-9 independent decode still verifies | 6 cover seeds × 8/16 payload bytes at 64×48 (low band; smooth covers have few carriers) |

Encoded fixtures are verified by independent decode
(`Fixture.verify_payload` dispatches on the encoder name), exactly
like the CL-9 replacement fixtures.

## Spatial: sample-pair detector

`covertlens.lsb.detect_lsb_pairs` emits `lsb-sample-pairs` v1.0.0
(`SpaConfig` v1.0.0) alongside `lsb-pov-chisquare`:

- **Statistic:** non-overlapping horizontally adjacent same-channel
  sample pairs (the Dumitrescu sample-pair layout). Embedding
  randomises sample LSBs independently, driving the pair LSB
  agreement rate toward 0.5; the score is the pair-LSB randomness
  `1 - 2*|agreement - 0.5|`, clipped to [0, 1]. Evidence records the
  raw agreement, the smooth-pair fraction, pair counts and a
  `reliable` flag.
- **Reliability gate:** where adjacent-pair correlation is absent
  (smooth-pair fraction below `smooth_min_fraction`, or too few
  pairs) the statistic cannot speak: the score is gated to 0 and
  the limitation is recorded — the same fail-closed shape as the
  PoV insufficient-coverage case, never a silent clean score.
- **Score cap:** the randomness is scaled by `score_scale` (0.25),
  so this unfrozen detector's maximum score stays below the frozen
  spatial quarantine point (0.272414). It can contribute triage
  evidence under the frozen ladder but can never by itself cause
  withholding before a dedicated freeze calibrates points for it.
- **Applicability:** parsed PNG with known geometry; JPEGs and
  failed parses get no finding.

## DCT: calibrated-histogram detector

`covertlens.dct.detect_dct_calibrated` emits
`dct-calibrated-histogram` v1.0.0 (`DctCalibratedConfig` v1.0.0)
alongside `dct-coefficient-pov-chisquare`:

- **Statistic:** a coefficient-domain calibrated histogram. Each AC
  coefficient is predicted as the rounded mean of the same-frequency
  coefficients in its adjacent blocks (same component slot); the
  calibrated histogram is the histogram of those predictions, and
  the score is the total-variation distance between the observed
  and calibrated AC magnitude histograms, normalised by
  `tv_reference`. No IDCT, pixel reconstruction or recompression
  is performed.
- **Reliability gate:** calibration needs spatially correlated
  blocks in a 4:4:4 or grayscale layout. Subsampled layouts and
  uncorrelated blocks (adjacent-block agreement below
  `neighbor_agreement_min`) gate the score to 0 with the limitation
  recorded.
- **Score cap:** the score is hard-capped at `score_cap` (0.09),
  below the frozen DCT quarantine point (0.122108), so this
  unfrozen detector can never by itself cause withholding before
  a dedicated freeze calibrates points for it.
- **Applicability:** parsed JPEG with coefficient blocks; PNGs and
  failed parses get no finding.

## Comparison benchmarks (both detectors individually visible)

`benchmark_lsb_pairs` (`covertlens.lsb-pairs-benchmark`) and
`benchmark_dct_calibrated` (`covertlens.dct-calibrated-benchmark`)
score the +/-1 suite with both detectors on every row — each row
carries both scores, each detector gets its own stratified
bootstrap ROC-AUC (default 1000 replicates, seeded), and
per-band pair/calibrated ROC-AUC against all negatives is reported.
CLI: `python -m covertlens benchmark-matching`.

Measured on the shipped suites (1000 bootstrap replicates):

| Family | New detector ROC-AUC | PoV ROC-AUC | Beats PoV (point estimate) |
|---|---|---|---|
| `spatial_lsb` | 0.597 [0.429, 0.762] | 0.499 [0.380, 0.614] | yes |
| `jpeg_dct` | 0.833 [0.632, 1.000] | 0.715 [0.493, 0.917] | yes |

The spatial gain is modest and the bootstrap intervals overlap:
the claim is that the point estimate beats PoV on this +/-1 suite
(PoV is at chance, as its limitations predict), not that the gain
is statistically separated at this suite size. Per-band spatial
AUCs (low 0.62, medium 0.56, high 0.65 against all negatives) are
reported in the benchmark and are honestly weak-to-moderate; the
DCT suite covers only the low band because smooth covers offer
few \|AC\| ≥ 2 carriers.

## Frozen-benchmark pinning (no regression)

CL-61 changes nothing about the frozen evaluation:

- `frozen_benchmark._family_score` selects the finding whose
  detector name is the one the frozen points were calibrated for
  (`lsb-pov-chisquare`, `dct-coefficient-pov-chisquare`,
  `metadata-ancillary-entries`), so held-out recall/precision are
  computed from exactly the same scores as before CL-61.
- `calibration.calibrate_thresholds` likewise only consumes those
  named detectors; the CL-61 detectors never tune frozen points.
- In the integrated pipeline (`analyze_all_bytes`) both new
  findings are attached and individually visible. On the frozen
  suite's gradient-noise covers both new detectors are gated to 0
  (no adjacent-pair / neighbor-block correlation), so clean-run
  stability verdicts are unaffected. Both scores are also capped
  below their family's frozen quarantine point, so neither new
  detector can by itself withhold a delivery under the frozen
  ladder; the full frozen evaluation (held-out families,
  in-coverage clean stability, and the out-of-coverage smooth /
  blocks probes) was re-run after CL-61 and matches main.
- `pinning.default_detector_versions` now records all six
  detectors, so a pin built after CL-61 names the new versions and
  drift against pre-CL-61 pins is detectable.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| On +/-1 embedded fixtures, the new spatial detector's ROC-AUC beats PoV chi-square, with bootstrap intervals reported | `tests/test_stronger_detectors.py::test_spa_beats_pov_on_matching_fixtures_with_bootstrap` (`pairs_beats_pov`, both AUC blocks carry 200-replicate intervals in tests, 1000 via CLI), `benchmark-matching` CLI report |
| No regression on the existing frozen benchmark | `test_frozen_family_score_stays_pinned_to_pov` (frozen score equals the PoV finding by name), full `tests/test_frozen_benchmark.py` + `tests/test_calibration.py` suites green, frozen evaluation unchanged |
| RS/SPA second spatial detector alongside PoV; calibrated-histogram DCT detector; +/-1 fixtures showing the gain; both detectors individually visible | `lsb-sample-pairs` / `dct-calibrated-histogram` findings in `analyze_all_bytes` (`test_both_detectors_individually_visible_in_pipeline`), matching fixture builders with independent decode verification (`test_matching_fixtures_verify_and_differ_only_by_embedding`) |
