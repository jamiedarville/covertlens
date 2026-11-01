"""CovertLens web service (CL-47).

Thin FastAPI layer over the library:

- `POST /api/analyze` — multipart upload; analysis runs in a
  ProcessPoolExecutor (`COVERTLENS_WORKERS`, default 4) with a
  wall-clock deadline mapped to the library's `timeout` status;
  upload size is limited before the body is read; per-IP rate
  limit; reviewer-only fields are stripped by the worker.
- `GET /api/fixtures`, `GET /api/fixtures/{digest}.png`
- `GET /api/benchmarks/{name}` — cached precompute output.
- `GET /api/scorecard`, `GET /api/version`, `GET /api/health`.
- OpenAPI at `/docs`; the built frontend is served statically.

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
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

import covertlens
from covertlens.manifest import load_manifest
from covertlens.pinning import default_detector_versions

from .analysis_worker import analyze_bytes

DATA_DIR = Path(os.environ.get("COVERTLENS_DATA_DIR", "/data"))
CACHE_DIR = DATA_DIR / "cache"
STATIC_DIR = Path(__file__).resolve().parent / "static"
GIT_SHA = os.environ.get("GIT_SHA", "unknown")
ANALYZE_TIMEOUT_S = float(os.environ.get("COVERTLENS_ANALYZE_TIMEOUT_S", "30"))
MAX_UPLOAD_BYTES = int(os.environ.get("COVERTLENS_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
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
        entries.append({
            "fixture_id": fixture.fixture_id,
            "kind": fixture.role,
            "subfamily": fixture.subfamily,
            "content_hash": fixture.content_hash,
            "media_type": "image/png",
            "_data": fixture.data,
        })
    for control in benign_controls():
        entries.append({
            "fixture_id": control["control_id"],
            "kind": f"benign_control:{control['kind']}",
            "subfamily": None,
            "content_hash": control["content_hash"],
            "media_type": "image/png",
            "_data": control["data"],
        })
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
    if current == _cache_key() and (CACHE_DIR / "geometric.json").exists():
        return
    threading.Thread(target=_precompute, daemon=True,
                     name="covertlens-precompute").start()


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
    if request.url.path == "/api/analyze":
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
        "cache_ready": (CACHE_DIR / "geometric.json").exists(),
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
        max_pixels = int(os.environ.get(
            "COVERTLENS_MAX_PIXELS", str(20_000_000)))
    except ValueError:
        max_pixels = 20_000_000
    loop = asyncio.get_running_loop()
    future = _executor().submit(analyze_bytes, data, max_pixels)
    try:
        payload = await asyncio.wait_for(
            asyncio.wrap_future(future), timeout=ANALYZE_TIMEOUT_S)
    except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
        return JSONResponse({
            "status": "timeout",
            "detail": f"analysis exceeded {ANALYZE_TIMEOUT_S}s deadline",
            "analysis": None, "geometric": None, "decision": None,
        })
    return JSONResponse(payload)


@app.get("/api/benchmarks/{name}")
def benchmark(name: str) -> JSONResponse:
    if name != "geometric":
        return JSONResponse({"detail": "benchmark_not_found"}, status_code=404)
    cache_file = CACHE_DIR / "geometric.json"
    if cache_file.exists():
        return JSONResponse(json.loads(cache_file.read_text()))
    _start_precompute()
    return JSONResponse(
        {"status": "computing", "benchmark": name}, status_code=202)


@app.get("/api/scorecard")
def scorecard() -> dict[str, Any]:
    from covertlens.scorecard import load_scorecard

    return load_scorecard()


@app.get("/")
def index() -> Response:
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({
        "service": "covertlens",
        "docs": "/docs",
        "health": "/api/health",
    })
