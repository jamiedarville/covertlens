# LSB spatial detector and benchmark (CL-14 · DET-03)

PNG sample LSBs are scored on the exact original bytes parsed by
CL-13, in `covertlens.lsb`. No resize, recompression or derivative
is involved: the detector consumes the `pixels` of a parsed PNG
`AnalysisResult` and emits one versioned `spatial_lsb` `Finding`
(DET-02 schema). Machine contract for the benchmark report:
[lsb-benchmark.schema.json](../../schemas/lsb-benchmark.schema.json).

## Detector (versioned scores and coverage)

- **Implementation:** `lsb-pov-chisquare` v`1.0.0`, configuration
  `LsbConfig` v`1.0.0` (currently only `pair_min_count`, the minimum
  pair total for a pairs-of-values cell to enter the statistic).
- **Statistic:** the classic pairs-of-values (PoV) chi-square for LSB
  replacement. Payload bits written into sample LSBs drive each value
  pair `(2k, 2k + 1)` toward equal counts; untouched covers retain the
  pair imbalance of the cover itself. The score is
  `degrees_of_freedom / chi_square` clipped to [0, 1] — near 1 when
  pairs look as equal as random LSBs predict, lower when natural
  imbalance survives. It never decodes a payload.
- **Coverage (applicable coverage):** every finding records
  `samples_examined`, `pixels_examined`, `channels`, `pairs_total`
  (128), `pairs_used` (after `pair_min_count`), `rows_parsed` and the
  `config_version` — a small or sparse image is visible as low
  coverage rather than masquerading as a confident score. Evidence
  carries the raw `chi_square`, degrees of freedom,
  `chi_square_per_df`, `lsb_one_fraction` and `pov_imbalance`.
- **Applicability:** only a parsed PNG with sample bytes gets a
  finding. JPEGs belong to the DCT family (CL-15); a failed parse
  keeps CL-13's explicit failure status and carries no finding, so a
  missing LSB score is never a clean verdict (C-02 fail-closed,
  manifest error behaviour). Entry points: `detect_lsb(result)`,
  `analyze_lsb_bytes(data)`, `analyze_lsb_version(store, ...)` — the
  last binds to one exact stored version through the CL-8 audited,
  hash-checked read.

## Benchmark (payload bands, threshold-free, uncertainty)

`benchmark_lsb(fixtures)` scores labelled CL-9 fixtures (positive:
`encoded`; negative: `clean` + `negative`; non-LSB families are
counted as `skipped_non_lsb`, never scored as negatives) and returns a
versioned `covertlens.lsb-benchmark` report (`validate_benchmark`
checks it):

- **By payload band:** rows keep the CL-9 `payload_band`
  (`none`/`low`/`medium`/`high`) and `bits_per_pixel`.
  `by_payload_band` reports per-band counts, score min/max/mean, and
  each encoded band's ROC-AUC ranked against *all* negatives, so the
  (harder) low band is never averaged away by the high band.
- **Threshold-free:** a sweep over every distinct score (plus 0 and 1)
  reports, at each candidate threshold, the confusion counts with
  precision, recall and false-positive-rate. The sweep is an
  evaluation curve, not a frozen operating point: thresholds stay
  `unfrozen_placeholder` until CL-27 (C-06 keeps triage and
  enforcement points separate). Overall summaries are ROC-AUC
  (Mann-Whitney) and average precision (the PR-curve summary).
- **Uncertainty:** every sweep proportion is a Wilson score interval
  (95%), and both AUC summaries carry stratified bootstrap percentile
  intervals (default 1000 replicates, seeded, reproducible). On the
  small CL-9 suite the Wilson intervals are honestly wide and the
  bootstrap intervals are conditional on the observed sample (they
  can be degenerate under perfect separation); a point estimate
  must never be quoted without them.

On the current procedural suite the detector separates medium/high
bands well and the low band only weakly (few payload bits spread over
the whole frame) — that gap is reported per band, not hidden in an
overall number, and is a limitation to carry into CL-27 calibration.

## Limitations

- Global PoV chi-square only: LSB-matching (+/-1) and
  content-adaptive embedding, which preserve pair counts by design,
  may evade it; sequential-scan length estimation is future work.
- Covers here are procedural synthetics, not natural images; do not
  extrapolate scores to photo-like covers without new calibration.
- A score is evidence for triage, never demonstrated collusion
  (C-02), and this module freezes no verdict threshold.

## Out of scope here

DCT scoring (CL-15), metadata scoring (CL-23), verdict mapping
(CL-17) and threshold freezing (CL-27) consume these findings but
are separate tasks.
