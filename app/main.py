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
- OpenAPI at `/docs`; the built React frontend is served
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
import concurrent.futures
import json
import os
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

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

app = FastAPI(title="CovertLens", version=covertlens.__version__)

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
    return {"library_version": covertlens.__version__, "git_sha": GIT_SHA}


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
    return (CACHE_DIR / "geometric.json").exists() and (
        CACHE_DIR / "comparison.json"
    ).exists()


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


@app.middleware("http")
async def _security_and_rate_limit(request: Request, call_next):
    if request.url.path in ("/api/analyze", "/api/generate"):
        now = time.time()
        window = _rate_windows.setdefault(request.client.host, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MIN:
            return JSONResponse({"detail": "rate_limited"}, status_code=429)
        window.append(now)
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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


@app.get("/api/benchmarks/{name}")
def benchmark(name: str) -> JSONResponse:
    if name != "geometric":
        return JSONResponse({"detail": "benchmark_not_found"}, status_code=404)
    cache_file = CACHE_DIR / "geometric.json"
    if cache_file.exists():
        return JSONResponse(json.loads(cache_file.read_text()))
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
