"""CL-47 acceptance: web service endpoints (skips without fastapi)."""

import os
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ["COVERTLENS_PRECOMPUTE"] = "off"
os.environ["COVERTLENS_DATA_DIR"] = tempfile.mkdtemp(prefix="covertlens-web-")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from covertlens.geometric_fixtures import build_geo_pair  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def geo_encoded():
    _clean, encoded = build_geo_pair("height_position")
    return encoded


def test_health_and_version(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in health.headers
    version = client.get("/api/version")
    assert version.status_code == 200
    body = version.json()
    assert body["manifest_version"] == "1.1.0"
    assert any("geometric" in d for d in body["detectors"])


def test_fixtures_listed_and_served(client):
    listing = client.get("/api/fixtures")
    assert listing.status_code == 200
    entries = listing.json()
    assert any(e["kind"] == "encoded" for e in entries)
    assert all("_data" not in e for e in entries)
    entry = next(e for e in entries if e["kind"] == "encoded")
    digest = entry["content_hash"].removeprefix("sha256:")
    png = client.get(f"/api/fixtures/{digest}.png")
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/api/fixtures/deadbeef.png").status_code == 404


def test_analyze_returns_four_families_and_decision(client, geo_encoded):
    response = client.post(
        "/api/analyze",
        files={"file": ("scene.png", geo_encoded.data, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "parsed"
    families = {f["family"] for f in payload["analysis"]["findings"]}
    assert "geometric" in families
    assert payload["geometric"]["classification"] in (
        "quantized_without_structure",
        "structure_claimed",
    )
    assert payload["decision"]["enforceable"] is False
    # Reviewer-only material is stripped from API responses (CL-46).
    assert "candidate_decode" not in response.text
    assert "DECAF" not in response.text


def test_analyze_rejects_garbage_without_hanging(client):
    response = client.post(
        "/api/analyze",
        files={"file": ("x.png", b"not an image", "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["status"] != "parsed"
    assert response.json()["decision"] is None


def test_oversized_pixels_return_explicit_status(client, geo_encoded, monkeypatch):
    monkeypatch.setenv("COVERTLENS_MAX_PIXELS", "100")
    response = client.post(
        "/api/analyze",
        files={"file": ("scene.png", geo_encoded.data, "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "oversized"


def test_upload_size_limit_before_read(client, monkeypatch):
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 10)
    response = client.post(
        "/api/analyze",
        files={"file": ("scene.png", b"x" * 5000, "image/png")},
    )
    assert response.status_code == 413


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr("app.main.RATE_LIMIT_PER_MIN", 2)
    import app.main as main_module

    main_module._rate_windows.clear()
    codes = [
        client.post(
            "/api/analyze",
            files={"file": ("x.png", b"junk", "image/png")},
        ).status_code
        for _ in range(3)
    ]
    assert codes[-1] == 429


def test_scorecard_and_benchmarks_endpoints(client):
    card = client.get("/api/scorecard")
    assert card.status_code == 200
    assert "geometric" in card.json()["sections"]
    computing = client.get("/api/benchmarks/geometric")
    assert computing.status_code in (200, 202)
    assert client.get("/api/benchmarks/nope").status_code == 404


def test_openapi_docs_served(client):
    docs = client.get("/docs")
    assert docs.status_code == 200
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "/api/analyze" in spec.json()["paths"]


def test_analyze_includes_overlay_series(client, geo_encoded):
    """CL-48: the overlay renders from this JSON alone."""
    response = client.post(
        "/api/analyze",
        files={"file": ("scene.png", geo_encoded.data, "image/png")},
    )
    assert response.status_code == 200
    geometric = response.json()["geometric"]
    # No decoded-text slot crosses the API (CL-48).
    assert "decoded_message" not in geometric["segmentation"]
    overlay = geometric["overlay"]
    assert overlay["version"] == "1.0.0"
    sequences = geometric["segmentation"]["sequences"]
    height = overlay["channels"]["height"]
    assert height["values"] == [float(v) for v in sequences["height"]]
    assert height["sequence_attribute"] == "height"
    channel = geometric["channels"]["height"]
    periodogram = height["periodogram"]
    assert periodogram["available"] is True
    assert periodogram["discovered_step"] == channel["step"]
    # The discovered step/R headline appears verbatim in the sweep.
    assert any(
        p["step"] == channel["step"] and p["rayleigh_R"] == channel["rayleigh_R"]
        for p in periodogram["points"]
    )
    steps = [p["step"] for p in periodogram["points"]]
    assert steps == sorted(steps)
    histogram = height["residual_histogram"]
    assert sum(histogram["counts"]) == len(channel["residuals"])
    assert len(histogram["bin_edges"]) == len(histogram["counts"]) + 1
    gap = overlay["channels"]["gap"]
    assert len(gap["values"]) == len(geometric["segmentation"]["elements"]) - 1
    # Colour has no Rayleigh grid by construction.
    assert overlay["channels"]["colour"]["periodogram"]["available"] is False


def test_comparison_endpoint(client):
    """CL-48: precomputed skyline pair, computing until cached."""
    import json

    import app.main as main_module

    # Precompute is off in this module, so an empty cache is explicit.
    computing = client.get("/api/comparison")
    assert computing.status_code in (200, 202)
    if computing.status_code == 202:
        from scripts.precompute import build_comparison

        cache_file = main_module.CACHE_DIR / "comparison.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(build_comparison()))
        try:
            ready = client.get("/api/comparison")
            assert ready.status_code == 200
            body = ready.json()
        finally:
            cache_file.unlink(missing_ok=True)
    else:
        body = computing.json()
    assert body["schema"] == "covertlens.skyline-comparison"
    assert body["clean"]["payload"]["geometric"]["classification"] == "no_signal"
    assert body["encoded"]["payload"]["geometric"]["classification"] in (
        "quantized_without_structure",
        "structure_claimed",
    )
    assert "overlay" in body["encoded"]["payload"]["geometric"]
    assert "candidate_decode" not in str(body)
    hashes = {e["content_hash"] for e in client.get("/api/fixtures").json()}
    assert body["clean"]["content_hash"] in hashes
    assert body["encoded"]["content_hash"] in hashes


def test_spa_routes_and_assets(client, tmp_path, monkeypatch):
    """CL-48: / and /analyze serve the shell; /api stays unshadowed."""
    import app.main as main_module

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')")
    monkeypatch.setattr(main_module, "STATIC_CANDIDATES", [tmp_path])
    for path in ("/", "/analyze"):
        page = client.get(path)
        assert page.status_code == 200
        assert "<title>spa</title>" in page.text
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/assets/..%2Findex.html").status_code == 404
    # API and docs are never swallowed by the single-page app.
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200


def test_spa_routes_without_build(client, tmp_path, monkeypatch):
    """CL-48: an API-only deployment says so instead of 500ing."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "STATIC_CANDIDATES", [tmp_path / "nope"])
    missing = client.get("/analyze")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "frontend_not_built"
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["service"] == "covertlens"
