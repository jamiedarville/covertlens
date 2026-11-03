# Multi-tenant authentication and real roles (CL-67)

Implements: CL-67 (OP-01). Replaces the demo-role toggle
([reviewer-role.md](reviewer-role.md)) for real deployments. Config:
[config/identity-mapping.json](../../config/identity-mapping.json)
(validated by `covertlens.identity.validate_identity_mapping`).

## Modes (`COVERTLENS_AUTH_MODE`)

| Mode | Who you are | `X-Demo-Role` |
|---|---|---|
| `oidc` | the authenticated identity (session cookie or bearer token), mapped to roles and dataset scopes | ignored |
| `demo` | the demo role in `X-Demo-Role` (not authentication) | honoured, demo builds only |
| `off` | an anonymous viewer | ignored |

Unset, the legacy `COVERTLENS_DEMO_ROLES=on` still selects `demo`.
A production image (`docker build --build-arg DEMO_BUILD=off`) sets
`COVERTLENS_DEMO_BUILD=off`: the server never honours demo roles
there, whatever the environment says, and the frontend bundle has no
demo-role picker and never sends the header
(`npm run test:prod-build` checks the bundle). In `oidc` mode the
service refuses to start with incomplete OIDC settings or an invalid
mapping.

## OIDC

Settings: `COVERTLENS_OIDC_ISSUER` (https, or local http for
development), `COVERTLENS_OIDC_CLIENT_ID`, optional
`COVERTLENS_OIDC_CLIENT_SECRET` (client_secret_basic; public clients
use PKCE alone), `COVERTLENS_OIDC_REDIRECT_URI` (default
`/api/auth/callback` on this host), `COVERTLENS_OIDC_SCOPES`,
`COVERTLENS_OIDC_AUDIENCE` (bearer tokens; default the client id),
`COVERTLENS_SESSION_TTL_S` (8 h), `COVERTLENS_COOKIE_SECURE` (on),
`COVERTLENS_IDENTITY_MAPPING` (mapping file path).

- **Browser sign-in:** `GET /api/auth/login?next=/review` starts the
  authorization-code flow with PKCE S256, a random `state` and
  `nonce`, and a login cookie that binds the state to this browser.
  `GET /api/auth/callback` accepts the state once (stored as a hash,
  deleted on first use), exchanges the code, validates the ID token
  (`nonce` included), maps the claims and creates a server-side
  session (`covertlens_session`: random token, stored hashed,
  HttpOnly, SameSite=Lax, Secure). `next` must be a same-site
  relative path. `POST /api/auth/logout` deletes the session.
  `GET /api/auth/me` reports mode, identity, roles and scopes.
- **Machine clients:** `Authorization: Bearer <JWT>` from the same
  issuer (`GateClient(bearer_token=...)` for harnesses).
- **Token checks:** signature by a JWKS key with matching `kid`
  (keys refreshed on an unknown `kid`, at most every 30 s), algorithm
  from an asymmetric allow-list (RS/PS/ES; never `none` or HMAC),
  `iss`, `aud` (and `azp` with several audiences), `exp`/`iat` with
  60 s leeway, `sub`. A presented but invalid credential is a 401,
  never a silent viewer.
- **CSRF:** cookie sessions rely on SameSite=Lax plus the CL-78
  cross-site and JSON-only checks on every unsafe `/api` request.

## Identity mapping

Rules match a claim (`groups` by default; `equals`, `contains` or
`suffix`) and grant human roles (`viewer`, `researcher`, `reviewer`,
`operator`, `approver`; system roles `agent`, `detector_worker`,
`scorer` are refused) plus dataset scope patterns (`fnmatch` over run
ids). Every matching rule adds its grants; an identity that matches
none gets the default grant, shipped as viewer with no dataset (the
validator refuses a default that names datasets). `principal_for`
turns an identity into a CL-11 `Principal` scoped to exactly the
requested dataset when a pattern covers it, so every
`EvidenceGateway` and runtime-policy check is unchanged and
dataset-scoped. The audit actor is `oidc:<sub>`.

## Multi-tenant isolation (OIDC mode)

Runs outside an identity's scopes are invisible and closed: the gate
run list is filtered; run detail, event stream, delivery creation,
analysis and recipient image, the review queue and delivery detail
need the run in scope (401 anonymous, 403 out of scope); evidence
reads, decodes, dispositions, exports, audit, trace and verdicts keep
their runtime-policy permissions on the scoped principal. Store
access records for user-initiated analysis reads name the requester.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| Every `EvidenceGateway` permission check uses an authenticated principal | `_demo_principal` resolves the OIDC identity in `oidc` mode for every review/gate/trace/export call (`app/main.py`); `tests/test_auth.py::test_demo_role_header_is_ignored_in_oidc_mode` |
| The CL-33 permission tests pass through the HTTP layer | `test_cl33_denials_hold_through_http_with_authenticated_principals`: agent read/export, wrong-dataset read/export denied; the scoped researcher allowed; audit chain valid and naming `oidc:` actors |
| OIDC login; roles and dataset scopes via configuration | `test_code_flow_creates_a_server_side_session`, `test_state_is_single_use_and_bound_to_the_browser`, `test_nonce_mismatch_fails_sign_in`, `test_next_path_cannot_redirect_off_site`, `test_forged_or_mismatched_tokens_are_rejected` (expired, wrong audience/issuer, `alg: none`, HS256 key confusion, foreign key, garbage), `test_tenants_are_isolated`, `test_shipped_mapping_is_valid_and_deny_by_default` |
| Demo toggle removed in non-demo builds | `test_production_build_never_honours_demo_roles`; `npm run test:prod-build`; frontend `tests/auth.test.tsx` |
