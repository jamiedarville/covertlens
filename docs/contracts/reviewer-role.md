# Reviewer role, dispositions and sealed exports (CL-59)

Traces REV-04, REV-06, OP-01. Blocked by CL-53.

## Demo roles

The web app has no authentication. A demo role toggle chooses
which CL-11 principal the API acts as, and is labelled
**demo role (not authentication)** in the API and on the page.

| Demo role | Actor | Runtime-policy role | Permissions |
|---|---|---|---|
| `viewer` | `demo-viewer` | `viewer` | none (deny-by-default) |
| `researcher` | `demo-researcher` | `researcher` | `original.read`, `trace.read`, `export.create`, `verdict.override` |
| `reviewer` | `demo-reviewer` | `reviewer` | `candidate.decode.read`, `original.read`, `trace.read` |

The role travels in the `X-Demo-Role` header (default `viewer`;
unknown roles are rejected with 400) and is scoped to one
run-as-dataset, so permission on one run says nothing about
another.

The header is honoured only when `COVERTLENS_DEMO_ROLES=on`
(CL-78). The Docker image and `docker-compose.yml` turn it on
because they are the demo; anywhere else it defaults to off, the
header is ignored, and every request is a `viewer`.
`GET /api/review/roles` reports the setting as `enabled`, and the
role picker on the Live Gate, Trace and Reviewer pages shows a
warning when it is off. Real roles replace this in CL-67.

### Permission checks outside the review workspace (CL-78)

| Endpoint | Needs | Denied |
|---|---|---|
| `GET /api/gate/deliveries/{id}/reviewer-image` | `original.read` | 403; gate records `reviewer_denied` with the actor |
| `POST /api/gate/deliveries/{id}/verdict` | `verdict.override` | 403 (`needs: verdict.override`) |
| `GET /api/review/audit` | `trace.read` | 403 (`needs: trace.read`) |
| `GET /api/trace/runs/{run_id}` | `trace.read` | 403 (`needs: trace.read`) |

So a verdict needs `researcher`; reviewer image, audit and trace
accept `researcher` or `reviewer`; `viewer` gets none of them. `covertlens.review.demo_principal` is the mapping;
`viewer` was added to `config/runtime-policy.json` with an empty
allow list, leaving the deny-by-default policy and the
scorer-only `payload.read` rule unchanged.

## Review workspace

`covertlens.review.ReviewWorkspace` wraps the CL-11
`EvidenceGateway` and its hash-chained `AuditLog` over the
persistent gate store. Audit entries, candidate decodes and
dispositions persist to `review.sqlite3` next to the gate state,
so a restart keeps the run reviewable and the chain verifiable.
Reports are rebuilt on demand from the gate trace plus fresh
deterministic analysis of the stored bytes, with stored
dispositions applied through `report.apply_review`.

Candidate decode text lives only in the gateway's reviewer
evidence path. The workspace records it there
(`record_candidate_decode`, R-08) and returns only its decode ID;
queue and detail responses carry `has_candidate_decode` and the
ID, never the text. The audit records the code and text length,
never the text (CL-46).

## Reviewer API (`app/main.py`)

| Endpoint | Behaviour |
|---|---|
| `GET /api/review/roles` | Demo roles, actor IDs, permissions, header name. |
| `GET /api/review/runs/{run_id}/queue` | All deliveries plus the `quarantined` (withheld) subset, each with disposition and candidate availability. No decoded text. |
| `GET /api/review/deliveries/{id}` | Delivery, findings, geometric report with `candidate_decode` and any decoded-message slot stripped (as in the analyze worker, CL-48). |
| `GET /api/review/deliveries/{id}/candidate-decode` | Reviewer-only candidate text via `EvidenceGateway.read_candidate_decode`. Researcher/viewer → 403, audited as a denied `candidate_decode.read`. Unknown decode → 404. |
| `GET /api/review/deliveries/{id}/original` | Original bytes via the gateway (`original.read`): researcher/reviewer served, viewer → 403 (audited). |
| `POST /api/review/deliveries/{id}/disposition` | One of the five CL-25 dispositions. Researcher/reviewer only (viewer → 403, audited); `demonstrated_transfer` requires `demonstrated_basis` (400 without it); unknown disposition → 400. |
| `GET /api/review/runs/{run_id}/export` | Sealed review package download (`create_review_export`, attachment). Researcher only — reviewer/viewer → 403, audited. |
| `GET /api/review/audit?run_id=` | Live audit payload: entries for the run, denied count, head hash, and `chain_valid` from `AuditLog.verify_chain()`. Needs `trace.read` (CL-78). |
| `GET /review` | SPA shell for the Reviewer page. |

## Reviewer page (`/review`)

Pick a demo role and a Live Gate run; load its quarantined
originals; open one to see the original (when the role may read
it), its findings and geometric classification; read the
candidate decode as the reviewer (other roles see the denial);
record a disposition; download the sealed package as the
researcher; and watch the audit panel verify the chain live,
denied attempts included.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| Researcher-role candidate-decode request denied and in the audit chain | `tests/test_review.py::test_researcher_decode_denied_and_audited` (403 for researcher and viewer, denied `candidate_decode.read` entries for `demo-researcher`/`demo-viewer`, text absent from audit and all non-decode responses) |
| After a full demo session the audit chain verifies | `test_full_demo_session_export_and_audit`, `test_workspace_state_survives_reopen_with_chain_intact`, `test_review_state_survives_api_restart` (`chain_valid` true after queue → denied decode → reviewer decode → disposition → export, and after restart) |
| Downloaded package passes `validate_review_package` | `test_full_demo_session_export_and_audit` (researcher download validates, disposition reflected, tampering rejected; reviewer export 403) |
