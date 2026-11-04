"""CL-78 section 3: web service robustness.

Body limits before parsing, worker timeouts and crashes, rate-limit
eviction and proxies, an unwritable data directory, scene context
through the API, and the analysis cache.
"""

import asyncio
import json
import os
import signal
import tempfile
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ["COVERTLENS_PRECOMPUTE"] = "off"
os.environ["COVERTLENS_DATA_DIR"] = tempfile.mkdtemp(prefix="covertlens-robust-")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from covertlens.geo_benchmark import structured_payload_fixture  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def demo_roles(monkeypatch):
    monkeypatch.setenv("COVERTLENS_DEMO_ROLES", "on")


def _asgi(path, chunks, headers=()):
    """Drive the app directly; return (status, chunks the app read)."""
    sent = []
    read = {"n": 0}
    pending = list(chunks)

    async def receive():
        if not pending:
            return {"type": "http.request", "body": b"", "more_body": False}
        read["n"] += 1
        body = pending.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(pending)}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"multipart/form-data; boundary=xyz"),
            *headers,
        ],
        "client": ("127.0.0.1", 5000),
        "server": ("testserver", 80),
    }
    asyncio.run(main.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], read["n"]


def test_declared_oversize_is_refused_without_reading_the_body(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1024)
    huge = str(20 * 1024 * 1024).encode()
    status, read = _asgi(
        "/api/analyze", [b"x" * 65536] * 4, headers=[(b"content-length", huge)]
    )
    assert status == 413
    assert read == 0


def test_chunked_upload_stops_at_the_limit(monkeypatch):
    # No Content-Length: the body is counted as it arrives and the read
    # stops once the limit is passed, long before 20 MiB.
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1024)
    head = (
        b'--xyz\r\nContent-Disposition: form-data; name="file"; '
        b'filename="a.png"\r\nContent-Type: image/png\r\n\r\n'
    )
    chunks = [head] + [b"x" * 65536] * 320  # 20 MiB
    status, read = _asgi("/api/analyze", chunks)
    assert status == 413
    limit = 1024 + main.MULTIPART_OVERHEAD_BYTES
    assert read <= limit // 65536 + 2


def test_gate_delivery_upload_is_size_and_rate_limited(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    too_big = client.post(
        "/api/gate/deliveries",
        data={"run_id": "run_limits"},
        files={"file": ("x.png", b"x" * 200_000, "image/png")},
    )
    assert too_big.status_code == 413
    monkeypatch.setattr(main, "RATE_LIMIT_PER_MIN", 2)
    main._rate_windows.clear()
    codes = [
        client.post(
            "/api/gate/deliveries",
            data={"run_id": "run_limits"},
            files={"file": ("x.png", b"tiny", "image/png")},
        ).status_code
        for _ in range(3)
    ]
    assert codes[-1] == 429
    main._rate_windows.clear()


def _fresh_pool(monkeypatch, workers=1):
    monkeypatch.setenv("COVERTLENS_WORKERS", str(workers))
    if main._pool is not None:
        main._discard_pool(main._pool)


def test_timeouts_kill_the_worker_and_never_block_a_fast_request(monkeypatch):
    _fresh_pool(monkeypatch)
    rebuilds = main._pool_rebuilds

    async def scenario():
        for _ in range(5):
            with pytest.raises(TimeoutError):
                await main._run_in_pool(time.sleep, 30, timeout=0.3)
        start = time.perf_counter()
        value = await main._run_in_pool(pow, 2, 10, timeout=20)
        return value, time.perf_counter() - start

    value, elapsed = asyncio.run(scenario())
    assert value == 1024
    # One worker and five 30 s sleeps: only killing the timed-out
    # workers lets the fast call through quickly.
    assert elapsed < 15
    assert main._pool_rebuilds >= rebuilds + 5


def test_a_killed_worker_does_not_cause_permanent_errors(monkeypatch):
    _fresh_pool(monkeypatch, workers=2)

    async def scenario():
        assert await main._run_in_pool(pow, 3, 2, timeout=20) == 9
        for process in list(main._pool._processes.values()):
            process.kill()
        await asyncio.sleep(0.5)
        return [await main._run_in_pool(pow, 2, n, timeout=20) for n in range(3)]

    assert asyncio.run(scenario()) == [1, 2, 4]


def test_workers_stop_on_sigterm(monkeypatch):
    _fresh_pool(monkeypatch)

    async def warm():
        return await main._run_in_pool(pow, 2, 2, timeout=20)

    assert asyncio.run(warm()) == 4
    process = next(iter(main._pool._processes.values()))
    os.kill(process.pid, signal.SIGTERM)
    process.join(timeout=5)
    assert process.exitcode is not None


def test_rate_windows_are_evicted(monkeypatch):
    main._rate_windows.clear()
    monkeypatch.setattr(main, "_RATE_SWEEP_EVERY", 4)
    # The sweep runs every fourth call overall; start the count here so
    # requests made by earlier tests in this process do not shift it.
    monkeypatch.setattr(main, "_rate_calls", 0)
    for i in range(3):
        main._rate_limited(f"10.0.0.{i}")
    for window in main._rate_windows.values():
        window[-1] -= 120  # a minute and more ago
    main._rate_limited("10.0.0.99")
    assert set(main._rate_windows) == {"10.0.0.99"}
    main._rate_windows.clear()


class _Req:
    def __init__(self, peer, forwarded=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


def test_forwarded_for_is_trusted_only_from_configured_proxies(monkeypatch):
    monkeypatch.delenv(main.TRUSTED_PROXIES_ENV, raising=False)
    assert main._client_key(_Req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"
    monkeypatch.setenv(main.TRUSTED_PROXIES_ENV, "10.0.0.2")
    # A forged left-most hop is ignored; the proxy's view wins.
    assert main._client_key(_Req("10.0.0.2", "6.6.6.6, 198.51.100.7")) == (
        "198.51.100.7"
    )
    assert main._client_key(_Req("203.0.113.9", "6.6.6.6")) == "203.0.113.9"


def test_unwritable_data_dir_is_reported_not_silent(client, monkeypatch, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        monkeypatch.setattr(main, "DATA_DIR", locked / "data")
        monkeypatch.setattr(main, "_data_dir_status", {"checked": False})
        main._reset_gate_for_tests()
        health = client.get("/api/health")
        assert health.status_code == 503
        assert "data_dir_not_writable" in health.json()["problems"]
        gate = client.post("/api/gate/runs", json={"run_id": "run_x"})
        assert gate.status_code == 503
        generate = client.post("/api/generate", json={"subfamily": "height_position"})
        assert generate.status_code == 503
    finally:
        locked.chmod(0o700)
        main._reset_gate_for_tests()
    monkeypatch.setattr(main, "_data_dir_status", {"checked": False})


def test_analyze_accepts_a_scene_declaration(client):
    scene = structured_payload_fixture()
    plain = client.post(
        "/api/analyze", files={"file": ("s.png", scene.data, "image/png")}
    ).json()
    declared = client.post(
        "/api/analyze",
        files={"file": ("s.png", scene.data, "image/png")},
        data={"declared_channels": "height", "scene_context": "chart"},
    ).json()
    assert plain["geometric"]["classification"] == "structure_claimed"
    assert declared["geometric"]["classification"] == "quantized_declared_channel"
    # Declaring lowers the prior; it does not silence the evidence.
    assert declared["geometric"]["signal_grade"] == "triage_declared_structure"
    assert declared["decision"]["verdict"] == "flag"
    bad = client.post(
        "/api/analyze",
        files={"file": ("s.png", scene.data, "image/png")},
        data={"declared_channels": "height,bogus"},
    )
    assert bad.status_code == 400


def test_run_scene_context_is_declared_before_the_run(client, demo_roles):
    run_id = "run_scene_ctx"
    created = client.post(
        "/api/gate/runs",
        json={"run_id": run_id, "declared_channels": ["height"], "context": "chart"},
    )
    assert created.status_code == 200
    assert created.json()["scene_context"]["declared_channels"] == ["height"]
    scene = structured_payload_fixture()
    delivery = client.post(
        "/api/gate/deliveries",
        data={"run_id": run_id},
        files={"file": ("s.png", scene.data, "image/png")},
    ).json()
    analysis = client.post(
        f"/api/gate/deliveries/{delivery['delivery_id']}/analyze"
    ).json()
    geometric = next(
        f for f in analysis["analysis"]["findings"] if f["family"] == "geometric"
    )
    assert geometric["evidence"]["classification"] == "quantized_declared_channel"
    assert analysis["suggested_verdict"] == "flag"
    late = client.post(
        "/api/gate/runs", json={"run_id": run_id, "declared_channels": ["gap"]}
    )
    assert late.status_code == 409
    detail = client.get(f"/api/gate/runs/{run_id}").json()
    assert detail["scene_context"]["declared_channels"] == ["height"]


def test_trace_view_reuses_cached_analysis(client, demo_roles, monkeypatch):
    run_id = "run_cache"
    scene = structured_payload_fixture()
    for _ in range(2):
        client.post(
            "/api/gate/deliveries",
            data={"run_id": run_id},
            files={"file": ("s.png", scene.data, "image/png")},
        )
    import covertlens.metadata as metadata

    calls = {"n": 0}
    real = metadata.analyze_all_with_geometric

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(metadata, "analyze_all_with_geometric", counting)
    headers = {"X-Demo-Role": "researcher"}
    first = client.get(f"/api/trace/runs/{run_id}", headers=headers)
    assert first.status_code == 200
    after_first = calls["n"]
    second = client.get(f"/api/trace/runs/{run_id}", headers=headers)
    assert second.status_code == 200
    assert calls["n"] == after_first
    assert json.dumps(first.json(), sort_keys=True) == json.dumps(
        second.json(), sort_keys=True
    )
