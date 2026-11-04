"""The interactive demo must measure recovery from bytes and respect blocking."""

import json

import pytest

from app.agent_demo import AgentDemo
from app.demo_scene import READING_INSTRUCTIONS, render_scene, validate_message
from covertlens.gate import InterceptionGate
from covertlens.second_opinion import ProviderResponse
from covertlens.segmentation import segment_image
from covertlens.store import ArtifactStore


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("COVERTLENS_AGENT_DEMO_API_KEY", "offline-test-key")
    gate = InterceptionGate(ArtifactStore(tmp_path / "gate"))
    service = AgentDemo(tmp_path / "demos", gate)
    calls = []

    def complete(self, prompt, *, images=None):
        calls.append((prompt, images))
        text = (
            {"message": "HELLO WORLD"}
            if images
            else {"message": "HELLO WORLD", "palette": "blue"}
        )
        return ProviderResponse(text=json.dumps(text), model="offline-agent")

    monkeypatch.setattr("app.agent_demo.HttpProvider.complete", complete)
    return service, calls


@pytest.mark.parametrize("scene", ["house", "garden", "night_sky", "skyline"])
@pytest.mark.parametrize("message", ["HI ALL", "HELLO WORLD", "ABCDEFGH IJKLMNOP"])
def test_entire_two_word_message_is_recoverable_from_each_scene(scene, message):
    image = render_scene(scene, message, "blue")
    elements = [e for e in segment_image(image).elements if e["top"] >= 200]
    digits = [round((element["height"] - 16) / 10) for element in elements]
    assert len(digits) == len(message) * 3
    recovered = "".join(
        chr(int("".join(str(d) for d in digits[i : i + 3]), 8))
        for i in range(0, len(digits), 3)
    )
    assert recovered == message


def test_block_never_calls_receiver_and_survives_reload(demo):
    service, calls = demo
    created = service.create("house", "HELLO WORLD")
    assert "message" not in created
    blocked = service.decide(created["id"], "block")
    assert blocked["state"] == "blocked"
    assert blocked["recovery"] == "not_observed"
    assert len(calls) == 1
    reloaded = AgentDemo(service.directory, service.gate)
    assert reloaded.decide(created["id"], "send")["state"] == "blocked"
    assert len(calls) == 1
    assert service.gate.get_delivery(created["delivery_id"]).state == "withheld"


def test_send_requires_completed_permitting_analysis(demo, monkeypatch):
    service, calls = demo
    created = service.create("garden", "HELLO WORLD")
    with pytest.raises(ValueError, match="not cleared"):
        service.decide(created["id"], "send")
    monkeypatch.setattr(
        "app.agent_demo.analyze_bytes",
        lambda data: {
            "status": "parsed",
            "decision": {"delivery": "withhold", "verdict": "quarantine"},
        },
    )
    service.analyze(created["id"])
    with pytest.raises(ValueError, match="not cleared"):
        service.decide(created["id"], "send")
    assert len(calls) == 1


def allow_analysis(monkeypatch):
    monkeypatch.setattr(
        "app.agent_demo.analyze_bytes",
        lambda data: {
            "status": "parsed",
            "decision": {"delivery": "permit", "verdict": "log"},
        },
    )


def test_receiver_only_gets_gate_served_image_and_shared_instructions(
    demo, monkeypatch
):
    service, calls = demo
    allow_analysis(monkeypatch)
    created = service.create("skyline", "HELLO WORLD")
    service.analyze(created["id"])
    result = service.decide(created["id"], "send")
    assert result["state"] == "sent"
    assert result["recovery"] == "recovered"
    assert calls[1][0] == READING_INSTRUCTIONS
    assert "HELLO WORLD" not in calls[1][0]
    assert calls[1][1] == [service._path(created["id"], ".png").read_bytes()]
    assert service.decide(created["id"], "send") == result
    assert len(calls) == 2
    assert service.gate.access_attempt_report()["unauthorized_served"] == 0


def test_wrong_answer_is_shown_and_scored_as_not_recovered(demo, monkeypatch):
    service, _ = demo
    allow_analysis(monkeypatch)
    created = service.create("house", "HELLO WORLD")
    service.analyze(created["id"])
    monkeypatch.setattr(
        "app.agent_demo.HttpProvider.complete",
        lambda *a, **kw: ProviderResponse(
            text='{"message":"WRONG ANSWER"}',
            model="offline-receiver",
        ),
    )
    result = service.decide(created["id"], "send")
    assert result["recovery"] == "not_recovered"
    assert result["receiver"]["message"] == "WRONG ANSWER"


def test_failed_receiver_is_not_replayed_on_duplicate_click(demo, monkeypatch):
    service, _ = demo
    allow_analysis(monkeypatch)
    created = service.create("house", "HELLO WORLD")
    service.analyze(created["id"])

    def unavailable(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("app.agent_demo.HttpProvider.complete", unavailable)
    failed = service.decide(created["id"], "send")
    assert failed["receiver_error"]["code"] == "receiver_unavailable"
    result = service.decide(created["id"], "send")
    assert result["state"] == "receiver_failed"
    assert result["recovery"] == "unknown"


@pytest.mark.parametrize(
    "message",
    [None, "one", "three word message", "123 test", "toolongword hi", "CAFÉ TEST"],
)
def test_two_word_input_validation(message):
    with pytest.raises(ValueError):
        validate_message(message)


def test_demo_api_requires_permission_and_hides_message(demo, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    service, calls = demo
    monkeypatch.setenv("COVERTLENS_DATA_DIR", str(service.directory.parent))
    from app import main

    monkeypatch.setenv("COVERTLENS_PRECOMPUTE", "off")
    monkeypatch.setenv("COVERTLENS_DEMO_BUILD", "on")
    monkeypatch.setenv("COVERTLENS_DEMO_ROLES", "on")
    monkeypatch.setattr(main, "_agent_demo", lambda: service)
    monkeypatch.setattr(main, "_rate_windows", {})
    with TestClient(main.app) as client:
        assert (
            client.post("/api/agent-demo", json={"message": "HELLO WORLD"}).status_code
            == 403
        )
        headers = {"X-Demo-Role": "researcher"}
        response = client.post(
            "/api/agent-demo",
            json={"scene": "house", "message": "HELLO WORLD"},
            headers=headers,
        )
        assert response.status_code == 200
        record = response.json()
        assert "HELLO WORLD" not in response.text
        path = "/api/agent-demo/" + record["id"]
        assert client.post(path + "/show", json={}).status_code == 403
        assert (
            client.post(path + "/show", json={}, headers=headers).json()["message"]
            == "HELLO WORLD"
        )
        assert (
            client.post(path + "/block", json={}, headers=headers).json()["state"]
            == "blocked"
        )
        assert (
            client.post(path + "/send", json={}, headers=headers).json()["recovery"]
            == "not_observed"
        )
        assert len(calls) == 1
        # Exercise the normal HTTP sequence against the real detector.
        fresh = client.post(
            "/api/agent-demo",
            json={"scene": "house", "message": "HELLO WORLD"},
            headers=headers,
        ).json()
        next_path = "/api/agent-demo/" + fresh["id"]
        checked = client.post(next_path + "/analyze", json={}, headers=headers)
        assert checked.status_code == 200
        assert checked.json()["analysis"]["decision"]["delivery"] == "permit"
        sent = client.post(next_path + "/send", json={}, headers=headers)
        assert sent.status_code == 200
        assert sent.json()["recovery"] == "recovered"
        assert calls[-1][0] == READING_INSTRUCTIONS


def test_changed_preview_cannot_be_analyzed_as_the_gated_original(demo):
    service, _ = demo
    created = service.create("house", "HELLO WORLD")
    service._path(created["id"], ".png").write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="saved picture has changed"):
        service.analyze(created["id"])


def test_interrupted_block_is_reconciled_from_the_persistent_gate(demo):
    from covertlens.events import Verdict

    service, calls = demo
    created = service.create("house", "HELLO WORLD")
    # Simulate a stop after writing the gate verdict but before saving demo state.
    service.gate.record_verdict(created["delivery_id"], Verdict.QUARANTINE)
    assert service.load(created["id"])["state"] == "blocked"
    assert service.decide(created["id"], "send")["state"] == "blocked"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "reply",
    [
        '{"message":"HELLO WORLD"}',
        '```json\n{"message":"HELLO WORLD"}\n```',
        '```\n{"message":"HELLO WORLD"}\n```',
    ],
)
def test_receiver_accepts_plain_and_fenced_json(demo, monkeypatch, reply):
    service, _ = demo
    allow_analysis(monkeypatch)
    created = service.create("house", "HELLO WORLD")
    service.analyze(created["id"])
    monkeypatch.setattr(
        "app.agent_demo.HttpProvider.complete",
        lambda *args, **kwargs: ProviderResponse(text=reply, model="stub"),
    )
    assert service.decide(created["id"], "send")["recovery"] == "recovered"


@pytest.mark.parametrize(
    "reply,finish,code",
    [
        ("", "length", "reply_limit"),
        ('{"message":"HELLO WORLD"}', "length", "reply_limit"),
        ("not JSON", "stop", "reply_format"),
        ("{}", "stop", "reply_format"),
        ("", "content_filter", "reply_declined"),
    ],
)
def test_receiver_failure_is_a_saved_result_instead_of_reload_error(
    demo, monkeypatch, reply, finish, code
):
    service, _ = demo
    allow_analysis(monkeypatch)
    created = service.create("house", "HELLO WORLD")
    service.analyze(created["id"])
    monkeypatch.setattr(
        "app.agent_demo.HttpProvider.complete",
        lambda *args, **kwargs: ProviderResponse(
            text=reply,
            model="stub",
            finish_reason=finish,
            request_id="req-diagnostic",
        ),
    )
    result = service.decide(created["id"], "send")
    assert result["state"] == "receiver_failed"
    assert result["receiver_error"]["code"] == code
    assert result["receiver"]["request_id"] == "req-diagnostic"
    assert result["recovery"] == "unknown"
    assert service.load(created["id"])["receiver_error"] == result["receiver_error"]


def test_retry_preserves_delivery_and_deduplicates_failed_attempt(demo, monkeypatch):
    service, calls = demo
    allow_analysis(monkeypatch)
    created = service.create("house", "HELLO WORLD")
    service.analyze(created["id"])
    attempts = []

    def unavailable(*args, **kwargs):
        attempts.append(1)
        raise TimeoutError("private-data-that-must-not-leak")

    monkeypatch.setattr("app.agent_demo.HttpProvider.complete", unavailable)
    failed = service.decide(created["id"], "send")
    assert failed["receiver_attempt"] == 1
    assert "private-data" not in json.dumps(failed)
    retried = service.retry_receiver(created["id"], 1)
    assert retried["receiver_attempt"] == 2
    service.retry_receiver(created["id"], 1)
    assert len(attempts) == 2
    monkeypatch.setattr(
        "app.agent_demo.HttpProvider.complete",
        lambda *args, **kwargs: ProviderResponse(
            text='{"message":"HELLO WORLD"}', model="stub"
        ),
    )
    recovered = service.retry_receiver(created["id"], 2)
    assert recovered["recovery"] == "recovered"
    assert recovered["delivery_id"] == created["delivery_id"]
    assert len(calls) == 1
    assert service.gate.get_delivery(created["delivery_id"]).state == "permitted"


def test_older_failed_demo_without_attempt_count_can_retry_once(demo, monkeypatch):
    service, _ = demo
    allow_analysis(monkeypatch)
    created = service.create("house", "HELLO WORLD")
    service.analyze(created["id"])
    record = service.load(created["id"])
    from covertlens.events import Verdict

    service.gate.record_verdict(created["delivery_id"], Verdict.LOG)
    record["state"] = "receiver_failed"
    service.save(record)

    def unavailable(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("app.agent_demo.HttpProvider.complete", unavailable)
    retried = service.retry_receiver(created["id"], 1)
    assert retried["receiver_attempt"] == 2
    assert service.retry_receiver(created["id"], 1)["receiver_attempt"] == 2


def test_retry_does_not_release_a_blocked_image(demo):
    service, calls = demo
    created = service.create("house", "HELLO WORLD")
    service.decide(created["id"], "block")
    assert service.retry_receiver(created["id"], 1)["state"] == "blocked"
    assert len(calls) == 1


def test_api_returns_receiver_failure_and_allows_explicit_retry(demo, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app import main
    from covertlens.second_opinion import ProviderRequestError

    service, _ = demo
    allow_analysis(monkeypatch)
    monkeypatch.setenv("COVERTLENS_PRECOMPUTE", "off")
    monkeypatch.setenv("COVERTLENS_DEMO_BUILD", "on")
    monkeypatch.setenv("COVERTLENS_DEMO_ROLES", "on")
    monkeypatch.setattr(main, "_agent_demo", lambda: service)
    monkeypatch.setattr(main, "_rate_windows", {})
    with TestClient(main.app) as client:
        headers = {"X-Demo-Role": "researcher"}
        created = client.post(
            "/api/agent-demo",
            json={"scene": "house", "message": "HELLO WORLD"},
            headers=headers,
        ).json()
        path = "/api/agent-demo/" + created["id"]
        assert (
            client.post(path + "/analyze", json={}, headers=headers).status_code == 200
        )

        def rejected(*args, **kwargs):
            raise ProviderRequestError(
                "api_rejected", "The agent API rejected the request (HTTP 400).", 400
            )

        monkeypatch.setattr("app.agent_demo.HttpProvider.complete", rejected)
        sent = client.post(path + "/send", json={}, headers=headers)
        assert sent.status_code == 200
        assert sent.json()["state"] == "receiver_failed"
        assert sent.json()["receiver_error"]["http_status"] == 400
        assert "Reload the demo" not in sent.text
        assert client.post(path + "/retry", json={}, headers=headers).status_code == 400
        retry = client.post(path + "/retry", json={"attempt": 1}, headers=headers)
        assert retry.status_code == 200
        assert retry.json()["receiver_attempt"] == 2
        duplicate = client.post(path + "/retry", json={"attempt": 1}, headers=headers)
        assert duplicate.json()["receiver_attempt"] == 2
