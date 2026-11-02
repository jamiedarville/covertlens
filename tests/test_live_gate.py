"""CL-53 acceptance tests: persisted gate state and the Live Gate page.

AC1 restarting mid-run leaves the run, deliveries and trace intact
AC2 unauthorized_served is computed and is 0 in every test
AC3 recipient pane shows "withheld" with the gate's reason for
    quarantine and fail_run verdicts (API contract the pane renders)
"""

import json
import os
import tempfile

import pytest

from covertlens.events import Verdict
from covertlens.gate import InterceptionContext, InterceptionGate
from covertlens.store import ArtifactStore

PNG = b"\x89PNG\r\n\x1a\n" + b"live-gate-test-image-v1"
CTX = InterceptionContext(run_id="run_live", episode_id="ep_1", sender_id="agent-a")


def test_store_access_history_lives_in_sqlite_not_index_json(tmp_path):
    root = tmp_path / "evidence"
    store = ArtifactStore(root)
    version = store.put_original(PNG, run_id="run_live", producer_id="agent-a")
    store.get_original(version.artifact_version_id, actor_id="gate", purpose="analysis")
    index = json.loads((root / "index.json").read_text())
    assert "access" not in index
    assert (root / "covertlens.sqlite3").exists()
    reopened = ArtifactStore(root)
    history = reopened.access_history(version.artifact_version_id)
    assert [(h.actor_id, h.purpose) for h in history] == [("gate", "analysis")]


def test_store_derivatives_survive_reopen(tmp_path):
    root = tmp_path / "evidence"
    store = ArtifactStore(root)
    version = store.put_original(PNG, run_id="run_live", producer_id="agent-a")
    derivative = store.register_derivative(
        version.artifact_version_id, b"thumbnail-bytes", transform="preview_thumbnail"
    )
    reopened = ArtifactStore(root)
    assert reopened.get_derivative(derivative.derivative_id) == derivative
    assert reopened.derivatives(version.artifact_version_id) == (derivative,)
    assert reopened.stats()["derivatives"] == 1


def test_gate_state_survives_restart_mid_run(tmp_path):
    root = tmp_path / "evidence"
    gate = InterceptionGate(ArtifactStore(root))
    handle = gate.intercept_reference("R-03", "ref://img-1", lambda _r: PNG, CTX)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    token = gate.issue_cached_link(delivery.delivery_id)
    gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
    assert gate.recipient_access(delivery.delivery_id) == PNG
    events_before = [e.event_type for e in gate.events("run_live")]

    # Restart: fresh store + gate objects over the same root.
    gate2 = InterceptionGate(ArtifactStore(root))
    assert gate2.runs() == ["run_live"]
    restored = gate2.get_delivery(delivery.delivery_id)
    assert restored.state == "permitted"
    assert restored.verdict is Verdict.FLAG
    assert [e.event_type for e in gate2.events("run_live")] == events_before
    assert gate2.coverage_report()["covered"] == ["R-03"]
    # References and cached links still resolve without re-ingest.
    again = gate2.intercept_reference("R-03", "ref://img-1", lambda _r: b"wrong", CTX)
    assert again.artifact_version_id == handle.artifact_version_id
    assert gate2.redeem_cached_link(token) == PNG
    assert gate2.access_attempt_report()["unauthorized_served"] == 0


def test_unauthorized_served_is_computed_not_hardcoded():
    gate = InterceptionGate(ArtifactStore())
    handle = gate.intercept_bytes("R-01", PNG, CTX)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    gate.record_verdict(delivery.delivery_id, Verdict.QUARANTINE)
    # A serve recorded while withheld must count as unauthorized.
    gate._access_attempts.append(
        {
            "delivery_id": delivery.delivery_id,
            "via_route": "R-04",
            "outcome": "served",
            "delivery_state": "withheld",
        }
    )
    assert gate.access_attempt_report()["unauthorized_served"] == 1
    gate._access_attempts.pop()
    assert gate.access_attempt_report()["unauthorized_served"] == 0


# -- Live Gate API -----------------------------------------------------

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ.setdefault("COVERTLENS_PRECOMPUTE", "off")
os.environ.setdefault(
    "COVERTLENS_DATA_DIR", tempfile.mkdtemp(prefix="covertlens-gate-test-")
)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from covertlens.geometric_fixtures import build_geo_pair  # noqa: E402


@pytest.fixture()
def gate_client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "GATE_STORE_DIR", tmp_path / "gate-store")
    main_module._reset_gate_for_tests()
    with TestClient(app) as client:
        yield client
    main_module._reset_gate_for_tests()


def _post_delivery(client, run_id="run_ui", verdict=None):
    _clean, encoded = build_geo_pair("height_position")
    created = client.post(
        "/api/gate/deliveries",
        files={"file": ("scene.png", encoded.data, "image/png")},
        data={
            "run_id": run_id,
            "sender_id": "agent-a",
            "recipient_id": "agent-b",
            "route_id": "R-01",
            "episode_id": "ep_1",
        },
    )
    assert created.status_code == 200, created.text
    delivery = created.json()
    assert delivery["state"] == "pending"
    assert delivery["recipient_message"].startswith("pending")
    if verdict is not None:
        analysed = client.post(
            f"/api/gate/deliveries/{delivery['delivery_id']}/analyze"
        )
        assert analysed.status_code == 200, analysed.text
        decided = client.post(
            f"/api/gate/deliveries/{delivery['delivery_id']}/verdict",
            json={"verdict": verdict},
        )
        assert decided.status_code == 200, decided.text
        delivery = decided.json()
    return delivery, encoded.data


@pytest.mark.parametrize("verdict", ["quarantine", "fail_run"])
def test_recipient_pane_contract_withheld_with_reason(gate_client, verdict):
    """The pane renders exactly this: 'withheld' + reason, no bytes."""
    delivery, raw = _post_delivery(gate_client, verdict=verdict)
    assert delivery["state"] == "withheld"
    assert delivery["verdict"] == verdict
    assert delivery["recipient_message"] == f"withheld — {verdict} verdict"

    recipient = gate_client.get(
        f"/api/gate/deliveries/{delivery['delivery_id']}/recipient-image"
    )
    assert recipient.status_code == 403
    assert recipient.json()["detail"] == f"withheld — {verdict} verdict"
    assert recipient.content != raw
    assert b"\x89PNG" not in recipient.content

    # The reviewer pane path still serves the original (audited R-08).
    reviewer = gate_client.get(
        f"/api/gate/deliveries/{delivery['delivery_id']}/reviewer-image"
    )
    assert reviewer.status_code == 200
    assert reviewer.content == raw

    detail = gate_client.get("/api/gate/runs/run_ui").json()
    assert detail["access_report"]["unauthorized_served"] == 0
    assert detail["access_report"]["withheld_denied"] >= 1
    assert [e["event_type"] for e in detail["events"]] == [
        "artifact.created",
        "delivery.attempted",
        "gate.verdict",
    ]


def test_live_gate_permitted_delivery_serves_recipient(gate_client):
    delivery, raw = _post_delivery(gate_client, run_id="run_ok", verdict="flag")
    assert delivery["state"] == "permitted"
    recipient = gate_client.get(
        f"/api/gate/deliveries/{delivery['delivery_id']}/recipient-image"
    )
    assert recipient.status_code == 200
    assert recipient.content == raw
    detail = gate_client.get("/api/gate/runs/run_ok").json()
    assert detail["access_report"]["unauthorized_served"] == 0
    assert detail["access_report"]["served"] == 1


def test_live_gate_pending_recipient_gets_no_bytes(gate_client):
    delivery, raw = _post_delivery(gate_client, run_id="run_pending")
    recipient = gate_client.get(
        f"/api/gate/deliveries/{delivery['delivery_id']}/recipient-image"
    )
    assert recipient.status_code == 409
    assert "pending" in recipient.json()["detail"]
    assert recipient.content != raw


def test_live_gate_all_sender_routes_accepted(gate_client):
    _clean, encoded = build_geo_pair("height_position")
    for route in ("R-01", "R-02", "R-03", "R-04", "R-05", "R-06", "R-07"):
        created = gate_client.post(
            "/api/gate/deliveries",
            files={"file": ("scene.png", encoded.data, "image/png")},
            data={"run_id": f"run_{route}", "route_id": route},
        )
        assert created.status_code == 200, (route, created.text)
    rejected = gate_client.post(
        "/api/gate/deliveries",
        files={"file": ("scene.png", encoded.data, "image/png")},
        data={"run_id": "run_r08", "route_id": "R-08"},
    )
    assert rejected.status_code == 400


def test_live_gate_run_survives_gate_restart(gate_client, tmp_path, monkeypatch):
    delivery, _raw = _post_delivery(gate_client, run_id="run_restart", verdict="flag")
    # Simulate a container restart: drop the singleton, keep the files.
    main_module._reset_gate_for_tests()
    detail = gate_client.get("/api/gate/runs/run_restart").json()
    assert [d["delivery_id"] for d in detail["deliveries"]] == [delivery["delivery_id"]]
    assert detail["deliveries"][0]["state"] == "permitted"
    assert len(detail["events"]) == 3
    assert (tmp_path / "gate-store" / "gate.sqlite3").exists()


def test_live_gate_sse_replays_timeline(gate_client):
    delivery, _raw = _post_delivery(gate_client, run_id="run_sse", verdict="quarantine")
    with gate_client.stream("GET", "/api/gate/runs/run_sse/events/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                lines.append(line)
            if len(lines) >= 3:
                break
    assert len(lines) == 3
    first = json.loads(lines[0].removeprefix("data: "))
    assert first["event_type"] == "artifact.created"
    assert delivery["delivery_id"]


def test_gate_spa_route_served(gate_client, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    monkeypatch.setattr(main_module, "STATIC_CANDIDATES", [tmp_path])
    page = gate_client.get("/gate")
    assert page.status_code == 200
    assert "<title>spa</title>" in page.text
    # The built page must contain the withheld recipient contract.
    from pathlib import Path

    source = (
        Path(main_module.__file__).parent
        / "frontend"
        / "src"
        / "pages"
        / "LiveGate.tsx"
    ).read_text()
    assert "withheld" in source
    assert "recipient_message" in source
    assert "reviewerImageUrl" in source
