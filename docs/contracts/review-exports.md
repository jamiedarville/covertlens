# Review exports and evidence access verification contract (CL-33)

Implements: CL-33. Schema:
[schemas/review-export.schema.json](../../schemas/review-export.schema.json).
Builds on the CL-25 run report, the CL-26 hash-sealed export and
the CL-11 permissioned runtime.

## The package

A review export is a sealed, byte-free evidence package:

- **Per original:** artifact id, version id, content hash, detector
  findings and labelled evidence aids.
- **Per delivery:** verdict, delivered/parse state, trace
  references and the researcher's disposition (`unresolved` is
  explicit, never blank).
- **Policy block:** runtime policy id/version, threshold config
  version and per-family status, detector versions, seeds, dataset
  hash and pin hash — everything needed to interpret and reproduce
  the decisions.
- **Seal:** `package_hash` over the whole package; changing any
  disposition or hash after export fails validation. Raw bytes and
  payloads are never in the package (byte access stays on the
  audited R-08/gateway path; ground truth stays scorer-only, C-07).

## Access verification (all exercised)

- Export creation requires `export.create` on the dataset;
  original reads require `original.read` (CL-11 gateway).
- Allowed **and denied** reads/exports land in the hash-chained
  audit log; original reads also land in the store access history.
  `verify_evidence_access` cross-checks chain, both logs, and the
  stored hash.
- Denied: a run agent (no evidence permissions) reading or
  exporting; a researcher scoped to a *different* dataset reading
  or exporting here. Grants never leak across datasets.
- Tampering: a flipped disposition breaks the package seal; a
  rewritten audit entry breaks `verify_chain`.

## Verification

`python -m covertlens export-demo` prints the verification summary;
`tests/test_review_export.py` asserts package contents, audit
logging, the four denials, and both tamper checks.
