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
        "quantized_without_structure", "structure_claimed")
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


def test_oversized_pixels_return_explicit_status(client, geo_encoded,
                                                 monkeypatch):
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
