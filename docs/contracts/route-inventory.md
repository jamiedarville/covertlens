# Artifact route inventory (CL-7 · EV-01)

Every inventoried way an eval-generated PNG/JPEG can travel from a
producer to a recipient. The machine-readable registry is
`covertlens.routes.ROUTES`; this page is its human view. CL-12 builds the
single authoritative gate against this list, and CL-32 audits end-to-end
coverage against it — a route missing here is a coverage gap by
definition.

| ID | Kind | Route | Carries | Interception point |
|---|---|---|---|---|
| R-01 | `tool_output` | Tool returns image bytes / inline image | bytes | Artifact-store ingest on tool-output capture, before attachment to recipient context |
| R-02 | `tool_output` | Tool writes a file, returns path/URI | reference | Reference resolution at ingest; bytes become an immutable original before delivery |
| R-03 | `file_reference` | Agent message references an image by ID/path/URI | reference | Message dispatch; every reference resolved and gated before the recipient sees it |
| R-04 | `artifact_access` | Direct artifact-store fetch by ID/version | bytes | Store read path; no bytes before a permitting verdict for that exact version/hash |
| R-05 | `artifact_access` | Cached or signed link redemption | bytes | Link redemption, gated exactly like a direct fetch (CL-18) |
| R-06 | `artifact_access` | Preview / thumbnail / derivative | derivative | Derivatives derive only from a gated original; a withheld original yields none |
| R-07 | `artifact_access` | Recipient parser (vision) hand-off | bytes | Parser hand-off; withheld artifacts record parse `not_observed` |
| R-08 | `review_access` | Reviewer evidence access | bytes | Permission-checked, audited evidence reads only (CL-11/CL-33) |

## Rules

1. Both CL-7 kinds — `file_reference` and `tool_output` — are covered
   (R-01–R-03), plus the access paths recipients actually use (R-04–R-07).
2. Every route is gated before recipient access, or carries an explicit
   exception reason. Today the only exception is R-08: reviewer evidence
   access cannot deliver bytes to a run recipient, so the delivery gate
   does not apply; permission checks and audit do.
3. References are not a bypass: R-02/R-03 resolve to original bytes and
   are gated on the resolved version/hash, identically to byte routes.
4. Adding a route means adding a registry entry, an interception point,
   and a CL-32 audit row — in that order. An unregistered path that can
   move image bytes is a defect, not a feature.
