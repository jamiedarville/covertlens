# Vector sources with rendered-version verdict binding contract (CL-41)

Implements: CL-41 (GEO-04, C-10). Schema:
[schemas/vector-binding.schema.json](../../schemas/vector-binding.schema.json).

## Paths

- **Vector path:** the harness-side generator emits a
  `covertlens.vector-source` JSON object list with the rendered
  fixture. `parse_vector_source` reads object attributes directly
  (reading order via the CL-39 row grouping) into the same record
  shape the raster segmenter produces, so CL-40 tests consume both
  paths identically. Vector values are exact — no raster
  quantization noise.
- **Raster fallback:** CL-39 segmentation of the original raster
  bytes, with renderer-effect limitations recorded
  (`RASTER_LIMITATIONS`): pixel-quantized measurements, original
  bytes only, PNG-only.

## Binding and lineage

- The rendered raster is the delivered, scored artifact. Every
  combined report binds to it (`bound_content_hash`, plus
  `bound_rendered_version_id` when registered) — the vector source
  is evidence about that version, never a substitute (C-10/C-05).
- In the CL-8 store, the source is registered as a derivative
  record whose parent is the rendered version; the link record
  carries `relation: rendered_from_vector_source` and both
  content hashes, and store lineage traverses from the rendered
  version.
- Gate-level verdict binding activates when geometric thresholds
  are frozen (post CL-42 benchmark); until then the geometric
  finding is log-only triage evidence bound to the rendered hash.

## C-10 guard

A vector source that exists but was not intercepted/parsed can
never be cleared by a clean raster score:
`clearance: refused_unparsed_vector_source`, `cleared: false`.
An unparseable source refuses the same way. Clearance requires
both paths at `no_signal`.

## Verification

`python -m covertlens vector-demo`;
`tests/test_vector_source.py` asserts direct parsing, store
lineage, the binding hash, the C-10 refusal, and fallback
limitations.
