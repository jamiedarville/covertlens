"""Authentication for the web service (CL-67, OP-01).

Three modes, chosen by `COVERTLENS_AUTH_MODE`:

- `oidc` — real authentication. Browsers sign in with the OpenID
  Connect authorization-code flow (PKCE S256, `state` bound to the
  browser by a login cookie, `nonce` checked in the ID token) and get
  a server-side session (`covertlens_session`, HttpOnly, SameSite=Lax,
  Secure). Machine clients (the harness, `GateClient`) send
  `Authorization: Bearer <JWT>` validated against the issuer's JWKS.
  Identities map to CL-11 roles and dataset scopes through
  `config/identity-mapping.json` (`covertlens.identity`). `X-Demo-Role`
  is ignored.
- `demo` — the Phase 2 labelled demo roles (`X-Demo-Role`), not
  authentication. Only honoured in demo builds
  (`COVERTLENS_DEMO_BUILD` not `off`); a production image never
  trusts the header, whatever the environment says.
- `off` — every request is an anonymous viewer.

Without `COVERTLENS_AUTH_MODE`, the legacy `COVERTLENS_DEMO_ROLES=on`
still selects `demo`; otherwise the mode is `off`.

Token checks (both paths): signature by a JWKS key whose `kid`
matches, algorithm from an asymmetric allow-list (never `none` or
HMAC), `iss` equal to the configured issuer, `aud` containing the
client id (or `COVERTLENS_OIDC_AUDIENCE` for bearer tokens), `azp`
when there are several audiences, `exp`/`iat` present with 60 s
leeway, and `sub` present.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

AUTH_MODE_ENV = "COVERTLENS_AUTH_MODE"
DEMO_ROLES_ENV = "COVERTLENS_DEMO_ROLES"
DEMO_BUILD_ENV = "COVERTLENS_DEMO_BUILD"
SESSION_COOKIE = "covertlens_session"
LOGIN_COOKIE = "covertlens_login"
LOGIN_TTL_S = 600
JWKS_TTL_S = 600
JWKS_MIN_REFRESH_S = 30
LEEWAY_S = 60
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "ES256", "ES384")
MODES = ("oidc", "demo", "off")


class AuthenticationFailed(Exception):
    """A presented credential is invalid (401), never a silent viewer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def demo_build() -> bool:
    """False in production images: they never honour demo roles."""
    return os.environ.get(DEMO_BUILD_ENV, "on").strip().lower() not in (
        "off",
        "0",
        "false",
        "no",
    )


def auth_mode() -> str:
    """Active mode; read per request so tests and operators can switch it."""
    mode = os.environ.get(AUTH_MODE_ENV, "").strip().lower()
    if not mode:
        legacy = os.environ.get(DEMO_ROLES_ENV, "off").strip().lower()
        mode = "demo" if legacy in ("on", "1", "true", "yes") else "off"
    if mode not in MODES:
        raise ValueError(f"{AUTH_MODE_ENV} must be one of {MODES}")
    if mode == "demo" and not demo_build():
        return "off"
    return mode


def _local_http(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1")


@dataclass(frozen=True)
class OidcSettings:
    """OIDC client settings, from `COVERTLENS_OIDC_*` environment variables."""

    issuer: str
    client_id: str
    client_secret: str | None = None
    redirect_uri: str | None = None
    scopes: str = "openid email profile"
    audience: str | None = None
    session_ttl_s: int = 8 * 3600
    cookie_secure: bool = True

    @classmethod
    def from_env(cls) -> OidcSettings:
        issuer = os.environ.get("COVERTLENS_OIDC_ISSUER", "").strip().rstrip("/")
        client_id = os.environ.get("COVERTLENS_OIDC_CLIENT_ID", "").strip()
        if not issuer or not client_id:
            raise ValueError(
                "oidc mode needs COVERTLENS_OIDC_ISSUER and COVERTLENS_OIDC_CLIENT_ID"
            )
        if urlsplit(issuer).scheme != "https" and not _local_http(issuer):
            raise ValueError("COVERTLENS_OIDC_ISSUER must be https (or local http)")
        redirect = os.environ.get("COVERTLENS_OIDC_REDIRECT_URI", "").strip() or None
        secure = os.environ.get("COVERTLENS_COOKIE_SECURE", "on").strip().lower()
        return cls(
            issuer=issuer,
            client_id=client_id,
            client_secret=os.environ.get("COVERTLENS_OIDC_CLIENT_SECRET") or None,
            redirect_uri=redirect,
            scopes=os.environ.get("COVERTLENS_OIDC_SCOPES", "openid email profile"),
            audience=os.environ.get("COVERTLENS_OIDC_AUDIENCE") or None,
            session_ttl_s=int(os.environ.get("COVERTLENS_SESSION_TTL_S", 8 * 3600)),
            cookie_secure=secure not in ("off", "0", "false", "no"),
        )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class OidcClient:
    """Discovery, JWKS and token validation for one issuer."""

    def __init__(self, settings: OidcSettings, http: Any = None) -> None:
        import httpx

        self.settings = settings
        self._http = http or httpx.Client(timeout=10.0, follow_redirects=False)
        self._lock = threading.Lock()
        self._discovery: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._jwks_at = 0.0

    def _get_json(self, url: str) -> dict[str, Any]:
        import httpx

        try:
            response = self._http.get(url)
        except httpx.HTTPError:
            raise AuthenticationFailed("identity provider unreachable") from None
        if response.status_code != 200:
            raise AuthenticationFailed(
                f"identity provider returned {response.status_code}"
            )
        try:
            doc = response.json()
        except ValueError:
            raise AuthenticationFailed("identity provider returned non-JSON") from None
        if not isinstance(doc, dict):
            raise AuthenticationFailed("identity provider returned a non-object")
        return doc

    def discovery(self) -> dict[str, Any]:
        with self._lock:
            if self._discovery is None:
                doc = self._get_json(
                    self.settings.issuer + "/.well-known/openid-configuration"
                )
                if str(doc.get("issuer", "")).rstrip("/") != self.settings.issuer:
                    raise AuthenticationFailed("discovery issuer does not match")
                for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                    if not doc.get(key):
                        raise AuthenticationFailed(f"discovery lacks {key}")
                self._discovery = doc
            return self._discovery

    def _keys(self, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            stale = self._jwks is None or now - self._jwks_at > JWKS_TTL_S
            allowed = now - self._jwks_at > JWKS_MIN_REFRESH_S
            need = stale or (refresh and allowed)
        if need:
            doc = self._get_json(self.discovery()["jwks_uri"])
            with self._lock:
                self._jwks = doc
                self._jwks_at = now
        with self._lock:
            return dict(self._jwks or {})

    def _signing_key(self, kid: str | None, alg: str) -> Any:
        import jwt

        for refresh in (False, True):
            for key in self._keys(refresh=refresh).get("keys") or []:
                if kid is not None and key.get("kid") != kid:
                    continue
                if key.get("use") not in (None, "sig"):
                    continue
                if key.get("alg") not in (None, alg):
                    continue
                try:
                    return jwt.PyJWK(key, algorithm=alg)
                except jwt.PyJWTError as exc:
                    raise AuthenticationFailed(f"unusable signing key: {exc}") from None
        raise AuthenticationFailed("no matching signing key")

    def validate(
        self,
        token: str,
        *,
        audience: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Verified claims of a JWT from this issuer, or AuthenticationFailed."""
        import jwt

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AuthenticationFailed("malformed token") from None
        alg = str(header.get("alg") or "")
        if alg not in ALLOWED_ALGORITHMS:
            raise AuthenticationFailed(f"token algorithm {alg!r} is not allowed")
        key = self._signing_key(header.get("kid"), alg)
        expected_audience = audience or self.settings.client_id
        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=[alg],
                audience=expected_audience,
                issuer=self.settings.issuer,
                leeway=LEEWAY_S,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationFailed(f"invalid token: {exc}") from None
        aud = claims.get("aud")
        if isinstance(aud, list) and len(aud) > 1:
            if claims.get("azp") != expected_audience:
                raise AuthenticationFailed("token azp does not name this client")
        if nonce is not None and not hmac.compare_digest(
            str(claims.get("nonce") or ""), nonce
        ):
            raise AuthenticationFailed("ID token nonce does not match")
        return claims

    def authorization_url(
        self, *, state: str, nonce: str, challenge: str, redirect_uri: str
    ) -> str:
        endpoint = self.discovery()["authorization_endpoint"]
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": redirect_uri,
                "scope": self.settings.scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{endpoint}{'&' if '?' in endpoint else '?'}{query}"

    def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> str:
        """Authorization code -> ID token (client_secret_basic when configured)."""
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        extra: dict[str, Any] = {}
        if self.settings.client_secret:
            extra["auth"] = (self.settings.client_id, self.settings.client_secret)
        else:
            form["client_id"] = self.settings.client_id
        import httpx

        try:
            response = self._http.post(
                self.discovery()["token_endpoint"],
                data=form,
                headers={"Accept": "application/json"},
                **extra,
            )
        except httpx.HTTPError:
            raise AuthenticationFailed("token endpoint unreachable") from None
        if response.status_code != 200:
            raise AuthenticationFailed(
                f"token endpoint returned {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError:
            raise AuthenticationFailed("token endpoint returned non-JSON") from None
        token = body.get("id_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise AuthenticationFailed("token endpoint returned no id_token")
        return token


class SessionStore:
    """Server-side sessions and pending logins (SQLite, token hashes only)."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY,"
                " identity TEXT NOT NULL, created_at REAL NOT NULL,"
                " expires_at REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS logins (state_hash TEXT PRIMARY KEY,"
                " binding_hash TEXT NOT NULL, nonce TEXT NOT NULL,"
                " verifier TEXT NOT NULL, next_path TEXT NOT NULL,"
                " expires_at REAL NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def create_session(self, identity: Any, ttl_s: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (_digest(token), json.dumps(identity.to_dict()), now, now + ttl_s),
            )
        return token

    def get_session(self, token: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT identity, expires_at FROM sessions WHERE token_hash = ?",
                (_digest(token),),
            ).fetchone()
            if row is None:
                return None
            if row[1] < time.time():
                db.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (_digest(token),)
                )
                return None
        return json.loads(row[0])

    def delete_session(self, token: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))

    def begin_login(self, next_path: str) -> dict[str, str]:
        login = {
            "state": secrets.token_urlsafe(32),
            "binding": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "verifier": secrets.token_urlsafe(48),
        }
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM logins WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO logins VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _digest(login["state"]),
                    _digest(login["binding"]),
                    login["nonce"],
                    login["verifier"],
                    next_path,
                    now + LOGIN_TTL_S,
                ),
            )
        return login

    def finish_login(self, state: str, binding: str) -> dict[str, str]:
        """Single-use: the pending login is deleted whatever happens next."""
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT binding_hash, nonce, verifier, next_path, expires_at"
                " FROM logins WHERE state_hash = ?",
                (_digest(state),),
            ).fetchone()
            db.execute("DELETE FROM logins WHERE state_hash = ?", (_digest(state),))
        if row is None:
            raise AuthenticationFailed("unknown or reused login state")
        if row[4] < time.time():
            raise AuthenticationFailed("login expired")
        if not hmac.compare_digest(row[0], _digest(binding or "")):
            raise AuthenticationFailed("login was started in another browser")
        return {"nonce": row[1], "verifier": row[2], "next_path": row[3]}


def safe_next_path(value: str | None) -> str:
    """Only same-origin relative paths; anything else lands on '/'."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if "\\" in value or any(ord(ch) < 32 for ch in value):
        return "/"
    return value[:512]


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationFailed("Authorization header must be a Bearer token")
    return token.strip()
