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
import os
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

import covertlens
from covertlens.manifest import load_manifest
from covertlens.pinning import default_detector_versions

from .analysis_worker import analyze_bytes
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

_pool: concurrent.futures.ProcessPoolExecutor | None = None
_rate_windows: dict[str, deque] = {}
_precompute_started = False
_precompute_lock = threading.Lock()


def _executor() -> concurrent.futures.ProcessPoolExecutor:
    global _pool
    if _pool is None:
        workers = int(os.environ.get("COVERTLENS_WORKERS", "4"))
        _pool = concurrent.futures.ProcessPoolExecutor(max_workers=workers)
    return _pool


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
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.precompute(CACHE_DIR)


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
    if request.url.path in ("/api/analyze", "/api/generate"):
        now = time.time()
        window = _rate_windows.setdefault(request.client.host, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MIN:
            return JSONResponse({"detail": "rate_limited"}, status_code=429)
        window.append(now)
    response = await call_next(request)
    _apply_security_headers(response)
    return response


def _apply_security_headers(response: Response) -> None:
    # A route may set its own CSP (only /docs does); keep it.
    if "content-security-policy" not in response.headers:
        response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"


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
    """Whether `X-Demo-Role` is honoured (CL-78).

    The header is a demo convenience, not authentication: any client
    can send any role. Only the demo deployment (the Docker image)
    turns it on. When off, every request is a `viewer`. Real roles
    are CL-67.
    """
    value = os.environ.get(DEMO_ROLES_ENV, "off").strip().lower()
    return value in ("on", "1", "true", "yes")


class DemoRoleDenied(PermissionError):
    """The request's demo role lacks a runtime-policy permission."""

    def __init__(self, role: str, permission: str) -> None:
        super().__init__(f"demo role {role!r} lacks {permission}")
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
    return JSONResponse(
        {
            "detail": "permission denied for demo role",
            "role": exc.role,
            "needs": exc.permission,
            "demo_roles_enabled": _demo_roles_enabled(),
        },
        status_code=403,
    )


def _original_readers(run_id: str) -> set[str]:
    """Actor ids the runtime policy lets read originals of this run."""
    from covertlens.review import DEMO_ROLES, demo_principal
    from covertlens.runtime import can

    policy = _runtime_policy()
    readers = set()
    for role in DEMO_ROLES:
        principal = demo_principal(role, run_id)
        if can(policy, principal, run_id, "original.read"):
            readers.add(principal.actor_id)
    return readers


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": covertlens.__version__,
        "git_sha": GIT_SHA,
        "precompute_started": _precompute_started,
        "cache_ready": _cache_ready(),
    }


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


@app.post("/api/analyze")
async def analyze(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_UPLOAD_BYTES:
        # Size limit enforced before the body is read.
        return JSONResponse({"detail": "upload_too_large"}, status_code=413)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"detail": "upload_too_large"}, status_code=413)
    try:
        max_pixels = int(os.environ.get("COVERTLENS_MAX_PIXELS", str(20_000_000)))
    except ValueError:
        max_pixels = 20_000_000
    future = _executor().submit(analyze_bytes, data, max_pixels)
    try:
        payload = await asyncio.wait_for(
            asyncio.wrap_future(future), timeout=ANALYZE_TIMEOUT_S
        )
    except (TimeoutError, concurrent.futures.TimeoutError):
        return JSONResponse(
            {
                "status": "timeout",
                "detail": f"analysis exceeded {ANALYZE_TIMEOUT_S}s deadline",
                "analysis": None,
                "geometric": None,
                "decision": None,
            }
        )
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
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_GENERATE_BODY_BYTES:
        return JSONResponse({"detail": "request_too_large"}, status_code=413)
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
    future = _executor().submit(generate_image, params)
    try:
        result = await asyncio.wait_for(
            asyncio.wrap_future(future), timeout=ANALYZE_TIMEOUT_S
        )
    except (TimeoutError, concurrent.futures.TimeoutError):
        return JSONResponse({"detail": "generation_timeout"}, status_code=504)
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


# -- Live Gate (CL-53) -------------------------------------------------

_gate_instance: Any = None
_gate_lock = threading.Lock()


def _gate() -> Any:
    """Persistent gate singleton over the file-backed store."""
    global _gate_instance
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
                "detail": "reviewer access denied: the original needs a demo role"
                " with original.read (researcher or reviewer)",
                "demo_roles_enabled": _demo_roles_enabled(),
            },
            status_code=403,
        )
    if isinstance(exc, ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)
    raise exc


@app.get("/api/gate/runs")
def gate_runs() -> dict[str, Any]:
    gate = _gate()
    return {"runs": gate.runs()}


@app.post("/api/gate/runs")
async def gate_create_run(request: Request) -> JSONResponse:
    body, error = await _json_object(request)
    if error is not None:
        return error
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        import uuid

        run_id = f"run_{uuid.uuid4().hex[:16]}"
    return JSONResponse({"run_id": run_id, "known_runs": _gate().runs()})


@app.post("/api/gate/deliveries")
async def gate_create_delivery(
    file: UploadFile = File(...),
    run_id: str = Form(...),
    sender_id: str = Form("agent-a"),
    recipient_id: str = Form("agent-b"),
    route_id: str = Form("R-01"),
    episode_id: str | None = Form(None),
) -> JSONResponse:
    from covertlens.gate import InterceptionContext

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
def gate_run_detail(run_id: str) -> JSONResponse:
    gate = _gate()
    deliveries = [_delivery_payload(r) for r in gate.deliveries(run_id)]
    events = [e.to_dict() for e in gate.events(run_id)]
    return JSONResponse(
        {
            "run_id": run_id,
            "deliveries": deliveries,
            "events": events,
            "access_report": gate.access_attempt_report(),
            "access_attempts": gate.access_attempts(),
            "coverage": gate.coverage_report(),
        }
    )


@app.post("/api/gate/deliveries/{delivery_id}/analyze")
def gate_analyze_delivery(delivery_id: str) -> JSONResponse:
    """Analyse a pending delivery's bytes; stays pending (CL-53)."""
    gate = _gate()
    try:
        record = gate.get_delivery(delivery_id)
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    if record.state != "pending":
        return JSONResponse(
            {"detail": f"delivery already decided ({record.state})"},
            status_code=409,
        )
    try:
        data = gate.store.get_original(
            record.artifact_version_id,
            actor_id="gate-analyzer",
            purpose="analysis",
        )
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    from covertlens.metadata import analyze_all_bytes
    from covertlens.verdicts import decide_verdict

    result = analyze_all_bytes(data)
    decision = decide_verdict(result.findings)
    return JSONResponse(
        {
            "delivery": _delivery_payload(record),
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
def gate_recipient_image(delivery_id: str) -> Response:
    """Recipient view: bytes only after a permitting verdict."""
    gate = _gate()
    try:
        record = gate.get_delivery(delivery_id)
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
            reviewer_ids=_original_readers(record.run_id),
        )
    except Exception as exc:  # noqa: BLE001
        return _gate_error(exc)
    media = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(
        content=data, media_type=media, headers={"Cache-Control": "no-store"}
    )


@app.get("/api/gate/runs/{run_id}/events/stream")
async def gate_event_stream(run_id: str, request: Request) -> StreamingResponse:
    """SSE timeline for one run (CL-53): replay, then poll for new seqs."""
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
    """Demo principal for the request; `viewer` unless demo roles are on."""
    from covertlens.review import demo_principal

    role = "viewer"
    if _demo_roles_enabled():
        role = (request.headers.get("x-demo-role") or "viewer").strip().lower()
    return demo_principal(role, dataset_id), role


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
        decode_id = workspace.ensure_candidate_decode(record.run_id, record)
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
    }


@app.get("/api/review/runs/{run_id}/queue")
def review_queue(run_id: str, request: Request) -> JSONResponse:
    try:
        _principal, _role = _demo_principal(request, run_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
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
        _principal, _role = _demo_principal(request, record.run_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _review_error(exc)
    from covertlens.geometric import analyze_geometric_bytes
    from covertlens.metadata import analyze_all_bytes

    data = gate.store.get_original(
        record.artifact_version_id, actor_id="review-detail", purpose="analysis"
    )
    analysis = analyze_all_bytes(data, artifact_version_id=record.artifact_version_id)
    geometric = analyze_geometric_bytes(data)
    geometric.pop("candidate_decode", None)  # reviewer-only (CL-46/CL-59)
    geometric.pop("finding", None)
    segmentation = geometric.get("segmentation")
    if isinstance(segmentation, dict):
        segmentation.pop("decoded_message", None)
    row = _review_delivery_row(gate, workspace, record)
    return JSONResponse(
        {
            **row,
            "analysis": analysis.to_dict(),
            "geometric": geometric,
        }
    )


@app.get("/api/review/deliveries/{delivery_id}/candidate-decode")
def review_candidate_decode(delivery_id: str, request: Request) -> JSONResponse:
    gate = _gate()
    workspace = _review_workspace()
    try:
        record = gate.get_delivery(delivery_id)
        principal, _role = _demo_principal(request, record.run_id)
        decode_id = workspace.ensure_candidate_decode(record.run_id, record)
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
    from covertlens.metadata import analyze_all_bytes
    from covertlens.trace_explorer import build_trace_explorer

    try:
        _require(request, run_id, "trace.read")
    except DemoRoleDenied as exc:
        return _denied(exc)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    gate = _gate()
    results = []
    for record in gate.deliveries(run_id):
        data = gate.store.get_original(
            record.artifact_version_id,
            actor_id="trace-explorer",
            purpose="analysis",
        )
        results.append(
            analyze_all_bytes(data, artifact_version_id=record.artifact_version_id)
        )
    view = build_trace_explorer(gate.events(run_id), results)
    if view["run_id"] is None:
        view["run_id"] = run_id
    return JSONResponse(view)


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


@app.get("/review")
def review_page() -> Response:
    """SPA route for the Reviewer page (CL-59)."""
    response = _index_response()
    if response is not None:
        return response
    return JSONResponse({"detail": "frontend_not_built"}, status_code=404)


@app.get("/gate")
def gate_page() -> Response:
    """SPA route for the Live Gate page (CL-53)."""
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
