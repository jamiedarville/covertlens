# Harness events and stable IDs (CL-7 · EV-01)

Every inter-agent image in the Meta AI internal eval harness produces an
ordered, single-run event trail. This contract defines the event families,
their stable IDs, and the invariants downstream tasks rely on. Machine
contracts: [harness-events.schema.json](../../schemas/harness-events.schema.json)
and `covertlens.events`.

## Event families

| Family (CL-7) | `event_type` | Meaning | Key required fields |
|---|---|---|---|
| creation | `artifact.created` | Exact original bytes enter the artifact store | `artifact_id`, `artifact_version_id`, `content_hash` |
| attempted delivery | `delivery.attempted` | A sender tries to deliver one artifact version to one recipient | `delivery_id`, `content_hash`, `sender_id`, `recipient_id` |
| gate linkage | `gate.verdict` | The gate records its verdict for a delivery | `delivery_id`, `verdict_id`, `verdict` |
| access | `artifact.accessed` | Bytes for a version are served on a gated route | `delivery_id` |
| access/parse | `artifact.parsed` | The recipient parser consumed (or did not consume) the bytes | `parse_status` |
| action | `recipient.action` | The recipient's next action after a delivery | `delivery_id` (when caused by one delivery) |
| run finalization | `run.finalized` | The run ends with an explicit outcome | `payload.outcome` |

`payload.outcome` is one of `completed`, `failed_detection`,
`failed_infrastructure`, `aborted`. Detection failure and infrastructure
failure are never merged (C-02).

## Stable IDs

| ID | Shape | Rule |
|---|---|---|
| `run_id` | `run_<uuid>` | Assigned at run start; events never join across runs (REV-02) |
| `episode_id` | `ep_<uuid>` | Persists across episodes inside one run only |
| `artifact_id` | `art_<uuid>` | One logical image; survives re-delivery |
| `artifact_version_id` | `<artifact_id>.v-<hash16>` | Binds the artifact to one exact byte sequence; changed bytes mean a new version and invalid prior verdicts (C-05, EV-04) |
| `content_hash` | `sha256:<hex>` | SHA-256 over the exact original bytes, before any preview or analysis transform (EV-03) |
| `delivery_id` | `dlv_<hash32>` | Deterministic over run, version, recipient and attempt; a retry of the same attempt reuses it (EV-07) |
| `verdict_id` | `vrd_<uuid>` | One gate decision; referenced by trace joins (REV-01) |
| `event_id` | `evt_<hash32>` | Deterministic over run, `seq`, type and idempotency key; identical logical events deduplicate |

## Ordering and invariants

1. `seq` is a per-run integer starting at 0 and increasing by exactly 1.
   Wall-clock `occurred_at` is recorded but never used for ordering.
2. `run.finalized` is always the last event of its run.
3. **No lookahead (C-03):** a `gate.verdict` may only reference a
   `delivery.attempted` that already appears earlier in the same run.
   Future recipient actions are never inputs to a pre-delivery decision.
4. **Withheld means not observed (C-04):** after a `quarantine` or
   `fail_run` verdict, the only valid parse status for that delivery is
   `not_observed`. Withheld artifacts never count as successful transfer.
5. **Idempotency (EV-07):** re-emitting the same logical event (same
   `event_id`) is a duplicate, not a second fact. Consumers deduplicate
   on `event_id`; producers reuse `delivery_id` across retries.
6. Every `delivery.attempted` carries the original `content_hash` and,
   once decided, a `verdict_id`, so findings join the ordered trace
   (REV-01, CL-16).

`covertlens.events.TraceLog` enforces invariants 1–5 for one run.
`covertlens.events.validate_event` checks a single event against the
field rules above.
