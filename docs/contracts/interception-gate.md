# Artifact-store interception and pending delivery (CL-12 · EV-06/EV-07)

The single authoritative hook for inter-agent image transfers, in
`covertlens.gate.InterceptionGate` over the CL-8 store. Machine
contract: [delivery-record.schema.json](../../schemas/delivery-record.schema.json);
events follow [harness-events.md](harness-events.md); routes follow
[route-inventory.md](route-inventory.md).

## Flow

1. **Intercept.** `intercept_bytes` (tool-output bytes) or
   `intercept_reference` (file/tool-output references, resolved once)
   ingests exact original bytes into the immutable store and emits
   `artifact.created`. Every gated route R-01…R-07 uses this path;
   R-08 reviewer evidence access is rejected as a delivery route (it
   belongs to the CL-11 evidence gateway). `coverage_report()` lists
   gated routes not yet exercised, for the CL-32 coverage audit.
2. **Attempt.** `attempt_delivery` creates a **pending** delivery and
   emits `delivery.attempted` with run, episode, sender, recipient,
   artifact version and original content hash. No bytes move.
3. **Verdict.** `record_verdict` binds a CL-7 ladder verdict to the
   delivery's exact artifact version in the store: `log`/`flag`
   permit, `quarantine`/`fail_run` withhold. Changed bytes create a
   new version whose deliveries start pending again — the old verdict
   reports `invalidated` in the store.
4. **Access.** `recipient_access` serves the exact original bytes
   only from the permitted state (emitting `artifact.accessed`);
   pending raises `PendingDeliveryError`, withheld raises
   `WithheldError`. `record_parse` emits `artifact.parsed`; for
   withheld deliveries the trace enforces `not_observed` (C-04).

## Idempotency

Repeated references resolve once and return the same immutable
version with a single `artifact.created` event. Delivery retries with
the same attempt number reuse the deterministic `delivery_id`
(run, version, recipient, attempt) with a single
`delivery.attempted` event; a new attempt number is a new delivery.

## Out of scope here

Detector scoring that produces verdicts (CL-14/CL-15/CL-23), verdict
ladder configuration (CL-17), total-quarantine race enforcement
(CL-18/CL-20) and trace joining (CL-16) consume this gate but are
separate tasks. A gate verdict is an enforcement outcome, never proof
of collusion (C-02).
