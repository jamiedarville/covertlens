# Gate integrity: races, retries and cache invalidation (CL-20 · ENF-05)

`covertlens.integrity.AnalysisCache` holds the two kinds of cached
result, with keys that encode exactly what each result depends on.
The zero-unauthorized-access property itself belongs to the CL-18
gate; this task verifies it under races, retries and alternate
references, and proves the cache invalidation rules.

## Invalidation keys

| Cached result | Key | Invalidated by |
|---|---|---|
| Image score (`Finding`) | `(content_hash, detector_name, detector_version, detector_config_version)` | changed bytes (new hash, C-05), detector bump, detector-config bump |
| Verdict (`VerdictDecision`) | score rows + `threshold_config.version` + `context_fingerprint(context)` | any score change, threshold-config change, **run-context change** |

`context_fingerprint` is a SHA-256 over the canonical JSON of the
caller-supplied context (run/episode identities, sender/recipient,
declared exceptions — whatever the caller gates on). When only the
context changes, `get_or_decide` misses and recomputes the verdict,
while `get_or_score` still hits: the image score, which never
depended on context, is safely reused. `stats()` counts
hits/misses/stores per cache so tests can prove which path ran.

## Race / retry / alternate-reference verification

`tests/test_integrity.py` drives the CL-18 gate with:

- concurrent pre-verdict and post-quarantine access storms
  (zero bytes served, `access_attempt_report()["unauthorized_served"] == 0`),
- delivery retries (same deterministic `delivery_id`, one attempted
  event) interleaved with access attempts,
- alternate references to the same bytes (file reference, cached
  link, direct route serve) all hitting the same verdict check.

## Out of scope here

Replay experiments (CL-21), reproducibility pinning (CL-26) and the
route coverage audit (CL-32) build on this but are separate tasks.
