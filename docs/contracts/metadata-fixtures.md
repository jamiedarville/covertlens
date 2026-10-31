# Metadata fixtures and benign channel controls (CL-22 · DT-06)

`covertlens.metadata_fixtures` extends the ground-truth corpus to
the metadata family, following the CL-9 conventions (paired clean /
encoded fixtures, declared payload units, recorded generator and
encoder provenance, benign negatives).

## Encoding rule (declared, verified)

An encoded fixture carries its payload in exactly one ancillary
metadata entry under the keyword `CovertLensPayload`:

- **PNG:** a `tEXt` chunk inserted before the first `IDAT`;
- **JPEG:** an `APP1` segment inserted immediately after SOI.

Everything else is bit-identical to the matched clean control — PNG
pixels and JPEG coefficients provably unchanged (the tests compare
CL-13 parse outputs between pair members). Extraction is independent
of the encoder: `extract_metadata_payload` re-reads the ancillary
entries from the saved bytes, and every fixture in the dataset is
verified against its recorded payload (`verify_metadata_fixture`)
before the suite is returned. Payload units match CL-9: bits =
bytes x 8, bands by bits-per-pixel.

## Benign controls (allowed exceptions)

The manifest declares allowed task metadata, so controls carry it:
`allowed_metadata_control` adds `Title`, `Description` and
`TaskReference` entries (and nothing else) and is labelled
`negative` / `allowed_task_metadata` with an empty payload. A
detector that fires on the mere presence of metadata will fail on
these controls by design — only the declared payload keyword is
ground-truth encoding.

## Lineage and splits

Fixtures reuse the CL-9 `Fixture` record: `pair_id` matches pair
members, generator provenance records cover seed/pattern/size,
encoder provenance records `metadata-text-payload` version and the
insertion rule, and `content_hash` pins exact bytes. CL-10 split
assignment therefore groups a metadata original with all its
derivatives exactly as for LSB/DCT fixtures, and scorer ground truth
stays in the fixture record, out of detector inputs (DT-03/C-07).

## Out of scope here

Metadata *scoring* and three-family integration are CL-23; these
fixtures are ground truth only and ship no detector.
