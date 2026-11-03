# AI second opinion (CL-74, CL-75, CL-76, CL-77; epic CL-73)

Traces OP-01, OP-02, C-01, C-02, C-09, REV-04, REV-06. Schema:
[schemas/second-opinion.schema.json](../../schemas/second-opinion.schema.json).

A second AI model reviews the sealed, picture-free review package
(`build_review_package`) and returns a written opinion. The opinion
is an advisory evidence aid, recorded separately. It can never
change a verdict, unfreeze a limit, or mark anything as a
confirmed hidden message.

## Provider interface and key handling (CL-74)

`covertlens.second_opinion.SecondOpinionProvider` has one method:
`complete(prompt, images=None)` returning text plus model,
request ID and token counts. `HttpProvider` speaks the
OpenAI-compatible chat-completions shape (hosted Llama endpoints
included) and, for `provider=anthropic`, the Messages shape, using
only `urllib`. Configuration is environment-only:

| Variable | Meaning |
|---|---|
| `COVERTLENS_SECOND_OPINION_PROVIDER` | e.g. `openai`, `anthropic`, `fake` (tests) |
| `COVERTLENS_SECOND_OPINION_MODEL` | model name |
| `COVERTLENS_SECOND_OPINION_ENDPOINT` | base URL (provider default if empty) |
| `COVERTLENS_SECOND_OPINION_API_KEY` | key; server-side only |
| `COVERTLENS_SECOND_OPINION_TEMPERATURE` / `_MAX_TOKENS` / `_TIMEOUT_S` | sampling and deadline |
| `COVERTLENS_SECOND_OPINION_PER_RUN_CAP` / `_PER_DAY_CAP` / `_RATE_LIMIT_PER_MIN` | spending caps |

With no key the feature reports itself disabled and every other
part of CovertLens behaves exactly as before. The key never
appears in logs, exceptions, reports, exports, API responses or
browser storage (a sentinel-key test asserts this). Missing key,
timeout, refusal, or a cap/rate limit yields an explicit
`second_opinion_unavailable` record — never an empty "all clear".
`FakeProvider` exercises the interface offline.

## Prompts and injection defence (CL-75)

`build_second_opinion_prompt` builds the prompt from the sealed
package and the run report: findings, scores, decisions,
limitations, versions and the package hash. The instruction part
is fixed library text. Every agent-controlled string (candidate
decodings from the reviewer path, metadata keywords) is sanitized
(control characters stripped, length-limited, forged fence
markers neutralized) and placed inside
`<<<UNTRUSTED_DATA label="...">>>` … `<<<END_UNTRUSTED_DATA>>>`,
with an instruction that the block is data, never instructions.

The model must answer with one JSON object: an `assessment` from
`no_concern | uncertain | suspicious | strong_concern`,
`per_finding` comments, and a `confidence_note`.
`parse_second_opinion_response` validates that shape; anything
else is recorded as `unparseable`, never as agreement.
`build_injection_fixtures` plants the classic injection line in
both a candidate decoding and a metadata keyword; tests assert
the line never reaches the instruction part, and the gate verdict
is unchanged in every case. Against a real model, planted cases
should be run and any assessment shift toward the injected
wording reported, not hidden.

## Advisory record and picture policy (CL-76)

Each result is a `covertlens.second-opinion` record: run and
delivery references, review-package hash, provider and model,
settings (no key), prompt fingerprint
(`canonical_hash` of the full prompt), full response, parsed
assessment or `unparseable`, timestamps, and
`advisory_only: true`, `equated_with_collusion: false`.
`validate_second_opinion` rejects any record missing
`advisory_only: true`. Records are stored alongside the run
report (`report.second_opinions`, via `attach_second_opinion`)
and in the CL-33 export as their own sealed section. The verdict
ladder, freezes, pins and dispositions never read them; a test
proves a hostile "confirmed hidden message" opinion leaves the
disposition and verdict untouched.

Pictures stay internal by default (C-01). Sending original image
bytes requires all three of: the caller asked, the manifest's
per-run opt-in (`second_opinion.allow_images: true`, recorded
before the run; see `second_opinion_allows_images`), and the
gateway's `second_opinion.send_image` permission
(`EvidenceGateway.authorize_second_opinion_image`, researcher
only). Every allowed send is written to the audit chain. With
the opt-in off, no picture bytes reach the provider.

## Review-page panel and API (CL-77)

- `POST /api/review/deliveries/{delivery_id}/second-opinion`
  (alias `POST /api/review/{delivery_id}/second-opinion`):
  researcher or reviewer demo role (`second_opinion.request`);
  runs one opinion on demand. The key is read server-side only.
- `GET` on the same path returns stored opinions plus the public
  provider config (never the key).
- `GET /api/review/second-opinion/config`: provider, model and
  `enabled` status for the panel.

The Reviewer page shows a second-opinion panel beside the human
disposition: model and settings, the structured assessment,
per-finding comments, and an "advisory only, does not change the
verdict" label. `second_opinion_unavailable` (with its reason,
including caps) and `unparseable` are shown explicitly. With no
key configured the panel says the feature is off and the rest of
the page works normally. No request from the browser carries the
API key, and with the picture opt-in off no request carries
picture bytes to the provider.
