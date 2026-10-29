# Runtime, evidence permissions and audit logging (CL-11 · OP-01)

Internal execution with classification-aware evidence access, enforced
by `covertlens.runtime` over the CL-8 store. Machine contracts:
[config/runtime-policy.json](../../config/runtime-policy.json) and
[runtime-policy.schema.json](../../schemas/runtime-policy.schema.json).

## Permission model

Deny-by-default and dataset-scoped: a grant helps only inside the
datasets listed on the principal. The shipped policy matrix:

| Role | Permissions |
|---|---|
| `agent` (run participant) | none — never touches evidence |
| `detector_worker` | `original.read` |
| `researcher` | `original.read`, `trace.read`, `export.create`, `verdict.override` |
| `scorer` | `payload.read`, `trace.read` (payloads are scorer-only, DT-04) |
| `operator` | `config.change`, `retirement.request` |
| `approver` | `retirement.approve` |

`validate_runtime_policy` fails closed on drift: it rejects a
non-internal policy, any grant to the `agent` role, `payload.read`
held by anyone but `scorer`, a non-chained audit log, or weakened
retirement rules.

## Evidence gateway

`EvidenceGateway` is the only read path in this layer. Allowed reads
are served from the immutable store and audited; denied reads raise
`PermissionError`, serve nothing, and are still audited. Held-out
payload export additionally requires `payload.read`, so the CL-10
scorer-role boundary holds through the gateway as well.

## Audit log

`AuditLog` is append-only and hash-chained (`prev_hash` → `entry_hash`
over the canonical entry body), retained for the dataset lifetime.
It records evidence reads (allowed and denied), configuration changes
(`RuntimeConfig.apply_change`, with old/new values and the bumped
config version), verdict overrides (mandatory reason; the original
verdict is never rewritten) and retirement lifecycle events.
`verify_chain()` re-computes every link, so silent edits to history
are detectable.

## Dataset retirement

`DatasetRetirement` governs the only deletion path — the CL-8 store
itself has no delete API:

1. `request` (operator) records reason and requester.
2. `approve` (approver) must come from a different actor than the
   requester; self-approval is refused and audited.
3. `execute` refuses to run before approval, first captures a
   reproducibility bundle (artifact version IDs, sorted content
   hashes, config version, policy version, audit head), then deletes
   the dataset bytes. The bundle and the audit chain survive deletion,
   preserving reproducibility until approved deletion — and the record
   of it afterwards.

## Out of scope here

Permission enforcement on researcher review exports (CL-33), gate
interception wiring (CL-12) and runbook/retention operations (CL-36)
consume this layer but are separate tasks.
