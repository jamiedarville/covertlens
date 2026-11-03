"""CL-78 section 1: web access control, CSRF and security headers.

- Demo roles are honoured only when COVERTLENS_DEMO_ROLES is on;
  otherwise every request is a viewer.
- Reviewer image, audit, trace and gate verdicts check the CL-11
  runtime policy (original.read, trace.read, verdict.override).
- JSON endpoints refuse non-JSON bodies, and unsafe /api requests
  from another site are blocked.
- Responses carry frame-ancestors, X-Frame-Options and
  Referrer-Policy; /docs gets a CSP Swagger can load under.
"""

import base64
import hashlib
import os
import re
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ.setdefault("COVERTLENS_PRECOMPUTE", "off")
os.environ.setdefault(
    "COVERTLENS_DATA_DIR", tempfile.mkdtemp(prefix="covertlens-security-test-")
)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from covertlens.geometric_fixtures import build_geo_pair  # noqa: E402

RESEARCHER = {"X-Demo-Role": "researcher"}
REVIEWER = {"X-Demo-Role": "reviewer"}
VIEWER = {"X-Demo-Role": "viewer"}
RUN = "run_security"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "GATE_STORE_DIR", tmp_path / "gate-store")
    monkeypatch.setenv("COVERTLENS_DEMO_ROLES", "on")
    main_module._reset_gate_for_tests()
    with TestClient(app) as test_client:
        yield test_client
    main_module._reset_gate_for_tests()


def _pending(client, run_id=RUN):
    _clean, encoded = build_geo_pair("height_position")
    created = client.post(
        "/api/gate/deliveries",
        files={"file": ("scene.png", encoded.data, "image/png")},
        data={"run_id": run_id, "route_id": "R-01"},
    )
    assert created.status_code == 200, created.text
    return created.json()["delivery_id"], encoded.data


def _verdict_url(delivery_id):
    return f"/api/gate/deliveries/{delivery_id}/verdict"


# -- roles -----------------------------------------------------------------


def test_verdict_needs_verdict_override(client):
    delivery_id, _raw = _pending(client)
    for headers in ({}, VIEWER, REVIEWER):
        denied = client.post(
            _verdict_url(delivery_id), json={"verdict": "log"}, headers=headers
        )
        assert denied.status_code == 403, headers
        assert denied.json()["needs"] == "verdict.override"
    state = client.get(f"/api/gate/runs/{RUN}").json()["deliveries"][0]["state"]
    assert state == "pending"
    allowed = client.post(
        _verdict_url(delivery_id), json={"verdict": "log"}, headers=RESEARCHER
    )
    assert allowed.status_code == 200
    assert allowed.json()["state"] == "permitted"


def test_audit_and_trace_need_trace_read(client):
    _pending(client)
    for url in (f"/api/review/audit?run_id={RUN}", f"/api/trace/runs/{RUN}"):
        for headers in ({}, VIEWER):
            denied = client.get(url, headers=headers)
            assert denied.status_code == 403, (url, headers)
            assert denied.json()["needs"] == "trace.read"
        for headers in (RESEARCHER, REVIEWER):
            assert client.get(url, headers=headers).status_code == 200, url


def test_unknown_demo_role_is_rejected(client):
    _pending(client)
    response = client.get(f"/api/trace/runs/{RUN}", headers={"X-Demo-Role": "admin"})
    assert response.status_code == 400


def test_demo_roles_off_treats_every_request_as_viewer(client, monkeypatch):
    delivery_id, raw = _pending(client)
    decided = client.post(
        _verdict_url(delivery_id), json={"verdict": "quarantine"}, headers=RESEARCHER
    )
    assert decided.status_code == 200
    monkeypatch.setenv("COVERTLENS_DEMO_ROLES", "off")

    roles = client.get("/api/review/roles").json()
    assert roles["enabled"] is False
    image = client.get(
        f"/api/gate/deliveries/{delivery_id}/reviewer-image", headers=RESEARCHER
    )
    assert image.status_code == 403
    assert image.json()["demo_roles_enabled"] is False
    assert raw not in image.content
    original = client.get(
        f"/api/review/deliveries/{delivery_id}/original", headers=REVIEWER
    )
    assert original.status_code == 403
    trace = client.get(f"/api/trace/runs/{RUN}", headers=RESEARCHER)
    assert trace.status_code == 403
    # "admin" is no longer a 400: the header is ignored entirely.
    queue = client.get(f"/api/review/runs/{RUN}/queue", headers={"X-Demo-Role": "x"})
    assert queue.status_code == 200


def test_demo_roles_default_is_off(monkeypatch):
    monkeypatch.delenv("COVERTLENS_DEMO_ROLES", raising=False)
    assert main_module._demo_roles_enabled() is False


# -- CSRF ------------------------------------------------------------------


def test_verdict_rejects_text_plain_body(client):
    """The forged cross-site form from the review: text/plain JSON."""
    delivery_id, _raw = _pending(client)
    forged = client.post(
        _verdict_url(delivery_id),
        content=b'{"verdict": "log"}',
        headers={"Content-Type": "text/plain", **RESEARCHER},
    )
    assert forged.status_code == 415
    state = client.get(f"/api/gate/runs/{RUN}").json()["deliveries"][0]["state"]
    assert state == "pending"


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/gate/runs", b"{}"),
        ("/api/generate", b"{}"),
        ("/api/review/deliveries/unknown/disposition", b'{"disposition": "benign"}'),
    ],
)
def test_json_endpoints_reject_form_bodies(client, path, body):
    response = client.post(
        path,
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", **REVIEWER},
    )
    assert response.status_code == 415, path


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
    ],
)
def test_cross_site_unsafe_requests_blocked(client, headers):
    delivery_id, _raw = _pending(client)
    response = client.post(
        _verdict_url(delivery_id),
        json={"verdict": "log"},
        headers={**RESEARCHER, **headers},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "cross_site_request_blocked"
    assert response.headers["x-frame-options"] == "DENY"
    # The multipart upload path is covered too.
    upload = client.post(
        "/api/gate/deliveries",
        files={"file": ("x.png", b"\x89PNG", "image/png")},
        data={"run_id": RUN},
        headers=headers,
    )
    assert upload.status_code == 403


def test_same_origin_and_allowed_origins_pass(client, monkeypatch):
    delivery_id, _raw = _pending(client)
    same = client.post(
        _verdict_url(delivery_id),
        json={"verdict": "log"},
        headers={**RESEARCHER, "Origin": "http://testserver"},
    )
    assert same.status_code == 200
    monkeypatch.setenv("COVERTLENS_ALLOWED_ORIGINS", "https://demo.example")
    created = client.post(
        "/api/gate/runs", json={}, headers={"Origin": "https://demo.example"}
    )
    assert created.status_code == 200
    # Safe methods are never blocked: a cross-site GET changes nothing.
    assert (
        client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 200
    )


# -- headers -----------------------------------------------------------------


def test_security_headers_on_every_response(client):
    for path in ("/api/health", "/api/fixtures/deadbeef.png"):
        response = client.get(path)
        csp = response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp
        assert "script-src 'self'" in csp
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_docs_csp_allows_swagger_and_pins_inline_script(client):
    response = client.get("/docs")
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in csp
    assert "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    scripts = re.findall(r"<script>(.*?)</script>", response.text, re.DOTALL)
    assert scripts
    for script in scripts:
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in csp
    assert client.get("/openapi.json").status_code == 200
    # ReDoc is switched off rather than left blank under the CSP.
    assert client.get("/redoc").status_code == 404


def test_export_filename_is_header_safe():
    header = main_module._attachment('review-a"b;c\r\nSet-Cookie: x.json')
    assert "\r" not in header and "\n" not in header
    plain = re.search(r'filename="([^"]*)"', header)
    assert plain is not None
    assert re.fullmatch(r"[A-Za-z0-9._-]+", plain.group(1))
    assert "filename*=UTF-8''review-a%22b%3Bc%0D%0ASet-Cookie%3A%20x.json" in header


def test_export_route_uses_safe_filename(client):
    run_id = 'run"x;y'
    _pending(client, run_id=run_id)
    response = client.get(f"/api/review/runs/{run_id}/export", headers=RESEARCHER)
    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    assert 'filename="review-run_x_y.json"' in disposition
    assert "filename*=UTF-8''review-run%22x%3By.json" in disposition
