"""CL-60 acceptance tests: Trace explorer view, API and page.

AC1 every delivery in a demo run appears with its content hash,
    verdict reference and parse/next-action link or explicit
    missing status (with an explicit reason per missing link)
AC2 no page element implies causation between an artifact and an
    action (candidates only, `causation_claimed: false` throughout)
Plus: episode context per run, repeated weak signals per sender,
and context never spanning runs.
"""

import json
import os
import tempfile

import pytest

from covertlens import ids
from covertlens.events import Event, EventType, Verdict
from covertlens.fixtures import build_pair
from covertlens.gate import InterceptionContext, InterceptionGate
from covertlens.lsb import analyze_lsb_version
from covertlens.store import ArtifactStore
from covertlens.trace_explorer import (
    build_trace_explorer,
    validate_trace_explorer,
    weak_signals_by_sender,
)

TS = "2026-11-02T12:00:00Z"
RUN = "run_trace"


def _gate_run():
    """Two deliveries: one decided+served, one still pending."""
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN, episode_id="ep_1", sender_id="agent-a")
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    results, deliveries = [], []
    for fixture in (clean, encoded):
        handle = gate.intercept_bytes("R-01", fixture.data, ctx)
        results.append(
            analyze_lsb_version(
                gate.store, handle.artifact_version_id, actor_id="detector"
            )
        )
        deliveries.append(gate.attempt_delivery(handle, recipient_id="agent-b"))
    gate.record_verdict(deliveries[0].delivery_id, Verdict.FLAG)
    gate.recipient_access(deliveries[0].delivery_id)
    return gate, results, deliveries


def _finding(score, family="spatial_lsb"):
    return {
        "family": family,
        "detector_name": "stub",
        "detector_version": "0",
        "score": score,
        "coverage": {},
        "evidence": {},
        "limitations": [],
    }


def test_every_delivery_has_hash_and_link_or_missing_reason():
    gate, results, deliveries = _gate_run()
    view = build_trace_explorer(gate.events(RUN), results)
    assert validate_trace_explorer(view) == []
    assert view["run_id"] == RUN
    assert view["causation_claimed"] is False
    assert len(view["deliveries"]) == 2
    by_id = {d["delivery_id"]: d for d in view["deliveries"]}
    decided, pending = (by_id[d.delivery_id] for d in deliveries)
    for record in view["deliveries"]:
        assert ids.is_content_hash(record["content_hash"])
        assert record["verdict_reference_status"] in ("linked", "missing")
        assert record["parse"]["linkage"] in ("linked", "missing")
        # Every missing link carries its explicit reason.
        assert {r["link"] for r in record["missing_reasons"]} == set(record["missing"])
        assert all(r["reason"] for r in record["missing_reasons"])
    assert decided["verdict_reference_status"] == "linked"
    assert decided["verdict"]["verdict"] == "flag"
    assert decided["delivered"] is True
    # Served, with no parse or action recorded: both explicitly missing.
    assert {r["link"] for r in decided["missing_reasons"]} == {
        "parse_event",
        "next_action",
    }
    assert pending["verdict_reference_status"] == "missing"
    assert pending["parse"]["linkage"] == "missing"
    assert any(r["link"] == "verdict_reference" for r in pending["missing_reasons"])
    json.dumps(view)


def test_action_candidates_never_claim_causation():
    gate, results, deliveries = _gate_run()
    events = list(gate.events(RUN))
    action = Event(
        EventType.RECIPIENT_ACTION,
        RUN,
        len(events),
        TS,
        recipient_id="agent-b",
        delivery_id=deliveries[0].delivery_id,
        payload={"action": "answer"},
    )
    view = build_trace_explorer([*events, action], results)
    assert validate_trace_explorer(view) == []
    assert len(view["actions"]) == 1
    record = view["actions"][0]
    assert record["causation_claimed"] is False
    # The served delivery is a visible candidate input; the pending
    # one (never served) is not presented as an input.
    assert record["candidate_delivery_ids"] == [deliveries[0].delivery_id]
    assert "cause" in record["linkage_basis"]
    decided = next(
        d for d in view["deliveries"] if d["delivery_id"] == deliveries[0].delivery_id
    )
    assert decided["next_actions"][0]["causation_claimed"] is False
    assert decided["next_actions"][0]["linkage"] == "referenced"


def test_episode_context_and_repeated_weak_signals():
    gate, _results, deliveries = _gate_run()
    # Stub-scored results pin both deliveries in the weak band.
    stub_results = [
        {
            "artifact_version_id": d.artifact_version_id,
            "content_hash": d.content_hash,
            "findings": [_finding(0.3)],
        }
        for d in deliveries
    ]
    view = build_trace_explorer(gate.events(RUN), stub_results)
    assert validate_trace_explorer(view) == []
    participants = view["context"]["participants"]
    assert participants["agent-a"]["sent"] == [d.delivery_id for d in deliveries]
    assert participants["agent-b"]["received"] == [d.delivery_id for d in deliveries]
    assert view["context"]["episodes"]["ep_1"]["deliveries"] == [
        d.delivery_id for d in deliveries
    ]
    per_sender = {r["sender_id"]: r for r in view["weak_signals"]["per_sender"]}
    assert per_sender["agent-a"]["weak_signals"] == 2
    assert per_sender["agent-a"]["repeated_weak"] is True
    assert view["weak_signals"]["repeated_senders"] == ["agent-a"]
    assert view["weak_signals"]["label"] == "triage_aid_not_verdict"


def test_weak_band_edges_and_cross_run_refusal():
    context = {
        "deliveries": [
            {
                "sender_id": "s1",
                "delivery_id": "d1",
                "max_score": 0.0,
                "delivered": True,
            },
            {
                "sender_id": "s1",
                "delivery_id": "d2",
                "max_score": 0.74,
                "delivered": True,
            },
            {
                "sender_id": "s1",
                "delivery_id": "d3",
                "max_score": 0.75,
                "delivered": True,
            },
            {
                "sender_id": "s2",
                "delivery_id": "d4",
                "max_score": 0.2,
                "delivered": False,
            },
        ]
    }
    rows = {r["sender_id"]: r for r in weak_signals_by_sender(context)}
    assert rows["s1"]["weak_delivery_ids"] == ["d2"]  # 0 and 0.75 excluded
    assert rows["s1"]["repeated_weak"] is False
    assert rows["s2"]["weak_signals"] == 1

    gate, results, _deliveries = _gate_run()
    other = Event(
        EventType.RECIPIENT_ACTION, "run_other", 99, TS, recipient_id="agent-b"
    )
    with pytest.raises(ValueError, match="across runs"):
        build_trace_explorer([*gate.events(RUN), other], results)


# -- Trace explorer API ----------------------------------------------------

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ.setdefault("COVERTLENS_PRECOMPUTE", "off")
os.environ.setdefault(
    "COVERTLENS_DATA_DIR", tempfile.mkdtemp(prefix="covertlens-trace-test-")
)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from covertlens.geometric_fixtures import build_geo_pair  # noqa: E402


@pytest.fixture()
def trace_client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "GATE_STORE_DIR", tmp_path / "gate-store")
    main_module._reset_gate_for_tests()
    with TestClient(app) as client:
        yield client
    main_module._reset_gate_for_tests()


def _post(client, data, run_id, verdict=None):
    created = client.post(
        "/api/gate/deliveries",
        files={"file": ("scene.png", data, "image/png")},
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
    if verdict is not None:
        decided = client.post(
            f"/api/gate/deliveries/{delivery['delivery_id']}/verdict",
            json={"verdict": verdict},
        )
        assert decided.status_code == 200, decided.text
    return delivery["delivery_id"]


def test_trace_api_covers_every_delivery_with_explicit_missing(trace_client):
    clean, encoded = build_geo_pair("height_position")
    decided_id = _post(trace_client, encoded.data, "run_demo", verdict="quarantine")
    pending_id = _post(trace_client, clean.data, "run_demo")

    response = trace_client.get("/api/trace/runs/run_demo")
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["run_id"] == "run_demo"
    assert view["causation_claimed"] is False
    assert validate_trace_explorer(view) == []
    assert {d["delivery_id"] for d in view["deliveries"]} == {
        decided_id,
        pending_id,
    }
    by_id = {d["delivery_id"]: d for d in view["deliveries"]}
    decided, pending = by_id[decided_id], by_id[pending_id]
    for record in view["deliveries"]:
        assert ids.is_content_hash(record["content_hash"])
        # Every missing link, if any, carries an explicit reason.
        assert {r["link"] for r in record["missing_reasons"]} == set(record["missing"])
    assert pending["missing_reasons"]
    assert decided["verdict_reference_status"] == "linked"
    assert decided["verdict"]["verdict"] == "quarantine"
    assert decided["parse"]["linkage"] == "missing"
    assert pending["verdict_reference_status"] == "missing"
    assert any(r["link"] == "verdict_reference" for r in pending["missing_reasons"])
    # Episode context and weak-signal views are present for the run.
    assert view["context"]["participants"]["agent-a"]["sent"]
    assert view["weak_signals"]["per_sender"][0]["sender_id"] == "agent-a"
    assert view["actions"] == []

    empty = trace_client.get("/api/trace/runs/run_unknown")
    assert empty.status_code == 200
    assert empty.json()["deliveries"] == []
    assert empty.json()["run_id"] == "run_unknown"


def test_trace_spa_route_and_no_causal_wording(trace_client, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    monkeypatch.setattr(main_module, "STATIC_CANDIDATES", [tmp_path])
    page = trace_client.get("/trace")
    assert page.status_code == 200
    assert "<title>spa</title>" in page.text

    from pathlib import Path

    source = (
        Path(main_module.__file__).parent / "frontend" / "src" / "pages" / "Trace.tsx"
    ).read_text()
    assert "causation_claimed: false" in source
    assert "candidate" in source.lower()
    lowered = source.lower()
    for phrase in (
        "caused by",
        "causes the",
        "triggered",
        "led to",
        "due to",
        "resulted in",
        "influenced",
        "because",
    ):
        assert phrase not in lowered, phrase
