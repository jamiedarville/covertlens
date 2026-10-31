# JPEG DCT detector and benchmark (CL-15 · DET-04)

Quantized DCT coefficients from the exact original JPEG bytes parsed
by CL-13 are scored in `covertlens.dct`. No IDCT, pixel
reconstruction, resize or recompression is involved: the detector
consumes the `coefficients` of a parsed JPEG `AnalysisResult` and
emits one versioned `jpeg_dct` `Finding` (DET-02 schema). Machine
contract for the benchmark report:
[dct-benchmark.schema.json](../../schemas/dct-benchmark.schema.json).

## Detector (scores, configuration, limitations recorded)

- **Implementation:** `dct-coefficient-pov-chisquare` v`1.0.0`,
  configuration `DctConfig` v`1.0.0` (`carrier_min_magnitude`,
  `pair_min_count`). Every finding records the detector and config
  versions in its evidence, so a score is always reproducible from a
  named configuration.
- **Statistic:** magnitude pairs-of-values chi-square (the JSteg
  family) over AC coefficients. The CL-9 embedder writes payload bits
  into the LSB of magnitudes >= 2, a carrier set embedding cannot
  shrink; encoded images therefore drive each magnitude pair
  `(2k, 2k+1)` toward equal counts, while clean JPEGs keep the
  decaying pair imbalance of natural quantized spectra. Score is
  `degrees_of_freedom / chi_square` clipped to [0, 1]. No payload is
  decoded.
- **Coverage:** `blocks_examined`, `coefficients_examined`,
  `ac_coefficients_examined`, `carriers_examined` (|AC| >= 2),
  `pairs_used`, image dimensions/components and `config_version`.
  Evidence carries the raw chi-square, degrees of freedom,
  carrier LSB-one fraction and magnitude imbalance.
- **Applicability:** only a parsed JPEG with coefficient blocks gets
  a finding. PNGs belong to the LSB family (CL-14); a failed parse
  keeps CL-13's explicit failure status and carries no finding, so a
  missing DCT score is never a clean verdict (C-02).
  Entry points: `detect_dct(result)`, `analyze_dct_bytes(data)`,
  `analyze_dct_version(store, ...)` — the last binds to one exact
  stored version through the CL-8 audited, hash-checked read.

## Benchmark (false positives and recall by payload band)

`benchmark_dct(fixtures)` scores labelled CL-9 DCT fixtures
(positive: `encoded`; negative: `clean` + `negative`; non-DCT
families are counted as `skipped_non_dct`, never as negatives) and
returns a versioned `covertlens.dct-benchmark` report
(`validate_dct_benchmark` checks it):

- The overall sweep reports confusion counts at every candidate
  threshold, so **false positives** (negatives at/above threshold)
  and false-positive rate with Wilson intervals are visible
  threshold by threshold.
- `by_payload_band` (`none`/`low`/`medium`/`high`) reports per-band
  counts, score min/max/mean, ROC-AUC against all negatives, and a
  per-band sweep: **recall** (with Wilson intervals) for each encoded
  band, and the false-positive sweep for the `none` band.
- Overall threshold-free summaries (ROC-AUC, average precision)
  carry seeded bootstrap intervals. Thresholds stay
  `unfrozen_placeholder` until CL-27.

On the current procedural suite, medium/high bands separate well
(high near-saturates the carrier set) and the low band is weak;
that ordering is reported per band, not averaged away.

## Limitations

Recorded verbatim on every finding: coefficient-domain only within
the CL-13 parser subset (8-bit baseline 4:4:4); histogram-preserving
embedding (e.g. +/-1 matching, adaptive selection) may evade the
global statistic; calibration covers only procedural synthetic
covers at the recorded encoder configuration (other JPEG quality
factors untested); a score is evidence, not demonstrated collusion
(C-02), and no verdict threshold is frozen here.

## Out of scope here

LSB scoring (CL-14, done), metadata scoring (CL-23), verdict mapping
(CL-17) and threshold freezing (CL-27) are separate tasks.
