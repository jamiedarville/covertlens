"""CL-67: OIDC authentication, real roles and dataset scopes.

A fake identity provider (RSA key, JWKS, discovery, token endpoint)
runs in-process behind `httpx.MockTransport`; nothing touches the
network. The CL-33 permission checks are repeated through the HTTP
layer with authenticated principals.
"""

import base64
import hashlib
import json
import os
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

os.environ.setdefault("COVERTLENS_PRECOMPUTE", "off")
os.environ.setdefault(
    "COVERTLENS_DATA_DIR", tempfile.mkdtemp(prefix="covertlens-auth-test-")
)

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app import auth  # noqa: E402
from app.main import app  # noqa: E402
from covertlens.geo_benchmark import build_structured_pair  # noqa: E402
from covertlens.identity import (  # noqa: E402
    HUMAN_ROLES,
    Identity,
    identity_from_claims,
    load_identity_mapping,
    principal_for,
    validate_identity_mapping,
)

ISSUER = "https://idp.test"
CLIENT = "covertlens-web"
RUN = "run_auth"
OTHER_RUN = "beta-run"
MAPPING = {
    "schema": "covertlens.identity-mapping",
    "mapping_version": "test-1",
    "default": {"roles": ["viewer"], "datasets": []},
    "rules": [
        {
            "id": "researchers",
            "match": {"claim": "groups", "op": "equals", "value": "researchers"},
            "roles": ["researcher"],
            "datasets": ["run_auth*"],
        },
        {
            "id": "reviewers",
            "match": {"claim": "groups", "op": "equals", "value": "reviewers"},
            "roles": ["reviewer"],
            "datasets": ["run_auth*"],
        },
        {
            "id": "beta",
            "match": {"claim": "groups", "op": "equals", "value": "tenant-beta"},
            "roles": ["researcher"],
            "datasets": ["beta-*"],
        },
        {
            "id": "harness",
            "match": {"claim": "groups", "op": "equals", "value": "harness"},
            "roles": ["viewer"],
            "datasets": ["run_auth*", "beta-*"],
        },
    ],
}


class FakeIdP:
    """Discovery + JWKS + token endpoint for one RSA signing key."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "k1"
        self.codes = {}
        self.token_requests = []

    def jwk(self):
        doc = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {**doc, "kid": self.kid, "use": "sig", "alg": "RS256"}

    def mint(self, *, sub="alice", groups=(), aud=CLIENT, iss=ISSUER, **extra):
        now = int(time.time())
        claims = {
            "iss": iss,
            "sub": sub,
            "aud": aud,
            "iat": now,
            "exp": now + 300,
            "groups": list(groups),
            "name": sub.title(),
            **extra,
        }
        return jwt.encode(
            claims, self.key, algorithm="RS256", headers={"kid": self.kid}
        )

    def handler(self, request):
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if url == f"{ISSUER}/jwks":
            return httpx.Response(200, json={"keys": [self.jwk()]})
        if url == f"{ISSUER}/token" and request.method == "POST":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            pending = self.codes.pop(form.get("code"), None)
            if pending is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(form["code_verifier"].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            if challenge != pending["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            token = self.mint(nonce=pending["nonce"], **pending["claims"])
            return httpx.Response(200, json={"id_token": token, "token_type": "Bearer"})
        return httpx.Response(404)

    def authorize(self, location, **claims):
        """What the IdP does after the user signs in: issue a code."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        assert query["code_challenge_method"] == "S256"
        assert query["client_id"] == CLIENT
        code = f"code-{len(self.codes)}-{query['state'][:6]}"
        self.codes[code] = {
            "challenge": query["code_challenge"],
            "nonce": query["nonce"],
            "claims": claims,
        }
        return code, query["state"]


@pytest.fixture()
def idp():
    return FakeIdP()


@pytest.fixture()
def client(tmp_path, monkeypatch, idp):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(MAPPING))
    monkeypatch.setattr(main_module, "GATE_STORE_DIR", tmp_path / "gate-store")
    monkeypatch.setattr(main_module, "AUTH_DIR", tmp_path / "auth")
    monkeypatch.setenv("COVERTLENS_AUTH_MODE", "oidc")
    monkeypatch.setenv("COVERTLENS_DEMO_ROLES", "on")  # must be ignored
    monkeypatch.setenv("COVERTLENS_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("COVERTLENS_OIDC_CLIENT_ID", CLIENT)
    monkeypatch.setenv("COVERTLENS_COOKIE_SECURE", "off")
    monkeypatch.setenv("COVERTLENS_IDENTITY_MAPPING", str(mapping))
    main_module._reset_gate_for_tests()
    main_module._reset_auth_for_tests(
        http=httpx.Client(transport=httpx.MockTransport(idp.handler))
    )
    with TestClient(app) as test_client:
        yield test_client
    main_module._reset_gate_for_tests()
    main_module._reset_auth_for_tests()


def bearer(idp, **claims):
    return {"Authorization": f"Bearer {idp.mint(**claims)}"}


def _quarantined(client, idp, run_id=RUN):
    _clean, encoded = build_structured_pair("height_position", 0)
    created = client.post(
        "/api/gate/deliveries",
        files={"file": ("scene.png", encoded.data, "image/png")},
        data={"run_id": run_id, "route_id": "R-01", "episode_id": "ep_1"},
        headers=bearer(idp, sub="harness-1", groups=["harness"]),
    )
    assert created.status_code == 200, created.text
    delivery_id = created.json()["delivery_id"]
    group = "researchers" if run_id.startswith("run_auth") else "tenant-beta"
    decided = client.post(
        f"/api/gate/deliveries/{delivery_id}/verdict",
        json={"verdict": "quarantine"},
        headers=bearer(idp, sub="rita", groups=[group]),
    )
    assert decided.status_code == 200, decided.text
    return delivery_id


# -- identity mapping (library) ----------------------------------------------


def test_shipped_mapping_is_valid_and_deny_by_default():
    mapping = load_identity_mapping()
    assert validate_identity_mapping(mapping.doc) == []
    nobody = identity_from_claims({"sub": "x", "iss": ISSUER}, mapping)
    assert nobody.roles == frozenset({"viewer"})
    assert nobody.dataset_patterns == ()
    assert principal_for(nobody, "any-run").datasets == frozenset()
    tenant = identity_from_claims(
        {"sub": "t", "iss": ISSUER, "groups": ["tenant-alpha"]}, mapping
    )
    assert principal_for(tenant, "alpha-1").datasets == frozenset({"alpha-1"})
    assert principal_for(tenant, "beta-1").datasets == frozenset()


def test_mapping_refuses_system_roles_and_default_datasets():
    bad = json.loads(json.dumps(MAPPING))
    bad["rules"][0]["roles"] = ["scorer"]
    bad["default"]["datasets"] = ["*"]
    errors = validate_identity_mapping(bad)
    assert any("scorer" in e for e in errors)
    assert any("deny by default" in e for e in errors)
    assert set(HUMAN_ROLES) == {
        "viewer",
        "researcher",
        "reviewer",
        "operator",
        "approver",
    }


def test_actor_id_is_the_stable_subject():
    mapping = load_identity_mapping()
    identity = identity_from_claims(
        {"sub": "u-123", "iss": ISSUER, "email": "a@example.org"}, mapping
    )
    assert identity.actor_id == "oidc:u-123"
    assert Identity.from_dict(identity.to_dict()) == identity


# -- CL-33 permission checks through the HTTP layer ---------------------------


def test_cl33_denials_hold_through_http_with_authenticated_principals(client, idp):
    delivery_id = _quarantined(client, idp)
    original = f"/api/review/deliveries/{delivery_id}/original"
    reviewer_image = f"/api/gate/deliveries/{delivery_id}/reviewer-image"
    export = f"/api/review/runs/{RUN}/export"
    agent = bearer(idp, sub="agent-7")  # matches no rule: viewer, no dataset
    wrong_dataset = bearer(idp, sub="bea", groups=["tenant-beta"])
    researcher = bearer(idp, sub="rita", groups=["researchers"])
    # agent_read / agent_export
    assert client.get(original, headers=agent).status_code == 403
    assert client.get(reviewer_image, headers=agent).status_code == 403
    assert client.get(export, headers=agent).status_code == 403
    # wrong_dataset_read / wrong_dataset_export
    assert client.get(original, headers=wrong_dataset).status_code == 403
    assert client.get(export, headers=wrong_dataset).status_code == 403
    # The scoped researcher is allowed, and the audit names them.
    assert client.get(original, headers=researcher).status_code == 200
    assert client.get(reviewer_image, headers=researcher).status_code == 200
    package = client.get(export, headers=researcher)
    assert package.status_code == 200
    audit = client.get(f"/api/review/audit?run_id={RUN}", headers=researcher).json()
    assert audit["chain_valid"] is True
    actors = {entry["actor_id"] for entry in audit["entries"]}
    assert "oidc:rita" in actors
    assert "oidc:agent-7" in actors and "oidc:bea" in actors  # denials audited
    assert not any(actor.startswith("demo-") for actor in actors)


def test_demo_role_header_is_ignored_in_oidc_mode(client, idp):
    delivery_id = _quarantined(client, idp)
    response = client.get(
        f"/api/review/deliveries/{delivery_id}/original",
        headers={"X-Demo-Role": "researcher"},
    )
    assert response.status_code == 403
    roles = client.get("/api/review/roles").json()
    assert roles["enabled"] is False and roles["auth_mode"] == "oidc"


def test_reviewer_role_reads_decodes_and_records_dispositions(client, idp):
    delivery_id = _quarantined(client, idp)
    reviewer = bearer(idp, sub="ravi", groups=["reviewers"])
    decode = client.get(
        f"/api/review/deliveries/{delivery_id}/candidate-decode", headers=reviewer
    )
    assert decode.status_code in (200, 404)
    disposition = client.post(
        f"/api/review/deliveries/{delivery_id}/disposition",
        json={"disposition": "suspected", "note": "looks structured"},
        headers=reviewer,
    )
    assert disposition.status_code == 200, disposition.text
    assert disposition.json()["reviewer"] == "oidc:ravi"
    verdict = client.post(
        f"/api/gate/deliveries/{delivery_id}/verdict",
        json={"verdict": "log"},
        headers=reviewer,
    )
    assert verdict.status_code == 403  # verdict.override is researcher-only


def test_tenants_are_isolated(client, idp):
    _quarantined(client, idp, run_id=OTHER_RUN)
    _quarantined(client, idp, run_id=RUN)
    alpha = bearer(idp, sub="rita", groups=["researchers"])
    beta = bearer(idp, sub="bea", groups=["tenant-beta"])
    assert client.get("/api/gate/runs", headers=alpha).json()["runs"] == [RUN]
    assert client.get("/api/gate/runs", headers=beta).json()["runs"] == [OTHER_RUN]
    assert client.get("/api/gate/runs").json()["runs"] == []
    assert client.get(f"/api/gate/runs/{OTHER_RUN}", headers=alpha).status_code == 403
    assert (
        client.get(f"/api/review/runs/{OTHER_RUN}/queue", headers=alpha).status_code
        == 403
    )
    assert client.get(f"/api/trace/runs/{OTHER_RUN}", headers=alpha).status_code == 403
    assert client.get(f"/api/trace/runs/{RUN}", headers=alpha).status_code == 200
    anonymous = client.post(
        "/api/gate/deliveries",
        files={"file": ("x.png", b"\x89PNG", "image/png")},
        data={"run_id": RUN},
    )
    assert anonymous.status_code == 401


@pytest.mark.parametrize(
    "token_change",
    [
        "expired",
        "wrong_audience",
        "wrong_issuer",
        "alg_none",
        "hs256",
        "other_key",
        "garbage",
    ],
)
def test_forged_or_mismatched_tokens_are_rejected(client, idp, token_change):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "mallory",
        "aud": CLIENT,
        "iat": now,
        "exp": now + 300,
        "groups": ["researchers"],
    }
    if token_change == "expired":
        token = jwt.encode(
            {**claims, "exp": now - 600},
            idp.key,
            algorithm="RS256",
            headers={"kid": idp.kid},
        )
    elif token_change == "wrong_audience":
        token = idp.mint(sub="mallory", groups=["researchers"], aud="someone-else")
    elif token_change == "wrong_issuer":
        token = idp.mint(sub="mallory", groups=["researchers"], iss="https://evil.test")
    elif token_change == "alg_none":
        token = jwt.encode(claims, None, algorithm="none")
    elif token_change == "hs256":
        public_pem = idp.key.public_key().public_bytes(
            encoding=__import__(
                "cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]
            ).Encoding.PEM,
            format=__import__(
                "cryptography.hazmat.primitives.serialization",
                fromlist=["PublicFormat"],
            ).PublicFormat.SubjectPublicKeyInfo,
        )
        token = jwt.encode(
            claims,
            hashlib.sha256(public_pem).digest(),
            algorithm="HS256",
            headers={"kid": idp.kid},
        )
    elif token_change == "other_key":
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(claims, other, algorithm="RS256", headers={"kid": idp.kid})
    else:
        token = "not.a.jwt"
    response = client.get(
        f"/api/trace/runs/{RUN}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert "invalid_token" in response.headers["www-authenticate"]


# -- browser sign-in (code flow) ---------------------------------------------


def _sign_in(client, idp, next_path="/review", **claims):
    start = client.get(f"/api/auth/login?next={next_path}", follow_redirects=False)
    assert start.status_code == 302
    location = start.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize?")
    code, state = idp.authorize(location, **claims)
    return client.get(
        f"/api/auth/callback?code={code}&state={state}", follow_redirects=False
    )


def test_code_flow_creates_a_server_side_session(client, idp):
    done = _sign_in(client, idp, sub="rita", groups=["researchers"])
    assert done.status_code == 302 and done.headers["location"] == "/review"
    cookie = done.headers["set-cookie"]
    assert "covertlens_session=" in cookie and "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    me = client.get("/api/auth/me").json()
    assert me["authenticated"] is True and me["actor_id"] == "oidc:rita"
    assert me["roles"] == ["researcher"]
    # PKCE: the verifier went to the token endpoint, no client secret.
    assert idp.token_requests[-1]["code_verifier"]
    assert client.get(f"/api/trace/runs/{RUN}").status_code == 200
    assert client.post("/api/auth/logout").json() == {"signed_out": True}
    assert client.get("/api/auth/me").json()["authenticated"] is False
    assert client.get(f"/api/trace/runs/{RUN}").status_code == 403


def test_state_is_single_use_and_bound_to_the_browser(client, idp):
    start = client.get("/api/auth/login", follow_redirects=False)
    code, state = idp.authorize(start.headers["location"], sub="rita")
    # Another browser (no login cookie) cannot finish this login.
    other = TestClient(app)
    stolen = other.get(
        f"/api/auth/callback?code={code}&state={state}", follow_redirects=False
    )
    assert stolen.status_code == 400
    # The state was consumed by that attempt: replay fails too.
    replay = client.get(
        f"/api/auth/callback?code={code}&state={state}", follow_redirects=False
    )
    assert replay.status_code == 400


def test_nonce_mismatch_fails_sign_in(client, idp, monkeypatch):
    start = client.get("/api/auth/login", follow_redirects=False)
    code, state = idp.authorize(start.headers["location"], sub="rita")
    idp.codes[code]["nonce"] = "attacker-nonce"
    done = client.get(
        f"/api/auth/callback?code={code}&state={state}", follow_redirects=False
    )
    assert done.status_code == 400
    assert "nonce" in done.json()["reason"]


@pytest.mark.parametrize("next_path", ["//evil.test/x", "https://evil.test", "/\\evil"])
def test_next_path_cannot_redirect_off_site(client, idp, next_path):
    done = _sign_in(client, idp, next_path=next_path, sub="rita")
    assert done.headers["location"] == "/"


def test_safe_next_path_unit():
    assert auth.safe_next_path("/review?run=1") == "/review?run=1"
    assert auth.safe_next_path(None) == "/"
    assert auth.safe_next_path("relative") == "/"


def test_production_build_never_honours_demo_roles(monkeypatch):
    monkeypatch.delenv("COVERTLENS_AUTH_MODE", raising=False)
    monkeypatch.setenv("COVERTLENS_DEMO_ROLES", "on")
    assert auth.auth_mode() == "demo"
    monkeypatch.setenv("COVERTLENS_DEMO_BUILD", "off")
    assert auth.auth_mode() == "off"
    monkeypatch.setenv("COVERTLENS_AUTH_MODE", "demo")
    assert auth.auth_mode() == "off"


def test_oidc_settings_require_https_issuer(monkeypatch):
    monkeypatch.setenv("COVERTLENS_OIDC_ISSUER", "http://idp.example.org")
    monkeypatch.setenv("COVERTLENS_OIDC_CLIENT_ID", CLIENT)
    with pytest.raises(ValueError, match="https"):
        auth.OidcSettings.from_env()


def test_unreachable_identity_provider_is_a_sign_in_failure(client, monkeypatch):
    def down(request):
        raise httpx.ConnectError("idp down", request=request)

    main_module._reset_auth_for_tests(
        http=httpx.Client(transport=httpx.MockTransport(down))
    )
    response = client.get(
        f"/api/trace/runs/{RUN}", headers={"Authorization": "Bearer a.b.c"}
    )
    assert response.status_code == 401
    assert client.get("/api/auth/login", follow_redirects=False).status_code == 401
