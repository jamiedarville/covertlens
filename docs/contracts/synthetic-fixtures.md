# Synthetic paired fixtures (CL-9 · DT-01/DT-02)

Reproducible eval-generated PNG/JPEG benchmark pairs for authorized
testing, built by the deterministic, dependency-free factory in
`covertlens.fixtures`. Machine contract:
[fixture-manifest.schema.json](../../schemas/fixture-manifest.schema.json).
No generative image model is involved: covers are seeded procedural
images and payloads are embedded by exact encoder code, so the only
intended difference inside a pair is the payload itself.

## How a pair is made

1. **Cover.** `generate_cover(width, height, pattern, seed)` produces a
   deterministic RGB cover (LCG-seeded; identical on every Python
   version). Patterns: `gradient_noise`, `blocks`, `smooth`, with
   per-channel noise so chroma stays textured.
2. **Payload.** `make_payload(seed, n_bytes)` produces the synthetic
   payload. Declared units on every fixture: `payload_bits`,
   `payload_bytes`, `bits_per_pixel` (= payload bits / cover pixels),
   and a payload band (`low` ≤ 0.05, `medium` ≤ 0.25, `high` above;
   `none` for zero-payload fixtures).
3. **Embed.**
   - `spatial_lsb`: payload bits (MSB-first) replace the LSB of RGB
     channel bytes in raster order; the result is saved once as a PNG.
   - `jpeg_dct`: the cover is JPEG-encoded by the factory's minimal
     baseline codec (4:4:4, standard quantization scaled by `quality`,
     custom Huffman tables carried in the file); payload bits replace
     the LSB of quantized AC coefficients with magnitude ≥ 2 — a
     carrier set that embedding cannot shrink — across Y, Cb and Cr.
4. **Freeze.** The saved bytes are the fixture. No resize or
   recompression happens afterwards (CL-13 analyses exactly these
   bytes), and ingest into the CL-8 store preserves their hashes.

## Verification (independent of the encoder)

`Fixture.verify_payload()` decodes the saved bytes through a separate
read path (PNG chunk parser; JPEG marker/Huffman coefficient parser)
and requires bit-exact payload recovery. Clean controls must not
recover the pair's payload. The default suite fails to build if any
encoded fixture does not verify.

## Provenance and label separation

Every fixture records generator `name`/`version`/`seed`/`pattern` and
encoder `name`/`version`/`seed` plus its full configuration (LSB depth
and order; JPEG quality, quantization rule and coefficient-selection
rule). The detector-facing `manifest.json` carries only
`payload_sha256`, never raw payload bytes; scorer-side payloads live
in a separate `ground-truth.json` (`covertlens.fixtures.ground_truth`).
CL-10 builds leakage-safe splits on these records.

## Negatives

The default dataset (`build_dataset()`) ships, per family, three
encoded pairs (low/medium/high bands) plus negatives with zero payload
bits: benign edits (`brightness`, `flip_horizontal`) and generator
variations (different patterns/seeds). Negatives follow the same
lineage, hash and unit rules as pairs.

## Out of scope here

Leakage-safe split assignment and held-out label protection (CL-10),
detector scoring of these fixtures (CL-14/CL-15) and metadata-channel
fixtures (CL-22) consume this factory but are separate tasks.
