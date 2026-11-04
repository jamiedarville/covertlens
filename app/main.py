"""CovertLens web service (CL-47, CL-48, CL-51).

Thin FastAPI layer over the library:

- `POST /api/analyze` — multipart upload; analysis runs in a
  ProcessPoolExecutor (`COVERTLENS_WORKERS`, default 4) with a
  wall-clock deadline mapped to the library's `timeout` status;
  upload size is limited before the body is read; per-IP rate
  limit; reviewer-only fields are stripped by the worker.
- `POST /api/generate` — red-team image generation (CL-51);
  same pool, rate limit and deadline. Provenance is recorded
  in a persistent artifact store plus an append-only index
  with `source: red_team`; bytes serve from
  `GET /api/generated/{digest}.png|.jpg`.
- `GET /api/fixtures`, `GET /api/fixtures/{digest}.png`
- `GET /api/benchmarks/{name}` — cached precompute output.
- `GET /api/comparison` — cached landing-page skyline pair (CL-48).
- `GET /api/scorecard`, `GET /api/version`, `GET /api/health`.
- `GET /api/trace/runs/{run_id}` — Trace explorer view (CL-60):
  join records with explicit missing-link reasons, episode
  context, per-sender weak signals, action candidate inputs.
- `/api/review/*` — Reviewer page API (CL-59): demo roles
  (`viewer`/`researcher`/`reviewer` via `X-Demo-Role`) mapped to
  CL-11 principals; quarantined originals, reviewer-only candidate
  decodes, CL-25 dispositions, sealed review-package download and
  live audit-chain verification.
- Demo roles are not authentication (CL-78): `X-Demo-Role` is
  honoured only when `COVERTLENS_DEMO_ROLES=on` (the Docker image's
  demo setting); otherwise every request is a `viewer`, which holds
  no evidence permission. Evidence and state-changing endpoints
  check the CL-11 runtime policy: reviewer image needs
  `original.read`, audit and trace need `trace.read`, gate verdicts
  need `verdict.override`. JSON endpoints accept only
  `application/json`, and unsafe `/api` requests from another site
  are rejected (CSRF).
- OpenAPI at `/docs` (Swagger with its own hash-pinned CSP); the
  built React frontend is served
  statically at `/` (landing), `/analyze` (CL-48) and
  `/generate` (CL-51), with its hashed assets under `/assets/`.
  API and docs paths are never shadowed by the single-page app.

Precompute runs in a background thread at first start (health
answers immediately); cache lives under
`COVERTLENS_DATA_DIR` (default /data) keyed by library version
and git SHA.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import hashlib
import json
import logging
import multiprocessing
import os
import re
import signal
import tempfile
import threading
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

import covertlens
from covertlens.manifest import load_manifest
from covertlens.pinning import default_detector_versions

from . import auth
from .agent_demo import AgentDemo, demo_config
from .analysis_worker import analyze_bytes, frozen_config, public_geometric
from .generation_worker import generate_image

DATA_DIR = Path(os.environ.get("COVERTLENS_DATA_DIR", "/data"))
CACHE_DIR = DATA_DIR / "cache"
# Red-team generations (CL-51): image files, an append-only
# provenance index, and a persistent artifact store.
GENERATED_DIR = DATA_DIR / "generated"
RED_TEAM_INDEX = DATA_DIR / "red-team" / "index.jsonl"
RED_TEAM_STORE_DIR = DATA_DIR / "red-team" / "store"
# Live Gate (CL-53): persistent gate over a file-backed store.
GATE_STORE_DIR = DATA_DIR / "gate" / "store"
MAX_GENERATE_BODY_BYTES = 16 * 1024
_GENERATED_NAME = re.compile(r"^[0-9a-f]{64}\.(png|jpg)$")
# The Docker image copies the Vite build to app/static (CL-47);
# a local `npm run build` leaves it in app/frontend/dist. Serve
# whichever exists so both paths run the same app (CL-48).
STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_DIST_DIR = Path(__file__).resolve().parent / "frontend" / "dist"
STATIC_CANDIDATES = [STATIC_DIR, FRONTEND_DIST_DIR]
GIT_SHA = os.environ.get("GIT_SHA", "unknown")
ANALYZE_TIMEOUT_S = float(os.environ.get("COVERTLENS_ANALYZE_TIMEOUT_S", "30"))
MAX_UPLOAD_BYTES = int(
    os.environ.get("COVERTLENS_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024))
)
RATE_LIMIT_PER_MIN = int(os.environ.get("COVERTLENS_RATE_LIMIT_PER_MIN", "30"))
# Request bodies are capped before any parsing (CL-78): multipart
# uploads at the upload limit plus room for the form framing, other
# /api bodies at a small JSON limit.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_JSON_BODY_BYTES = 64 * 1024
# Rate-limited (expensive) endpoints: every upload path (CL-78).
RATE_LIMITED = frozenset(
    {
        ("POST", "/api/analyze"),
        ("POST", "/api/generate"),
        ("POST", "/api/gate/deliveries"),
    }
)
# Client IPs allowed to set X-Forwarded-For (a reverse proxy), comma
# separated. Without it the socket peer address is the client.
TRUSTED_PROXIES_ENV = "COVERTLENS_TRUSTED_PROXIES"
_RATE_SWEEP_EVERY = 256
# `X-Demo-Role` is trusted only when this is on (CL-78). Read per
# request so tests and operators can flip it without a restart.
DEMO_ROLES_ENV = "COVERTLENS_DEMO_ROLES"
# Extra origins allowed to make state-changing requests, comma
# separated (e.g. a reverse proxy's public origin).
ALLOWED_ORIGINS_ENV = "COVERTLENS_ALLOWED_ORIGINS"

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)
SWAGGER_CDN = "https://cdn.jsdelivr.net"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Built-in /docs and /redoc are off: /docs is served below with a
# CSP that allows Swagger's CDN and pins its one inline script.
app = FastAPI(
    title="CovertLens",
    version=covertlens.__version__,
    docs_url=None,
    redoc_url=None,
)

_log = logging.getLogger("covertlens.web")
_pool: concurrent.futures.ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()
_pool_rebuilds = 0
_rate_windows: dict[str, deque] = {}
_rate_lock = threading.Lock()
_rate_calls = 0
_precompute_started = False
_precompute_lock = threading.Lock()
_precompute_error: str | None = None
_data_dir_status: dict[str, Any] = {"checked": False}


def _worker_init() -> None:
    """Pool worker start-up: default signal handling (CL-78).

    Workers forked straight from the server inherited its handlers,
    which only set a flag in the parent's copy of the server, so
    SIGTERM did not stop them. The pool now starts workers from a
    forkserver; resetting the defaults here keeps that true whatever
    start method is in use.
    """
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def _executor() -> concurrent.futures.ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            workers = int(os.environ.get("COVERTLENS_WORKERS", "4"))
            # forkserver: workers fork from a clean process, not from the
            # threaded server (no inherited locks or handlers).
            method = (
                "forkserver"
                if "forkserver" in multiprocessing.get_all_start_methods()
                else "spawn"
            )
            _pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context(method),
                initializer=_worker_init,
            )
        return _pool


def _discard_pool(pool: concurrent.futures.ProcessPoolExecutor) -> None:
    """Kill a pool's workers and drop it; the next call builds a new one.

    A process pool cannot cancel one running task, so a timed-out or
    broken pool is replaced whole (CL-78). Other in-flight tasks fail
    with BrokenProcessPool and are retried once by `_run_in_pool`.
    """
    global _pool, _pool_rebuilds
    with _pool_lock:
        if _pool is pool:
            _pool = None
            _pool_rebuilds += 1
    processes = list(getattr(pool, "_processes", {}).values())
    for process in processes:
        try:
            process.kill()
        except (OSError, ValueError):
            pass
    pool.shutdown(wait=False, cancel_futures=True)


async def _run_in_pool(fn: Any, *args: Any, timeout: float) -> Any:
    """Run `fn(*args)` in the pool with a wall-clock deadline (CL-78).

    On timeout the worker is killed (the pool is replaced) and
    `TimeoutError` is raised. A broken pool (a worker died) is replaced
    and the call retried once, so one crash never leaves the service
    answering 500 until restart.
    """
    for attempt in (1, 2):
        pool = _executor()
        try:
            future = pool.submit(fn, *args)
        except concurrent.futures.process.BrokenProcessPool:
            _discard_pool(pool)
            continue
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout)
        except (TimeoutError, concurrent.futures.TimeoutError):
            _discard_pool(pool)
            raise TimeoutError from None
        except concurrent.futures.process.BrokenProcessPool:
            _discard_pool(pool)
            if attempt == 2:
                raise
    raise concurrent.futures.process.BrokenProcessPool("worker pool unavailable")


def _check_data_dir() -> dict[str, Any]:
    """Whether DATA_DIR is writable; recorded for /api/health (CL-78)."""
    global _data_dir_status
    status: dict[str, Any] = {"checked": True, "path": str(DATA_DIR)}
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=DATA_DIR, prefix=".write-check-"):
            pass
        status["writable"] = True
    except OSError as exc:
        status["writable"] = False
        status["error"] = f"{type(exc).__name__}: {exc}"
    _data_dir_status = status
    return status


def _data_dir_writable() -> bool:
    if not _data_dir_status.get("checked"):
        _check_data_dir()
    return bool(_data_dir_status.get("writable"))


def _data_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "detail": "data directory is not writable; gate, generation and "
            "review state cannot be stored",
            "data_dir": _data_dir_status,
        },
        status_code=503,
    )


def _fixtures() -> list[dict[str, Any]]:
    from covertlens.geo_benchmark import benign_controls
    from covertlens.geometric_fixtures import build_geo_dataset

    entries: list[dict[str, Any]] = []
    for fixture in build_geo_dataset():
        entries.append(
            {
                "fixture_id": fixture.fixture_id,
                "kind": fixture.role,
                "subfamily": fixture.subfamily,
                "content_hash": fixture.content_hash,
                "media_type": "image/png",
                "_data": fixture.data,
            }
        )
    for control in benign_controls():
        entries.append(
            {
                "fixture_id": control["control_id"],
                "kind": f"benign_control:{control['kind']}",
                "subfamily": None,
                "content_hash": control["content_hash"],
                "media_type": "image/png",
                "_data": control["data"],
            }
        )
    return entries


_FIXTURES: list[dict[str, Any]] | None = None


def _fixture_entries() -> list[dict[str, Any]]:
    global _FIXTURES
    if _FIXTURES is None:
        _FIXTURES = _fixtures()
    return _FIXTURES


def _cache_key() -> dict[str, str]:
    from scripts.precompute import cache_key

    return {**cache_key(), "git_sha": GIT_SHA}


def _precompute() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "covertlens_precompute",
        Path(__file__).resolve().parent.parent / "scripts" / "precompute.py",
    )
    if spec is None or spec.loader is None:
        return
    global _precompute_error
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.precompute(CACHE_DIR)
    except Exception as exc:  # noqa: BLE001 - reported through /api/health
        _precompute_error = f"{type(exc).__name__}: {exc}"
        _log.exception("precompute failed")


def _cache_ready() -> bool:
    from scripts.precompute import REPORT_COMMANDS

    return all(
        (CACHE_DIR / f"{name}.json").exists()
        for name in (*REPORT_COMMANDS, "provenance", "comparison")
    )


def _start_precompute() -> None:
    global _precompute_started
    if os.environ.get("COVERTLENS_PRECOMPUTE", "on") == "off":
        return
    with _precompute_lock:
        if _precompute_started:
            return
        _precompute_started = True
    key_file = CACHE_DIR / "key.json"
    try:
        current = json.loads(key_file.read_text()) if key_file.exists() else None
    except (OSError, json.JSONDecodeError):
        current = None
    if current == _cache_key() and _cache_ready():
        return
    threading.Thread(
        target=_precompute, daemon=True, name="covertlens-precompute"
    ).start()


def _static_root() -> Path | None:
    """First built-frontend directory that exists, if any (CL-48)."""
    for candidate in STATIC_CANDIDATES:
        if (candidate / "index.html").exists():
            return candidate
    return None


@app.on_event("startup")
def _startup() -> None:
    if auth.auth_mode() == "oidc":
        # Fail closed at start: a misconfigured OIDC deployment must not
        # come up and serve every request as an anonymous viewer.
        auth.OidcSettings.from_env()
        _mapping()
    status = _check_data_dir()
    if not status["writable"]:
        # Reported by /api/health and by every endpoint that needs the
        # data directory (503), instead of failing quietly (CL-78).
        _log.error("data directory %s is not writable: %s", DATA_DIR, status["error"])
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Cache is best-effort: endpoints report `computing`/404
        # rather than the service failing to start.
        pass
    _start_precompute()


def _allowed_origin_hosts(request: Request) -> set[str]:
    hosts = {
        (request.headers.get("host") or "").lower(),
        (request.headers.get("x-forwarded-host") or "").lower(),
    }
    for origin in os.environ.get(ALLOWED_ORIGINS_ENV, "").split(","):
        if origin.strip():
            hosts.add(urlsplit(origin.strip()).netloc.lower())
    hosts.discard("")
    return hosts


def _is_cross_site(request: Request) -> bool:
    """True when a browser marks the request as coming from another site.

    `Sec-Fetch-Site` covers current browsers; the `Origin` check covers
    older ones. Requests with neither (curl, tests) are not browser
    cross-site requests and pass.
    """
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site in ("cross-site", "same-site"):
        return True
    origin = request.headers.get("origin")
    if origin is None:
        return False
    if origin.strip().lower() == "null":
        return True
    return urlsplit(origin).netloc.lower() not in _allowed_origin_hosts(request)


@app.middleware("http")
async def _security_and_rate_limit(request: Request, call_next):
    if (
        request.method in _UNSAFE_METHODS
        and request.url.path.startswith("/api/")
        and _is_cross_site(request)
    ):
        # CSRF (CL-78): no cross-site form or fetch may change state.
        response = JSONResponse({"detail": "cross_site_request_blocked"}, 403)
        _apply_security_headers(response)
        return response
    expensive = (request.method, request.url.path) in RATE_LIMITED or (
        request.method == "POST" and request.url.path.startswith("/api/agent-demo")
    )
    if expensive and _rate_limited(_client_key(request)):
        response = JSONResponse({"detail": "rate_limited"}, status_code=429)
        _apply_security_headers(response)
        return response
    response = await call_next(request)
    _apply_security_headers(response)
    return response


def _client_key(request: Request) -> str:
    """Rate-limit key: the client IP (CL-78).

    `X-Forwarded-For` is honoured only when the socket peer is a
    trusted proxy (`COVERTLENS_TRUSTED_PROXIES`); the key is then the
    right-most address not itself a trusted proxy. Anyone else could
    forge the header to dodge the limit.
    """
    peer = request.client.host if request.client is not None else "unknown"
    trusted = {
        ip.strip() for ip in os.environ.get(TRUSTED_PROXIES_ENV, "").split(",") if ip
    }
    if peer not in trusted:
        return peer
    forwarded = [
        hop.strip()
        for hop in (request.headers.get("x-forwarded-for") or "").split(",")
        if hop.strip()
    ]
    for hop in reversed(forwarded):
        if hop not in trusted:
            return hop
    return peer


def _rate_limited(key: str) -> bool:
    """Sliding one-minute window per client; idle windows are evicted.

    In-process and per replica: N replicas allow N times the rate.
    """
    global _rate_calls
    now = time.time()
    with _rate_lock:
        _rate_calls += 1
        if _rate_calls % _RATE_SWEEP_EVERY == 0:
            for stale in [
                k for k, w in _rate_windows.items() if not w or now - w[-1] > 60
            ]:
                del _rate_windows[stale]
        window = _rate_windows.setdefault(key, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MIN:
            return True
        window.append(now)
        return False


def _apply_security_headers(response: Response) -> None:
    # A route may set its own CSP (only /docs does); keep it.
    if "content-security-policy" not in response.headers:
        response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"


def _body_limit(path: str) -> tuple[int, str]:
    """(max body bytes, error detail) for an unsafe /api request."""
    if path in ("/api/analyze", "/api/gate/deliveries"):
        return MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES, "upload_too_large"
    if path == "/api/generate":
        return MAX_GENERATE_BODY_BYTES, "request_too_large"
    return MAX_JSON_BODY_BYTES, "request_too_large"


class BodyLimitMiddleware:
    """Cap request bodies before anything parses them (CL-78).

    FastAPI reads a whole multipart form before a handler runs, so a
    size check in the handler comes too late. This ASGI layer answers
    413 from `Content-Length` without reading the body, and counts the
    bytes of a chunked or unlabelled body as they arrive, stopping the
    read at the limit.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in _UNSAFE_METHODS
            or not str(scope["path"]).startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        limit, detail = _body_limit(str(scope["path"]))
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                declared_too_large = int(declared) > limit
            except ValueError:
                declared_too_large = False
            if declared_too_large:
                response = JSONResponse(
                    {"detail": detail, "limit_bytes": limit}, status_code=413
                )
                _apply_security_headers(response)
                await response(scope, receive, send)
                return
        received = 0
        overflow = False
        started = False

        async def too_large() -> None:
            response = JSONResponse(
                {"detail": detail, "limit_bytes": limit}, status_code=413
            )
            _apply_security_headers(response)
            await response(scope, receive, send)

        async def limited_receive() -> Any:
            nonlocal received, overflow
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > limit:
                    # Stop reading here. Whatever the app makes of the
                    # error, the client gets the 413 below.
                    overflow = True
                    raise StarletteHTTPException(status_code=413, detail=detail)
            return message

        async def guarded_send(message: Any) -> None:
            nonlocal started
            if overflow:
                if message.get("type") == "http.response.start" and not started:
                    started = True
                    await too_large()
                return
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not overflow or started:
                raise
            await too_large()


app.add_middleware(BodyLimitMiddleware)


@app.get("/docs", include_in_schema=False)
def swagger_docs() -> Response:
    """Swagger UI with a CSP that lets it load (CL-78).

    The page needs Swagger's CDN bundle and one inline bootstrap
    script; the script is allowed by its SHA-256, not by
    `'unsafe-inline'`.
    """
    from fastapi.openapi.docs import get_swagger_ui_html

    page = get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} - Swagger UI",
    )
    html = bytes(page.body).decode()
    hashes = " ".join(
        "'sha256-"
        + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        + "'"
        for script in re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    )
    page.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src 'self' {SWAGGER_CDN} {hashes}; "
        f"style-src 'self' 'unsafe-inline' {SWAGGER_CDN}; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return page


# -- JSON bodies and demo roles (CL-78) ------------------------------------


def _is_json(request: Request) -> bool:
    content_type = request.headers.get("content-type") or ""
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


async def _json_object(request: Request) -> tuple[dict[str, Any], JSONResponse | None]:
    """Parse a JSON object body; only `application/json` is accepted.

    Browsers send `text/plain` and form bodies cross-site without a
    preflight, so refusing them closes the forged-request path.
    """
    if not _is_json(request):
        return {}, JSONResponse(
            {"detail": "content type must be application/json"}, status_code=415
        )
    try:
        body = json.loads((await request.body()) or b"{}")
    except json.JSONDecodeError:
        return {}, JSONResponse({"detail": "invalid_json"}, status_code=400)
    if not isinstance(body, dict):
        return {}, JSONResponse({"detail": "invalid_json"}, status_code=400)
    return body, None


def _demo_roles_enabled() -> bool:
    """Whether `X-Demo-Role` is honoured (CL-78, CL-67).

    The header is a demo convenience, not authentication: any client
    can send any role. Only demo mode in a demo build honours it
    (`app.auth.auth_mode`); OIDC mode and production images never do.
    """
    return auth.auth_mode() == "demo"


class DemoRoleDenied(PermissionError):
    """The request's role (demo or authenticated) lacks a permission."""

    def __init__(self, role: str, permission: str) -> None:
        super().__init__(f"role {role!r} lacks {permission}")
        self.role = role
        self.permission = permission


_policy_cache: dict[str, Any] | None = None


def _runtime_policy() -> dict[str, Any]:
    global _policy_cache
    if _policy_cache is None:
        from covertlens.runtime import load_runtime_policy

        _policy_cache = load_runtime_policy()
    return _policy_cache


def _require(request: Request, dataset_id: str, permission: str) -> tuple[Any, str]:
    """Principal for this request, if its role holds `permission`.

    Raises `ValueError` for an unknown role and `DemoRoleDenied` when
    the runtime policy does not grant the permission on this run.
    """
    from covertlens.runtime import can

    principal, role = _demo_principal(request, dataset_id)
    if not can(_runtime_policy(), principal, dataset_id, permission):
        raise DemoRoleDenied(role, permission)
    return principal, role


def _denied(exc: DemoRoleDenied) -> JSONResponse:
    mode = auth.auth_mode()
    return JSONResponse(
        {
            "detail": "permission denied for demo role"
            if mode != "oidc"
            else "permission denied",
            "role": exc.role,
            "needs": exc.permission,
            "auth_mode": mode,
            "demo_roles_enabled": mode == "demo",
        },
        status_code=403,
    )


def _original_readers(run_id: str, principal: Any) -> set[str]:
    """The request's actor, when the runtime policy lets it read originals."""
    from covertlens.runtime import can

    if can(_runtime_policy(), principal, run_id, "original.read"):
        return {principal.actor_id}
    return set()


@app.get("/api/health")
def health() -> JSONResponse:
    """Liveness plus the state a demo depends on (CL-78).

    `degraded` (HTTP 503) when the data directory is not writable or
    precompute failed; the reasons are in the body.
    """
    writable = _data_dir_writable()
    problems = []
    if not writable:
        problems.append("data_dir_not_writable")
    if _precompute_error is not None:
        problems.append("precompute_failed")
    gate_reload = _gate_instance.reload_report() if _gate_instance else None
    if gate_reload and gate_reload["skipped_versions"]:
        problems.append("gate_reload_skipped_versions")
    body = {
        "status": "degraded" if problems else "ok",
        "problems": problems,
        "version": covertlens.__version__,
        "git_sha": GIT_SHA,
        "precompute_started": _precompute_started,
        "precompute_error": _precompute_error,
        "cache_ready": _cache_ready(),
        "data_dir": _data_dir_status,
        "worker_pool_rebuilds": _pool_rebuilds,
        "gate_reload": gate_reload,
    }
    return JSONResponse(body, status_code=503 if problems else 200)


@app.get("/api/version")
def version() -> dict[str, Any]:
    manifest = load_manifest()
    return {
        "library_version": covertlens.__version__,
        "git_sha": GIT_SHA,
        "manifest_id": manifest["manifest_id"],
        "manifest_version": manifest["manifest_version"],
        "detectors": default_detector_versions(),
    }


@app.get("/api/fixtures")
def fixtures() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in entry.items() if not k.startswith("_")}
        for entry in _fixture_entries()
    ]


@app.get("/api/fixtures/{digest}.png")
def fixture_png(digest: str) -> Response:
    for entry in _fixture_entries():
        if entry["content_hash"].removeprefix("sha256:") == digest:
            return Response(content=entry["_data"], media_type="image/png")
    return JSONResponse({"detail": "fixture_not_found"}, status_code=404)


def _scene_context(
    declared_channels: Any, context: Any = None
) -> dict[str, Any] | None:
    """Validate a caller's geometric scene declaration (CL-45, CL-78).

    Accepts a list or a comma-separated string of channel names; an
    empty declaration is None. Unknown names raise ValueError.
    """
    from covertlens.manifest import GEOMETRIC_CHANNEL_NAMES

    if declared_channels is None:
        return None
    if isinstance(declared_channels, str):
        names = [n.strip() for n in declared_channels.split(",") if n.strip()]
    elif isinstance(declared_channels, list):
        names = [str(n).strip() for n in declared_channels if str(n).strip()]
    else:
        raise ValueError("declared_channels must be a list or comma-separated names")
    unknown = sorted(set(names) - set(GEOMETRIC_CHANNEL_NAMES))
    if unknown:
        raise ValueError(
            f"unknown geometric channel(s) {unknown}; "
            f"choose from {list(GEOMETRIC_CHANNEL_NAMES)}"
        )
    if not names:
        return None
    return {
        "declared_channels": sorted(set(names)),
        "context": str(context).strip() if context else "declared_by_caller",
    }


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    declared_channels: str | None = Form(None),
    scene_context: str | None = Form(None),
) -> JSONResponse:
    """Analyze one upload. The body limit is enforced before parsing.

    Optional `declared_channels` (comma-separated geometric channel
    names) and `scene_context` declare the task's legitimate channels.
    """
    try:
        context = _scene_context(declared_channels, scene_context)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"detail": "upload_too_large"}, status_code=413)
    try:
        max_pixels = int(os.environ.get("COVERTLENS_MAX_PIXELS", str(20_000_000)))
    except ValueError:
        max_pixels = 20_000_000
    try:
        payload = await _run_in_pool(
            analyze_bytes, data, max_pixels, context, timeout=ANALYZE_TIMEOUT_S
        )
    except TimeoutError:
        return JSONResponse(
            {
                "status": "timeout",
                "detail": f"analysis exceeded {ANALYZE_TIMEOUT_S}s deadline",
                "analysis": None,
                "geometric": None,
                "decision": None,
            }
        )
    except concurrent.futures.process.BrokenProcessPool:
        return JSONResponse({"detail": "analysis_worker_unavailable"}, status_code=503)
    return JSONResponse(payload)


_red_team_store: Any = None
_red_team_lock = threading.Lock()


def _record_red_team(result: dict[str, Any]) -> str:
    """Persist a generation's bytes + provenance (CL-51)."""
    global _red_team_store
    from covertlens.store import ArtifactStore

    data: bytes = result["data"]
    digest = str(result["content_hash"]).removeprefix("sha256:")
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (GENERATED_DIR / f"{digest}.{result['ext']}").write_bytes(data)
    with _red_team_lock:
        if _red_team_store is None:
            RED_TEAM_STORE_DIR.mkdir(parents=True, exist_ok=True)
            _red_team_store = ArtifactStore(RED_TEAM_STORE_DIR)
        version = _red_team_store.put_original(
            data, run_id="red_team", producer_id="red-team-ui"
        )
        RED_TEAM_INDEX.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "source": "red_team",
            "fixture_id": result["fixture_id"],
            "content_hash": result["content_hash"],
            "artifact_version_id": version.artifact_version_id,
            "created_at": datetime.now(UTC).isoformat(),
            "parameters": result["provenance"],
        }
        with RED_TEAM_INDEX.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return str(version.artifact_version_id)


@app.post("/api/generate")
async def generate(request: Request) -> JSONResponse:
    """Generate one red-team image from JSON parameters (CL-51)."""
    if not _data_dir_writable():
        return _data_unavailable()
    if not _is_json(request):
        return JSONResponse(
            {"detail": "content type must be application/json"}, status_code=415
        )
    body = await request.body()
    if len(body) > MAX_GENERATE_BODY_BYTES:
        return JSONResponse({"detail": "request_too_large"}, status_code=413)
    try:
        params = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return JSONResponse({"detail": "invalid_json"}, status_code=400)
    try:
        result = await _run_in_pool(generate_image, params, timeout=ANALYZE_TIMEOUT_S)
    except TimeoutError:
        return JSONResponse({"detail": "generation_timeout"}, status_code=504)
    except concurrent.futures.process.BrokenProcessPool:
        return JSONResponse(
            {"detail": "generation_worker_unavailable"}, status_code=503
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    version_id = _record_red_team(result)
    digest = str(result["content_hash"]).removeprefix("sha256:")
    return JSONResponse(
        {
            "fixture_id": result["fixture_id"],
            "content_hash": result["content_hash"],
            "media_type": result["media_type"],
            "image_url": f"/api/generated/{digest}.{result['ext']}",
            "source": "red_team",
            "artifact_version_id": version_id,
            "parameters": result["parameters"],
        }
    )


@app.get("/api/generated/{filename}")
def generated_image(filename: str) -> Response:
    """Serve one recorded red-team generation by content digest."""
    if not _GENERATED_NAME.match(filename):
        return JSONResponse({"detail": "generated_not_found"}, status_code=404)
    target = (GENERATED_DIR / filename).resolve()
    if not target.is_relative_to(GENERATED_DIR.resolve()) or not target.is_file():
        return JSONResponse({"detail": "generated_not_found"}, status_code=404)
    return FileResponse(target)


# The interactive demo keeps its state alongside the existing persistent gate.
_agent_demo_instance: AgentDemo | None = None


def _agent_demo() -> AgentDemo:
    global _agent_demo_instance
    gate = _gate()
    with _gate_lock:
        if _agent_demo_instance is None or _agent_demo_instance.gate is not gate:
            _agent_demo_instance = AgentDemo(DATA_DIR / "agent-demo", gate)
        return _agent_demo_instance


def _demo_permission(request: Request, run_id: str) -> JSONResponse | None:
    if not auth.demo_build():
        return JSONResponse(
            {"detail": "The agent demo is available in demo builds."}, 403
        )
    try:
        _require(request, run_id, "verdict.override")
        _require(request, run_id, "original.read")
    except DemoRoleDenied as exc:
        return _denied(exc)
    return None


@app.get("/api/agent-demo/config")
def agent_demo_config() -> dict[str, Any]:
    return demo_config()


@app.post("/api/agent-demo")
async def agent_demo_create(request: Request) -> JSONResponse:
    denied = _demo_permission(request, "agent-demo")
    if denied is not None:
        return denied
    body, error = await _json_object(request)
    if error is not None:
        return error
    try:
        result = await asyncio.to_thread(
            _agent_demo().create, body.get("scene", "house"), body.get("message", "")
        )
        return JSONResponse(result)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, 400)
    except Exception:
        return JSONResponse(
            {
                "detail": "The sender could not make the image. Check the API connection and try again."
            },
            502,
        )


@app.get("/api/agent-demo/{demo_id}")
def agent_demo_get(demo_id: str, request: Request) -> JSONResponse:
    denied = _demo_permission(request, "demo_" + demo_id)
    if denied is not None:
        return denied
    try:
        service = _agent_demo()
        return JSONResponse(service.public(service.load(demo_id)))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, 404)


@app.post("/api/agent-demo/{demo_id}/{operation}")
async def agent_demo_step(
    demo_id: str, operation: str, request: Request
) -> JSONResponse:
    denied = _demo_permission(request, "demo_" + demo_id)
    if denied is not None:
        return denied
    service = _agent_demo()
    try:
        if operation == "image":
            result = service.image(demo_id)
        elif operation == "show":
            result = {"message": service.load(demo_id)["message"]}
        elif operation == "analyze":
            result = await asyncio.to_thread(service.analyze, demo_id)
        elif operation == "retry":
            body, error = await _json_object(request)
            if error is not None:
                return error
            attempt = body.get("attempt")
            if isinstance(attempt, bool) or not isinstance(attempt, int):
                return JSONResponse(
                    {
                        "detail": "Reload the saved demo before trying the receiver again."
                    },
                    400,
                )
            result = await asyncio.to_thread(service.retry_receiver, demo_id, attempt)
        elif operation in ("block", "send"):
            result = await asyncio.to_thread(service.decide, demo_id, operation)
        else:
            return JSONResponse({"detail": "Unknown demo action."}, 404)
        return JSONResponse(result)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, 409)
    except Exception:
        return JSONResponse(
            {
                "detail": "This step could not finish. Reload the demo to see its last saved state."
            },
            502,
        )


# -- Live Gate (CL-53) -------------------------------------------------

_gate_instance: Any = None
_gate_lock = threading.Lock()


class DataDirUnavailable(RuntimeError):
    """The data directory cannot hold gate or review state (CL-78)."""


@app.exception_handler(DataDirUnavailable)
async def _data_dir_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    response = _data_unavailable()
    _apply_security_headers(response)
    return response


def _gate() -> Any:
    """Persistent gate singleton over the file-backed store."""
    global _gate_instance
    if _gate_instance is None and not _data_dir_writable():
        raise DataDirUnavailable(str(DATA_DIR))
    with _gate_lock:
        if _gate_instance is None:
            from covertlens.gate import InterceptionGate
            from covertlens.store import ArtifactStore

            GATE_STORE_DIR.mkdir(parents=True, exist_ok=True)
            _gate_instance = InterceptionGate(ArtifactStore(GATE_STORE_DIR))
        return _gate_instance


def _reset_gate_for_tests() -> None:
    global _gate_instance, _review_instance
    with _gate_lock:
        _gate_instance = None
        _review_instance = None
    with _analysis_lock:
        _analysis_cache.clear()


# Analysis results by (artifact version, scene context) (CL-78). The
# gate-analyze, review-detail and trace endpoints each re-analysed
# stored bytes on every call; versions are immutable, so one analysis
# per version and context serves them all.
ANALYSIS_CACHE_SIZE = 256
_analysis_cache: OrderedDict[tuple[str, str], tuple[Any, Any]] = OrderedDict()
_analysis_lock = threading.Lock()


def _context_key(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    return json.dumps(
        {k: context.get(k) for k in ("declared_channels", "context")}, sort_keys=True
    )


def _analysis_for(gate: Any, record: Any, actor_id: str) -> tuple[Any, Any]:
    """(AnalysisResult, geometric report or None) for a delivery, cached.

    Uses the run's declared scene context (CL-45/CL-78). Callers must
    not mutate the returned report; use `public_geometric` for output.
    """
    from covertlens.metadata import analyze_all_with_geometric

    context = gate.scene_context(record.run_id)
    key = (record.artifact_version_id, _context_key(context))
    with _analysis_lock:
        hit = _analysis_cache.get(key)
        if hit is not None:
            _analysis_cache.move_to_end(key)
            return hit
    data = gate.store.get_original(
        record.artifact_version_id, actor_id=actor_id, purpose="analysis"
    )
    value = analyze_all_with_geometric(
        data,
        artifact_version_id=record.artifact_version_id,
        declared_context=context,
    )
    with _analysis_lock:
        _analysis_cache[key] = value
        while len(_analysis_cache) > ANALYSIS_CACHE_SIZE:
            _analysis_cache.popitem(last=False)
    return value


def _delivery_payload(record: Any) -> dict[str, Any]:
    verdict = record.verdict.value if record.verdict is not None else None
    if record.state == "permitted":
        recipient_message = "delivered"
    elif record.state == "withheld":
        if record.infrastructure_error:
            reason = f"infrastructure error: {record.infrastructure_error}"
        elif verdict:
            reason = f"{verdict} verdict"
        else:
            reason = "withheld by the gate"
        recipient_message = f"withheld — {reason}"
    else:
        recipient_message = "pending — awaiting analysis and verdict"
    return {
        "delivery_id": record.delivery_id,
        "run_id": record.run_id,
        "episode_id": record.episode_id,
        "artifact_id": record.artifact_id,
        "artifact_version_id": record.artifact_version_id,
        "content_hash": record.content_hash,
        "sender_id": record.sender_id,
        "recipient_id": record.recipient_id,
        "attempt": record.attempt,
        "state": record.state,
        "verdict": verdict,
        "verdict_id": record.verdict_id,
        "infrastructure_error": record.infrastructure_error,
        "recipient_message": recipient_message,
    }


def _gate_error(exc: Exception) -> JSONResponse:
    from covertlens.gate import (
        PendingDeliveryError,
        ReviewerAccessError,
        UnknownDeliveryError,
        WithheldError,
    )

    if isinstance(exc, UnknownDeliveryError):
        return JSONResponse({"detail": "delivery_not_found"}, status_code=404)
    if isinstance(exc, PendingDeliveryError):
        return JSONResponse(
            {"detail": "withheld — pending: awaiting a verdict; no bytes served"},
            status_code=409,
        )
    if isinstance(exc, WithheldError):
        return JSONResponse(
            {"detail": "withheld — delivery was withheld; no bytes served"},
            status_code=403,
        )
    if isinstance(exc, ReviewerAccessError):
        return JSONResponse(
            {
                "detail": "reviewer access denied: the original needs a role"
                " with original.read (researcher or reviewer)",
                "auth_mode": auth.auth_mode(),
                "demo_roles_enabled": _demo_roles_enabled(),
            },
            status_code=403,
        )
    if isinstance(exc, ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)
    raise exc


@app.get("/api/gate/runs")
def gate_runs(request: Request) -> dict[str, Any]:
    gate = _gate()
    runs = gate.runs()
    if auth.auth_mode() == "oidc":
        # Multi-tenant: only runs inside the caller's dataset scopes.
        identity = _request_identity(request)
        runs = [r for r in runs if identity is not None and identity.covers(r)]
    return {"runs": runs}


@app.post("/api/gate/runs")
async def gate_create_run(request: Request) -> JSONResponse:
    """Create a run id; optionally declare its scene context first.

    `declared_channels` (list of geometric channel names) and `context`
    are the run's declaration (CL-45). It must come before the run's
    first delivery (409 afterwards).
    """
    body, error = await _json_object(request)
    if error is not None:
        return error
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        import uuid

        run_id = f"run_{uuid.uuid4().hex[:16]}"
    denied = _tenant_guard(request, run_id)
    if denied is not None:
        return denied
    gate = _gate()
    try:
        context = _scene_context(body.get("declared_channels"), body.get("context"))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    if context is not None:
        try:
            gate.declare_scene_context(
                run_id, context["declared_channels"], context["context"]
            )
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
    return JSONResponse(
        {
            "run_id": run_id,
            "known_runs": gate_runs(request)["runs"],
            "scene_context": gate.scene_context(run_id),
        }
    )


@app.post("/api/gate/deliveries")
async def gate_create_delivery(
    request: Request,
    file: UploadFile = File(...),
    run_id: str = Form(...),
    sender_id: str = Form("agent-a"),
    recipient_id: str = Form("agent-b"),
    route_id: str = Form("R-01"),
    episode_id: str | None = Form(None),
) -> JSONResponse:
    from covertlens.gate import InterceptionContext

    denied = _tenant_guard(request, run_id)
    if denied is not None:
        return denied
    gate = _gate()
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"detail": "upload_too_large"}, status_code=413)
    ctx = InterceptionContext(
        run_id=run_id.strip(),
        sender_id=sender_id.strip() or "agent-a",
        episode_id=episode_id.strip() if episode_id and episode_id.strip() else None,
    )
    if not ctx.run_id:
        return JSONResponse({"detail": "run_id is required"}, status_code=400)
    try:
        handle = gate.intercept_bytes(route_id.strip(), data, ctx)
        record = gate.attempt_delivery(
            handle, recipient_id=recipient_id.strip() or "agent-b"
        )
    except Exception as exc:  # noqa: BLE001 - mapped to explicit API errors
        return _gate_error(exc)
    return JSONResponse(_delivery_payload(record))


@app.get("/api/gate/runs/{run_id}")
def gate_run_detail(run_id: str, request: Request) -> JSONResponse:
    denied = _tenant_guard(request, run_id)
    if denied is not None:
        return denied
    gate = _gate()
    deliveries = [_delivery_payload(r) for r in gate.deliveries(run_id)]
    events = [e.to_dict() for e in gate.events(run_id)]
    return JSONResponse(
        {
            "run_id": run_id,
            "scene_context": gate.scene_context(run_id),
            "deliveries": deliveries,
            "events": events,
            "access_report": gate.access_attempt_report(),
            "access_attempts": gate.access_attempts(),
            "coverage": gate.coverage_report(),
        }
    )


@app.post("/api/gate/deliveries/{delivery_id}/analyze")
def gate_analyze_delivery(delivery_id: str, request: Request) -> JSONResponse:
    """Analyse a pending delivery's bytes; stays pending (CL-53)."""
    gate = _gate()
    try:
        record = gate.get_delivery(delivery_id)
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    denied = _tenant_guard(request, record.run_id)
    if denied is not None:
        return denied
    identity = _request_identity(request)
    if record.state != "pending":
        return JSONResponse(
            {"detail": f"delivery already decided ({record.state})"},
            status_code=409,
        )
    try:
        result, _geometric = _analysis_for(
            gate,
            record,
            identity.actor_id if identity is not None else "gate-analyzer",
        )
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    from covertlens.verdicts import decide_verdict

    # The shipped freeze decides, not the log-only library default.
    decision = decide_verdict(result.findings, frozen_config())
    return JSONResponse(
        {
            "delivery": _delivery_payload(record),
            "scene_context": gate.scene_context(record.run_id),
            "analysis": result.to_dict(),
            "decision": decision.to_dict(),
            "suggested_verdict": decision.to_dict()["verdict"],
        }
    )


@app.post("/api/gate/deliveries/{delivery_id}/verdict")
async def gate_record_verdict(delivery_id: str, request: Request) -> JSONResponse:
    """Record a gate verdict; needs `verdict.override` (CL-78)."""
    body, error = await _json_object(request)
    if error is not None:
        return error
    gate = _gate()
    try:
        record = gate.get_delivery(delivery_id)
        _require(request, record.run_id, "verdict.override")
    except DemoRoleDenied as exc:
        return _denied(exc)
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    verdict_value = str(body.get("verdict") or "").strip()
    from covertlens.events import Verdict

    try:
        verdict = Verdict(verdict_value)
    except ValueError:
        return JSONResponse(
            {"detail": "verdict must be log, flag, quarantine or fail_run"},
            status_code=400,
        )
    try:
        record = gate.record_verdict(delivery_id, verdict)
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    return JSONResponse(_delivery_payload(record))


@app.get("/api/gate/deliveries/{delivery_id}/recipient-image")
def gate_recipient_image(delivery_id: str, request: Request) -> Response:
    """Recipient view: bytes only after a permitting verdict."""
    gate = _gate()
    try:
        record = gate.get_delivery(delivery_id)
        denied = _tenant_guard(request, record.run_id)
        if denied is not None:
            return denied
        data = gate.recipient_access(delivery_id, via_route="R-04")
    except Exception as exc:  # noqa: BLE001
        # Withheld/pending responses carry the gate's reason and no bytes.
        try:
            record = gate.get_delivery(delivery_id)
            payload = _delivery_payload(record)
            detail = payload["recipient_message"]
        except Exception:  # noqa: BLE001
            detail = "withheld — delivery not available to the recipient"
            return JSONResponse({"detail": detail}, status_code=404)
        from covertlens.gate import PendingDeliveryError, WithheldError

        if isinstance(exc, PendingDeliveryError):
            return JSONResponse({"detail": detail}, status_code=409)
        if isinstance(exc, WithheldError):
            return JSONResponse({"detail": detail}, status_code=403)
        return _gate_error(exc)
    media = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(content=data, media_type=media)


@app.get("/api/gate/deliveries/{delivery_id}/reviewer-image")
def gate_reviewer_image(delivery_id: str, request: Request) -> Response:
    """Reviewer view (R-08): audited read, `original.read` only (CL-78).

    The caller cannot name the actor. The demo role (viewer when the
    header is absent or demo roles are off) maps to its CL-11
    principal, and only principals the runtime policy allows
    `original.read` on this run count as reviewers. Denied attempts
    are recorded as `reviewer_denied`.
    """
    gate = _gate()
    try:
        record = gate.get_delivery(delivery_id)
        principal, _role = _demo_principal(request, record.run_id)
        data = gate.reviewer_access(
            delivery_id,
            actor_id=principal.actor_id,
            reviewer_ids=_original_readers(record.run_id, principal),
        )
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    media = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(
        content=data, media_type=media, headers={"Cache-Control": "no-store"}
    )


@app.get("/api/gate/runs/{run_id}/events/stream")
async def gate_event_stream(run_id: str, request: Request) -> Response:
    """SSE timeline for one run (CL-53): replay, then poll for new seqs."""
    denied = _tenant_guard(request, run_id)
    if denied is not None:
        return denied
    gate = _gate()

    async def generate() -> Any:
        sent = -1
        # Replay existing events, then poll briefly for new ones.
        # The stream ends after ~5s idle; browsers reconnect and
        # replay, which keeps the timeline live without holding a
        # request open indefinitely.
        idle_polls = 0
        while idle_polls < 50:
            if await request.is_disconnected():
                break
            events = gate.events(run_id)
            fresh = [e for e in events if e.seq > sent]
            for event in fresh:
                sent = event.seq
                yield f"data: {json.dumps(event.to_dict())}\n\n"
            if fresh:
                idle_polls = 0
                continue
            idle_polls += 1
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- Reviewer (CL-59) ---------------------------------------------------

_review_instance: Any = None


def _review_workspace() -> Any:
    """Review workspace over the persistent gate store (CL-59)."""
    global _review_instance
    if _review_instance is not None:
        return _review_instance
    from covertlens.review import ReviewWorkspace

    gate = _gate()
    with _gate_lock:
        if _review_instance is None:
            GATE_STORE_DIR.mkdir(parents=True, exist_ok=True)
            _review_instance = ReviewWorkspace(
                gate.store, db_path=GATE_STORE_DIR / "review.sqlite3"
            )
        return _review_instance


def _reset_review_for_tests() -> None:
    global _review_instance
    with _gate_lock:
        _review_instance = None


def _demo_principal(request: Request, dataset_id: str) -> Any:
    """CL-11 principal for the request on one dataset (CL-67).

    OIDC mode: the authenticated identity (session cookie or bearer
    token) mapped through `config/identity-mapping.json`; anonymous
    requests are viewers with no dataset. Demo mode: the `X-Demo-Role`
    header. Off: a viewer. Returns (principal, role label).
    """
    from covertlens.identity import principal_for
    from covertlens.review import demo_principal

    mode = auth.auth_mode()
    if mode == "oidc":
        identity = _request_identity(request)
        principal = principal_for(identity, dataset_id)
        return principal, ",".join(sorted(principal.roles)) or "viewer"
    role = "viewer"
    if mode == "demo":
        role = (request.headers.get("x-demo-role") or "viewer").strip().lower()
    return demo_principal(role, dataset_id), role


def _tenant_guard(request: Request, run_id: str) -> JSONResponse | None:
    """OIDC mode: the run must be inside the caller's dataset scopes.

    Multi-tenant isolation for run-level reads and writes that hold no
    runtime-policy permission of their own (gate runs, deliveries,
    review queue). Demo and off modes keep the Phase 2 behaviour.
    """
    if auth.auth_mode() != "oidc":
        return None
    identity = _request_identity(request)
    if identity is None:
        return JSONResponse(
            {"detail": "authentication required", "auth_mode": "oidc"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not identity.covers(run_id):
        return JSONResponse(
            {"detail": "run is outside your dataset scopes", "auth_mode": "oidc"},
            status_code=403,
        )
    return None


# -- Authentication (CL-67) --------------------------------------------

AUTH_DIR = DATA_DIR / "auth"
_auth_lock = threading.Lock()
_oidc_client: Any = None
_session_store: Any = None
_identity_mapping: Any = None


def _oidc() -> Any:
    global _oidc_client
    with _auth_lock:
        if _oidc_client is None:
            _oidc_client = auth.OidcClient(auth.OidcSettings.from_env())
        return _oidc_client


def _sessions() -> Any:
    global _session_store
    with _auth_lock:
        if _session_store is None:
            _session_store = auth.SessionStore(AUTH_DIR / "sessions.sqlite3")
        return _session_store


def _mapping() -> Any:
    global _identity_mapping
    with _auth_lock:
        if _identity_mapping is None:
            from covertlens.identity import load_identity_mapping

            _identity_mapping = load_identity_mapping(
                os.environ.get("COVERTLENS_IDENTITY_MAPPING") or None
            )
        return _identity_mapping


def _reset_auth_for_tests(http: Any = None) -> None:
    """Drop cached auth state; `http` injects a fake identity provider."""
    global _oidc_client, _session_store, _identity_mapping
    with _auth_lock:
        _oidc_client = (
            auth.OidcClient(auth.OidcSettings.from_env(), http=http)
            if http is not None
            else None
        )
        _session_store = None
        _identity_mapping = None


def _request_identity(request: Request) -> Any:
    """Authenticated identity (OIDC mode) or None for anonymous requests.

    A presented but invalid credential raises `AuthenticationFailed`
    (401): a bad token never degrades silently to a viewer.
    """
    from covertlens.identity import Identity, identity_from_claims

    if auth.auth_mode() != "oidc":
        return None
    cached = getattr(request.state, "covertlens_identity", "unset")
    if cached != "unset":
        return cached
    identity = None
    token = auth.bearer_token(request.headers.get("authorization"))
    if token is not None:
        client = _oidc()
        claims = client.validate(
            token, audience=client.settings.audience or client.settings.client_id
        )
        identity = identity_from_claims(claims, _mapping(), auth_method="bearer")
    else:
        session = request.cookies.get(auth.SESSION_COOKIE)
        if session:
            stored = _sessions().get_session(session)
            if stored is not None:
                identity = Identity.from_dict(stored)
    request.state.covertlens_identity = identity
    return identity


@app.exception_handler(auth.AuthenticationFailed)
async def _authentication_failed(
    request: Request, exc: auth.AuthenticationFailed
) -> JSONResponse:
    response = JSONResponse(
        {"detail": "authentication failed", "reason": exc.reason},
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )
    _apply_security_headers(response)
    return response


def _redirect_uri(request: Request) -> str:
    configured = _oidc().settings.redirect_uri
    if configured:
        return str(configured)
    return str(request.url_for("auth_callback"))


def _cookie_secure() -> bool:
    return bool(_oidc().settings.cookie_secure)


@app.get("/api/auth/me")
def auth_me(request: Request) -> JSONResponse:
    """Who the service thinks you are, and how to sign in (CL-67)."""
    mode = auth.auth_mode()
    body: dict[str, Any] = {
        "auth_mode": mode,
        "demo_build": auth.demo_build(),
        "authenticated": False,
    }
    if mode == "oidc":
        identity = _request_identity(request)
        body["login_url"] = "/api/auth/login"
        if identity is not None:
            body.update(
                {
                    "authenticated": True,
                    "actor_id": identity.actor_id,
                    "display_name": identity.display_name,
                    "roles": sorted(identity.roles),
                    "dataset_patterns": list(identity.dataset_patterns),
                    "auth_method": identity.auth_method,
                }
            )
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/api/auth/login")
def auth_login(request: Request, next: str | None = None) -> Response:
    """Start the OIDC code flow (PKCE S256, state bound to this browser)."""
    if auth.auth_mode() != "oidc":
        return JSONResponse({"detail": "oidc sign-in is not enabled"}, status_code=404)
    login = _sessions().begin_login(auth.safe_next_path(next))
    target = _oidc().authorization_url(
        state=login["state"],
        nonce=login["nonce"],
        challenge=auth.pkce_challenge(login["verifier"]),
        redirect_uri=_redirect_uri(request),
    )
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        auth.LOGIN_COOKIE,
        login["binding"],
        max_age=auth.LOGIN_TTL_S,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/api/auth",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/auth/callback", name="auth_callback")
def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """Finish the code flow: one-time state, PKCE exchange, ID token, session."""
    from covertlens.identity import identity_from_claims

    if auth.auth_mode() != "oidc":
        return JSONResponse({"detail": "oidc sign-in is not enabled"}, status_code=404)
    if error:
        return JSONResponse(
            {"detail": "sign-in was not completed", "error": error[:80]},
            status_code=400,
        )
    if not code or not state:
        return JSONResponse({"detail": "missing code or state"}, status_code=400)
    try:
        pending = _sessions().finish_login(
            state, request.cookies.get(auth.LOGIN_COOKIE) or ""
        )
        client = _oidc()
        id_token = client.exchange(
            code=code, verifier=pending["verifier"], redirect_uri=_redirect_uri(request)
        )
        claims = client.validate(id_token, nonce=pending["nonce"])
        identity = identity_from_claims(claims, _mapping())
    except (auth.AuthenticationFailed, ValueError) as exc:
        return JSONResponse(
            {"detail": "sign-in failed", "reason": str(exc)[:200]}, status_code=400
        )
    token = _sessions().create_session(identity, client.settings.session_ttl_s)
    response = RedirectResponse(pending["next_path"], status_code=302)
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=client.settings.session_ttl_s,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(auth.LOGIN_COOKIE, path="/api/auth")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    """End the server-side session and clear the cookie."""
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token and auth.auth_mode() == "oidc":
        _sessions().delete_session(token)
    response = JSONResponse({"signed_out": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


def _review_error(exc: Exception) -> JSONResponse:
    from covertlens.gate import UnknownDeliveryError

    if isinstance(exc, UnknownDeliveryError) or isinstance(exc, KeyError):
        return JSONResponse({"detail": "delivery_not_found"}, status_code=404)
    if isinstance(exc, PermissionError):
        return JSONResponse(
            {"detail": "permission denied for demo role"}, status_code=403
        )
    if isinstance(exc, ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)
    raise exc


def _review_delivery_row(gate: Any, workspace: Any, record: Any) -> dict[str, Any]:
    row = _delivery_payload(record)
    decode_id = None
    if record.state == "withheld":
        decode_id = workspace.ensure_candidate_decode(
            record.run_id, record, declared_context=gate.scene_context(record.run_id)
        )
    row["disposition"] = workspace.disposition(record.run_id, record.delivery_id)
    row["has_candidate_decode"] = decode_id is not None
    row["decode_id"] = decode_id
    return row


@app.get("/api/review/roles")
def review_roles() -> dict[str, Any]:
    from covertlens.review import role_capabilities

    return {
        "roles": role_capabilities(),
        "header": "X-Demo-Role",
        "default": "viewer",
        "enabled": _demo_roles_enabled(),
        "auth_mode": auth.auth_mode(),
        "demo_build": auth.demo_build(),
    }


@app.get("/api/review/runs/{run_id}/queue")
def review_queue(run_id: str, request: Request) -> JSONResponse:
    try:
        _principal, _role = _demo_principal(request, run_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    denied = _tenant_guard(request, run_id)
    if denied is not None:
        return denied
    gate = _gate()
    workspace = _review_workspace()
    rows = [
        _review_delivery_row(gate, workspace, record)
        for record in gate.deliveries(run_id)
    ]
    return JSONResponse(
        {
            "run_id": run_id,
            "deliveries": rows,
            "quarantined": [r for r in rows if r["state"] == "withheld"],
        }
    )


@app.get("/api/review/deliveries/{delivery_id}")
def review_delivery_detail(delivery_id: str, request: Request) -> JSONResponse:
    gate = _gate()
    workspace = _review_workspace()
    try:
        record = gate.get_delivery(delivery_id)
        principal, _role = _demo_principal(request, record.run_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    denied = _tenant_guard(request, record.run_id)
    if denied is not None:
        return denied
    # Store access log names the requester (CL-67), purpose "analysis".
    analysis, geometric = _analysis_for(
        gate,
        record,
        principal.actor_id if auth.auth_mode() == "oidc" else "review-detail",
    )
    row = _review_delivery_row(gate, workspace, record)
    return JSONResponse(
        {
            **row,
            "scene_context": gate.scene_context(record.run_id),
            "analysis": analysis.to_dict(),
            # Reviewer-only fields stripped (CL-46/CL-59).
            "geometric": public_geometric(geometric) if geometric else None,
        }
    )


@app.get("/api/review/deliveries/{delivery_id}/candidate-decode")
def review_candidate_decode(delivery_id: str, request: Request) -> JSONResponse:
    gate = _gate()
    workspace = _review_workspace()
    try:
        record = gate.get_delivery(delivery_id)
        principal, _role = _demo_principal(request, record.run_id)
        decode_id = workspace.ensure_candidate_decode(
            record.run_id, record, declared_context=gate.scene_context(record.run_id)
        )
        if decode_id is None:
            return JSONResponse(
                {"detail": "no candidate decode for this delivery"}, status_code=404
            )
        decode = workspace.read_candidate_decode(principal, record.run_id, decode_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    return JSONResponse(decode)


@app.get("/api/review/deliveries/{delivery_id}/original")
def review_original(delivery_id: str, request: Request) -> Response:
    gate = _gate()
    workspace = _review_workspace()
    try:
        record = gate.get_delivery(delivery_id)
        principal, _role = _demo_principal(request, record.run_id)
        data = workspace.read_original(
            principal, record.run_id, record.artifact_version_id
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    media = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(
        content=data, media_type=media, headers={"Cache-Control": "no-store"}
    )


@app.post("/api/review/deliveries/{delivery_id}/disposition")
async def review_disposition(delivery_id: str, request: Request) -> JSONResponse:
    body, error = await _json_object(request)
    if error is not None:
        return error
    gate = _gate()
    workspace = _review_workspace()
    try:
        record = gate.get_delivery(delivery_id)
        principal, _role = _demo_principal(request, record.run_id)
        review = workspace.apply_disposition(
            principal,
            record.run_id,
            delivery_id,
            disposition=str(body.get("disposition") or ""),
            note=str(body.get("note") or ""),
            demonstrated_basis=(
                str(body["demonstrated_basis"])
                if body.get("demonstrated_basis")
                else None
            ),
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    return JSONResponse({"delivery_id": delivery_id, **review})


# -- AI second opinion (CL-74..CL-77, advisory only) -------------------
# The API key is read server-side from the environment only and
# never appears in any response. Opinions never change a verdict.

_second_opinion_tracker: Any = None


def _opinion_tracker() -> Any:
    global _second_opinion_tracker
    if _second_opinion_tracker is None:
        from covertlens.second_opinion import UsageTracker

        _second_opinion_tracker = UsageTracker()
    return _second_opinion_tracker


def _opinion_provider_and_config() -> tuple[Any, Any]:
    """Server-side provider; tests may set a fake via the env."""
    from covertlens.second_opinion import (
        FakeProvider,
        SecondOpinionConfig,
        provider_from_config,
    )

    config = SecondOpinionConfig.from_env()
    if config.provider == "fake":
        text = os.environ.get("COVERTLENS_SECOND_OPINION_FAKE_RESPONSE")
        provider = FakeProvider(response_text=text, model=config.model or "fake-model")
        return provider, config
    return provider_from_config(config), config


@app.get("/api/review/second-opinion/config")
def second_opinion_config() -> JSONResponse:
    """Public provider status (never the key)."""
    from covertlens.second_opinion import SecondOpinionConfig

    return JSONResponse(SecondOpinionConfig.from_env().public_dict())


@app.post("/api/review/deliveries/{delivery_id}/second-opinion")
@app.post("/api/review/{delivery_id}/second-opinion")
async def second_opinion_request(delivery_id: str, request: Request) -> JSONResponse:
    body, error = await _json_object(request)
    if error is not None:
        return error
    gate = _gate()
    workspace = _review_workspace()
    try:
        record_row = gate.get_delivery(delivery_id)
        principal, _role = _demo_principal(request, record_row.run_id)
        provider, config = _opinion_provider_and_config()
        record = workspace.request_second_opinion(
            principal,
            gate,
            record_row.run_id,
            delivery_id,
            provider=provider,
            config=config,
            tracker=_opinion_tracker(),
            include_image=bool(body.get("include_image")),
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    return JSONResponse(record)


@app.get("/api/review/deliveries/{delivery_id}/second-opinion")
@app.get("/api/review/{delivery_id}/second-opinion")
def second_opinion_list(delivery_id: str, request: Request) -> JSONResponse:
    gate = _gate()
    workspace = _review_workspace()
    try:
        record_row = gate.get_delivery(delivery_id)
        _principal, _role = _demo_principal(request, record_row.run_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    return JSONResponse(
        {
            "delivery_id": delivery_id,
            "run_id": record_row.run_id,
            "opinions": workspace.second_opinions(record_row.run_id, delivery_id),
            "config": SecondOpinionConfig_status(),
        }
    )


def SecondOpinionConfig_status() -> dict[str, Any]:
    from covertlens.second_opinion import SecondOpinionConfig

    return SecondOpinionConfig.from_env().public_dict()


@app.get("/api/review/runs/{run_id}/export")
def review_export(run_id: str, request: Request) -> Response:
    gate = _gate()
    workspace = _review_workspace()
    try:
        principal, _role = _demo_principal(request, run_id)
        package = workspace.export_package(principal, gate, run_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    return Response(
        content=json.dumps(package, indent=2, sort_keys=True),
        media_type="application/json",
        headers={"Content-Disposition": _attachment(f"review-{run_id}.json")},
    )


def _attachment(filename: str) -> str:
    """`Content-Disposition` with a header-safe filename (CL-78).

    The plain `filename` keeps only `[A-Za-z0-9._-]`; the exact name
    goes in the RFC 5987 `filename*` form, percent-encoded, so quotes,
    CR/LF or semicolons in a run id cannot break the header.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120] or "download"
    return (
        f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quote(filename, safe='')}"
    )


@app.get("/api/review/audit")
def review_audit(request: Request, run_id: str | None = None) -> JSONResponse:
    """Audit chain entries; needs `trace.read` (CL-78)."""
    try:
        _require(request, run_id or "*", "trace.read")
    except DemoRoleDenied as exc:
        return _denied(exc)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse(_review_workspace().audit_payload(run_id))


# -- Trace explorer (CL-60) ----------------------------------------------


@app.get("/api/trace/runs/{run_id}")
def trace_run(run_id: str, request: Request) -> JSONResponse:
    """Trace explorer view for one run (CL-60, REV-01/02/03).

    Needs `trace.read` on the run (CL-78).
    """
    from covertlens.trace_explorer import build_trace_explorer

    try:
        principal, _role = _require(request, run_id, "trace.read")
    except DemoRoleDenied as exc:
        return _denied(exc)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    gate = _gate()
    results = [
        _analysis_for(
            gate,
            record,
            principal.actor_id if auth.auth_mode() == "oidc" else "trace-explorer",
        )[0]
        for record in gate.deliveries(run_id)
    ]
    view = build_trace_explorer(gate.events(run_id), results)
    if view["run_id"] is None:
        view["run_id"] = run_id
    return JSONResponse(view)


# -- Leaderboard (CL-70) ---------------------------------------------------

LEADERBOARD_DB = DATA_DIR / "leaderboard" / "leaderboard.sqlite3"
LEADERBOARD_DATASET = "leaderboard"
_leaderboard_instance: Any = None
_leaderboard_lock = threading.Lock()
_leaderboard_windows: dict[str, deque] = {}
_HIDDEN_PROVENANCE = ("grid_full", "generator", "encoder")


def _leaderboard() -> Any:
    global _leaderboard_instance
    with _leaderboard_lock:
        if _leaderboard_instance is None:
            from covertlens.leaderboard import LeaderboardStore

            _leaderboard_instance = LeaderboardStore(LEADERBOARD_DB)
        return _leaderboard_instance


def _reset_leaderboard_for_tests() -> None:
    global _leaderboard_instance
    with _leaderboard_lock:
        _leaderboard_instance = None
        _leaderboard_windows.clear()


def _leaderboard_moderated() -> bool:
    """New entries wait for an operator; default on for OIDC deployments."""
    default = "on" if auth.auth_mode() == "oidc" else "off"
    value = os.environ.get("COVERTLENS_LEADERBOARD_MODERATION", default)
    return value.strip().lower() in ("on", "1", "true", "yes")


def _leaderboard_rate_ok(key: str) -> bool:
    """Per submitter sliding hour window; idle windows are evicted."""
    limit = int(os.environ.get("COVERTLENS_LEADERBOARD_RATE_PER_HOUR", "20"))
    now = time.time()
    with _leaderboard_lock:
        for stale in [
            k for k, w in _leaderboard_windows.items() if not w or now - w[-1] > 3600
        ]:
            _leaderboard_windows.pop(stale, None)
        window = _leaderboard_windows.setdefault(key, deque())
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


def _red_team_record(artifact_version_id: str) -> dict[str, Any] | None:
    if not RED_TEAM_INDEX.is_file():
        return None
    found = None
    with RED_TEAM_INDEX.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("artifact_version_id") == artifact_version_id:
                found = record
    return found


def _can_moderate(request: Request) -> bool:
    try:
        _require(request, LEADERBOARD_DATASET, "leaderboard.moderate")
    except (DemoRoleDenied, ValueError):
        return False
    return True


def _board_payload(pin_hash: str, request: Request) -> dict[str, Any]:
    from covertlens.leaderboard import standings

    entries = _leaderboard().entries(pin_hash)
    return {
        "pin_hash": pin_hash,
        "standings": standings(entries),
        "entries": len(entries),
        "pending": sum(1 for e in entries if e["status"] == "pending"),
    }


@app.get("/api/leaderboard")
def leaderboard(request: Request) -> JSONResponse:
    """Current board (this release's pin hash) plus every archived board."""
    from covertlens.leaderboard import OPERATING_POINTS, configuration_pin

    pin = configuration_pin()
    return JSONResponse(
        {
            "current": pin,
            "board": _board_payload(pin["pin_hash"], request),
            "boards": [
                {**b, "current": b["pin_hash"] == pin["pin_hash"]}
                for b in _leaderboard().boards()
            ],
            "operating_points": list(OPERATING_POINTS),
            "moderation": _leaderboard_moderated(),
            "can_moderate": _can_moderate(request),
            "submissions_need_sign_in": auth.auth_mode() == "oidc",
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/leaderboard/boards/{pin_hash}")
def leaderboard_board(pin_hash: str, request: Request) -> JSONResponse:
    """An archived (or current) board by its pin hash; old entries stay."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", pin_hash):
        return JSONResponse({"detail": "not a pin hash"}, status_code=400)
    board = _board_payload(pin_hash, request)
    if not board["entries"]:
        return JSONResponse({"detail": "no board for this pin hash"}, status_code=404)
    return JSONResponse(board)


@app.get("/api/leaderboard/entries/{entry_id}")
def leaderboard_entry(entry_id: str, request: Request) -> JSONResponse:
    from covertlens.leaderboard import public_entry

    try:
        entry = _leaderboard().get(entry_id)
    except KeyError:
        return JSONResponse({"detail": "entry_not_found"}, status_code=404)
    if _can_moderate(request):
        return JSONResponse(entry)
    if entry["status"] != "visible":
        return JSONResponse({"detail": "entry_not_found"}, status_code=404)
    return JSONResponse(public_entry(entry))


@app.get("/api/leaderboard/pending")
def leaderboard_pending(request: Request) -> JSONResponse:
    """Entries awaiting moderation; operators only."""
    from covertlens.leaderboard import configuration_pin

    try:
        _require(request, LEADERBOARD_DATASET, "leaderboard.moderate")
    except DemoRoleDenied as exc:
        return _denied(exc)
    pin = configuration_pin()["pin_hash"]
    return JSONResponse({"pending": _leaderboard().entries(pin, status="pending")})


@app.post("/api/leaderboard/submissions")
async def leaderboard_submit(request: Request) -> JSONResponse:
    """Record one Generate-page artifact on the current board (CL-70).

    The server re-scores the stored bytes; the client sends only the
    artifact version id and a display name.
    """
    from covertlens.leaderboard import (
        DuplicateSubmission,
        clean_display_name,
        configuration_pin,
        score_submission,
    )

    body, error = await _json_object(request)
    if error is not None:
        return error
    identity = _request_identity(request)
    if auth.auth_mode() == "oidc" and identity is None:
        return JSONResponse(
            {"detail": "sign in to submit"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        name = clean_display_name(
            body.get("display_name")
            or (identity.display_name if identity is not None else "")
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    # Anonymous submitters are keyed like the upload limiter: by the
    # client behind a trusted proxy, never a forgeable header (CL-78).
    rate_key = (
        identity.actor_id if identity is not None else f"ip:{_client_key(request)}"
    )
    if not _leaderboard_rate_ok(rate_key):
        return JSONResponse({"detail": "rate_limited"}, status_code=429)
    version_id = str(body.get("artifact_version_id") or "")
    record = _red_team_record(version_id) if version_id else None
    if record is None:
        return JSONResponse(
            {"detail": "unknown artifact: submit an image made on the Generate page"},
            status_code=404,
        )
    digest = str(record["content_hash"]).removeprefix("sha256:")
    media = str((record.get("parameters") or {}).get("kind") or "")
    ext = (
        "jpg"
        if media == "jpeg_dct"
        or (
            media == "metadata"
            and (record.get("parameters") or {}).get("media_kind") == "jpeg"
        )
        else "png"
    )
    path = GENERATED_DIR / f"{digest}.{ext}"
    if not path.is_file():
        return JSONResponse({"detail": "generated bytes are missing"}, status_code=410)
    data = path.read_bytes()
    if "sha256:" + hashlib.sha256(data).hexdigest() != record["content_hash"]:
        return JSONResponse({"detail": "generated bytes do not match"}, status_code=409)
    parameters = {
        k: v
        for k, v in (record.get("parameters") or {}).items()
        if k not in _HIDDEN_PROVENANCE
    }
    if (parameters.get("grid") or {}).get("hidden"):
        # A hidden attacker grid is derived from the scene and payload
        # seeds (CL-51); publishing them would publish the grid.
        parameters.pop("scene_seed", None)
        parameters.pop("payload_seed", None)
    provenance = record.get("parameters") or {}
    parameters["encoder_name"] = (provenance.get("encoder") or {}).get("name")
    parameters["encoder_version"] = (provenance.get("encoder") or {}).get("version")
    future = _executor().submit(score_submission, data, parameters)
    try:
        outcome = await asyncio.wait_for(
            asyncio.wrap_future(future), timeout=ANALYZE_TIMEOUT_S
        )
    except (TimeoutError, concurrent.futures.TimeoutError):
        return JSONResponse({"detail": "scoring_timeout"}, status_code=504)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    try:
        entry = _leaderboard().submit(
            pin=configuration_pin(),
            artifact={
                "content_hash": record["content_hash"],
                "artifact_version_id": version_id,
                "fixture_id": record.get("fixture_id"),
            },
            parameters=parameters,
            outcome=outcome,
            submitter={
                "display_name": name,
                "actor_id": identity.actor_id if identity is not None else "anonymous",
                "auth_method": identity.auth_method if identity is not None else None,
            },
            moderated=_leaderboard_moderated(),
        )
    except DuplicateSubmission as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    from covertlens.leaderboard import public_entry

    return JSONResponse(public_entry(entry), status_code=201)


@app.post("/api/leaderboard/entries/{entry_id}/moderation")
async def leaderboard_moderate(entry_id: str, request: Request) -> JSONResponse:
    """Approve or hide an entry; needs `leaderboard.moderate` (operator)."""
    body, error = await _json_object(request)
    if error is not None:
        return error
    try:
        principal, _role = _require(
            request, LEADERBOARD_DATASET, "leaderboard.moderate"
        )
    except DemoRoleDenied as exc:
        return _denied(exc)
    try:
        entry = _leaderboard().moderate(
            entry_id,
            action=str(body.get("action") or ""),
            actor_id=principal.actor_id,
            reason=str(body.get("reason") or ""),
        )
    except KeyError:
        return JSONResponse({"detail": "entry_not_found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse(entry)


@app.get("/api/benchmarks/{name}")
def benchmark(name: str) -> Response:
    from scripts.precompute import REPORT_COMMANDS

    if name not in (*REPORT_COMMANDS, "provenance"):
        return JSONResponse({"detail": "benchmark_not_found"}, status_code=404)
    cache_file = CACHE_DIR / f"{name}.json"
    key_file = CACHE_DIR / "key.json"
    try:
        current = json.loads(key_file.read_text())
    except (OSError, json.JSONDecodeError):
        current = None
    if current == _cache_key() and cache_file.exists():
        return Response(cache_file.read_bytes(), media_type="application/json")
    if _precompute_error is not None or not _data_dir_writable():
        # Never "computing" forever (CL-78): say why there is no cache.
        return JSONResponse(
            {
                "status": "unavailable",
                "benchmark": name,
                "precompute_error": _precompute_error,
                "data_dir": _data_dir_status,
            },
            status_code=503,
        )
    _start_precompute()
    return JSONResponse({"status": "computing", "benchmark": name}, status_code=202)


@app.get("/api/scorecard")
def scorecard() -> dict[str, Any]:
    from covertlens.scorecard import load_scorecard

    return load_scorecard()


@app.get("/api/comparison")
def comparison() -> JSONResponse:
    """Precomputed two-skyline comparison for the landing page (CL-48)."""
    cache_file = CACHE_DIR / "comparison.json"
    if cache_file.exists():
        return JSONResponse(json.loads(cache_file.read_text()))
    if _precompute_error is not None or not _data_dir_writable():
        return JSONResponse(
            {"status": "unavailable", "precompute_error": _precompute_error},
            status_code=503,
        )
    _start_precompute()
    return JSONResponse(
        {"status": "computing", "comparison": "height_position"}, status_code=202
    )


def _index_response() -> Response | None:
    root = _static_root()
    if root is None:
        return None
    return FileResponse(root / "index.html")


@app.get("/")
def index() -> Response:
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse(
        {
            "service": "covertlens",
            "docs": "/docs",
            "health": "/api/health",
        }
    )


@app.get("/analyze")
def analyze_page() -> Response:
    """SPA route for the Analyze page; same shell as `/` (CL-48)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/generate")
def generate_page() -> Response:
    """SPA route for the Generate / red-team page (CL-51)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/trace")
def trace_page() -> Response:
    """SPA route for the Trace explorer page (CL-60)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/leaderboard")
def leaderboard_page() -> Response:
    """SPA route for the Leaderboard page (CL-70)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/review")
def review_page() -> Response:
    """SPA route for the Reviewer page (CL-59)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/demo")
@app.get("/gate")
def gate_page() -> Response:
    """SPA route for the Live Gate page (CL-53)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/benchmarks")
def benchmarks_page() -> Response:
    """SPA route for the Benchmarks page (CL-79: direct loads 404'd)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/scorecard")
def scorecard_page() -> Response:
    """SPA route for the Scorecard page (CL-79: direct loads 404'd)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/assets/{asset_path:path}")
def frontend_asset(asset_path: str) -> Response:
    """Hashed Vite assets; never a path outside the build (CL-48)."""
    root = _static_root()
    if root is None:
        return JSONResponse({"detail": "frontend_not_built"}, status_code=404)
    assets_dir = (root / "assets").resolve()
    target = (assets_dir / asset_path).resolve()
    if not target.is_relative_to(assets_dir) or not target.is_file():
        return JSONResponse({"detail": "asset_not_found"}, status_code=404)
    return FileResponse(target)
