# Bounded parsing and analysis result schema (CL-13 · DET-01/DET-02)

Original PNG/JPEG bytes are parsed natively by `covertlens.parsing`
under versioned worker limits. No resize, recompression or preview
substitution ever happens before analysis: every result carries
`transform_applied: false` and the `content_hash` of the exact bytes
consumed, so hash drift is detectable. Machine contract:
[analysis-result.schema.json](../../schemas/analysis-result.schema.json).

## One explicit result for every input

`analyze_bytes(data, limits=...)` never raises for malformed image
input. Every call returns one `AnalysisResult` with a stable status:

| Status | Meaning |
|---|---|
| `parsed` | Original bytes parsed in the native domain within limits |
| `corrupt` | Recognised format with broken structure (CRC, truncation, bad markers) |
| `unsupported_format` | Not PNG or JPEG bytes (eval scope) |
| `unsupported_encoding` | Valid format outside the declared parser subset |
| `oversized` | A size, dimension, pixel or decompressed bound was exceeded |
| `timeout` | The runtime deadline was exceeded |

Failures carry `errors`, partial `coverage` where meaningful and
`limitations`; they never carry `findings`. A parse failure is an
infrastructure outcome, never a clean verdict or a collusion finding
(C-02, manifest error behaviour).

`analyze_version(store, version_id, actor_id=...)` reads the original
through the CL-8 store's hash-checked, audited `get_original`
(`purpose: "analysis"`), so analysis always binds to one exact stored
version. Tampered backing bytes raise `HashMismatchError` instead of
being analysed.

## Declared parser subset

Anything outside this subset returns `unsupported_encoding` with the
limitation recorded rather than a guessed parse:

- **PNG:** 8-bit, non-interlaced, colour types 0/2/3/4/6. All five row
  filters are unfiltered in place. Coverage reports `rows_parsed` and
  `pixels_parsed`; `pixels` holds the unfiltered sample bytes.
- **JPEG (parser 1.1.0, CL-57):** 8-bit baseline sequential DCT (SOF0),
  grayscale or 3 components with 4:4:4, 4:2:2 or 4:2:0 sampling.
  Each scan component selects its own DC/AC Huffman tables. SOF/SOS/DHT
  lengths, component IDs, table availability and entropy categories are
  validated before indexing. Entropy data is decoded in the quantized coefficient
  domain (no IDCT, no pixel reconstruction). Coverage reports
  `blocks_parsed` and `coefficients_parsed`; `coefficients` holds the
  64-coefficient blocks in raster MCU order. Restart intervals are
  outside the subset.

## Worker limits (DET-02)

`ParserLimits` is versioned (`1.0.0`). Defaults: 10 MiB input,
20 MP, 8192x8192 dimensions, 128 MiB decompressed data, 2 s runtime
deadline. Input size is checked before parsing; dimensions and pixel
counts are checked from headers before decompression or entropy
decoding; decompressed output is capped while inflating; the deadline
is checked before heavy phases and periodically during row/MCU loops.
`max_runtime_s: 0` means already timed out, which tests use for a
deterministic `timeout` result.

## Channel findings (DET-02)

`Finding` is the versioned record detectors populate: `family`
(`spatial_lsb`, `jpeg_dct`, `metadata`), detector `name`/`version`,
`score` in [0, 1], detector `coverage`, `evidence` and `limitations`.
CL-13 emits no findings itself; CL-14 (LSB), CL-15 (DCT) and CL-23
(metadata) fill them in. `validate_result` / `validate_finding`
enforce the contract, including that failed parses carry no findings.
Thresholds stay unfrozen until CL-27.

## Out of scope here

Detector scoring (CL-14/CL-15/CL-23), trace joining (CL-16) and run
failure handling (CL-19) consume these results but are separate tasks.

## Optional acceleration and measured limit (CL-57)

Install `.[fast]` and set `COVERTLENS_FAST_PATH=numpy` to enable exact NumPy
None/Sub/Up PNG unfiltering and sample histograms. Average/Paeth filters use
the reference loops. Missing NumPy falls back to the standard-library path.
The default remains the pure-Python implementation. Tests compare reconstructed
pixels and findings exactly across paths. JPEG entropy decoding uses a byte
reader and nine-bit Huffman lookup without materializing individual bits.

A seeded 2,000-case CI fuzz campaign truncates/flips bytes across procedural,
geometric and committed real/codec fixtures. Every result must validate against
the result schema. Independent libjpeg-turbo 4:2:0 and optimized-Huffman files
must produce DCT coefficients. Progressive JPEG and restart intervals remain
outside the integrated coefficient parser subset.

The CL-29 **end-to-end** large-JPEG deadline is not met: five accelerated
1024×768 samples parsed, but P95 was 10.3298 s. The 2 s parser deadline does
not bound subsequent geometry reconstruction/segmentation. This remains an
open CL-57 acceptance gap; see the validation record in
[docs/reviews/cl-55-57-validation.json](../reviews/cl-55-57-validation.json).
