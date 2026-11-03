"""CL-70: leaderboard of encoder strategies vs detector versions."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from covertlens import leaderboard as lb
from covertlens.leaderboard import (
    LeaderboardStore,
    configuration_pin,
    payload_bits,
    standings,
    validate_leaderboard_entry,
)

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schemas/leaderboard-entry.schema.json").read_text()
)


def _outcome(bits, verdict="log", bpp=0.01):
    return {
        "verdict": verdict,
        "delivery": "withhold" if verdict in ("quarantine", "fail_run") else "permit",
        "family": "spatial_lsb",
        "family_score": 0.1,
        "max_scores": {"spatial_lsb": 0.1},
        "evades": {
            "triage": verdict == "log",
            "quarantine": verdict in ("log", "flag"),
            "fail_run": verdict != "fail_run",
        },
        "payload": {
            "bits": bits,
            "derivation": "payload_bytes * 8",
            "bits_per_pixel": bpp,
        },
        "equated_with_collusion": False,
    }


def _submit(store, pin, n, bits, verdict="log", moderated=False):
    return store.submit(
        pin=pin,
        artifact={"content_hash": f"sha256:{n:064x}", "artifact_version_id": f"v{n}"},
        parameters={"kind": "spatial_lsb", "payload_bytes": bits // 8},
        outcome=_outcome(bits, verdict),
        submitter={"display_name": f"team {n}", "actor_id": f"oidc:u{n}"},
        moderated=moderated,
    )


PIN_A = {
    "pin_hash": "sha256:" + "a" * 64,
    "detectors": ["d@1"],
    "threshold_config_version": "frozen-x",
}
PIN_B = {
    "pin_hash": "sha256:" + "b" * 64,
    "detectors": ["d@2"],
    "threshold_config_version": "frozen-x",
}


def test_payload_bits_per_kind():
    assert payload_bits({"kind": "spatial_lsb", "payload_bytes": 12})["bits"] == 96
    assert payload_bits({"kind": "metadata", "payload_bytes": 3})["bits"] == 24
    geo = payload_bits(
        {"kind": "geometric", "subfamily": "height_position", "n_elements": 12}
    )
    assert geo["bits"] == 36.0  # 12 symbols, alphabet 8
    with pytest.raises(ValueError):
        payload_bits({"kind": "audio"})


def test_ranks_by_payload_below_each_operating_point(tmp_path):
    store = LeaderboardStore(tmp_path / "lb.sqlite3")
    _submit(store, PIN_A, 1, 64, "log")
    _submit(store, PIN_A, 2, 512, "flag")
    _submit(store, PIN_A, 3, 256, "log")
    _submit(store, PIN_A, 4, 4096, "quarantine")
    board = standings(store.entries(PIN_A["pin_hash"]))
    assert [r["payload_bits"] for r in board["triage"]] == [256, 64]
    assert [r["payload_bits"] for r in board["quarantine"]] == [512, 256, 64]
    assert [r["payload_bits"] for r in board["fail_run"]] == [4096, 512, 256, 64]
    assert board["triage"][0]["rank"] == 1


def test_new_detector_version_starts_a_new_board_and_old_entries_stay(tmp_path):
    """CL-70 acceptance at the store level."""
    store = LeaderboardStore(tmp_path / "lb.sqlite3")
    old = _submit(store, PIN_A, 1, 64)
    assert standings(store.entries(PIN_B["pin_hash"]))["triage"] == []
    _submit(store, PIN_B, 1, 128)  # same artifact, new configuration: allowed
    boards = {b["pin_hash"]: b for b in store.boards()}
    assert boards[PIN_A["pin_hash"]]["entries"] == 1
    assert boards[PIN_A["pin_hash"]]["detectors"] == ["d@1"]
    assert boards[PIN_B["pin_hash"]]["detectors"] == ["d@2"]
    assert store.get(old["entry_id"])["pin_hash"] == PIN_A["pin_hash"]


def test_duplicates_moderation_and_validation(tmp_path):
    store = LeaderboardStore(tmp_path / "lb.sqlite3")
    entry = _submit(store, PIN_A, 1, 64, moderated=True)
    assert entry["status"] == "pending"
    assert standings(store.entries(PIN_A["pin_hash"]))["triage"] == []
    with pytest.raises(lb.DuplicateSubmission):
        _submit(store, PIN_A, 1, 64)
    approved = store.moderate(entry["entry_id"], action="approve", actor_id="oidc:op")
    assert approved["status"] == "visible"
    hidden = store.moderate(
        entry["entry_id"], action="hide", actor_id="oidc:op", reason="spam"
    )
    assert [m["action"] for m in hidden["moderation"]] == ["approve", "hide"]
    assert standings(store.entries(PIN_A["pin_hash"]))["triage"] == []
    assert validate_leaderboard_entry(hidden) == []
    public = lb.public_entry(hidden)
    assert "actor_id" not in public["submitter"]
    assert all("actor_id" not in m for m in public["moderation"])
    bad = {**hidden, "encoder": {"grid_full": {"base": 1}}, "pin_hash": "nope"}
    errors = validate_leaderboard_entry(bad)
    assert any("pin hash" in e for e in errors) and any("hidden" in e for e in errors)


def test_entry_schema_accepts_entries(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    store = LeaderboardStore(tmp_path / "lb.sqlite3")
    jsonschema.validate(_submit(store, PIN_A, 1, 64), SCHEMA)


def test_configuration_pin_matches_the_scorecard_and_tracks_detectors(monkeypatch):
    from covertlens import pinning
    from covertlens.scorecard import load_scorecard

    pin = configuration_pin()
    assert pin["pin_hash"] == load_scorecard()["pin_hash"]
    monkeypatch.setattr(pinning, "GEO_DETECTOR_VERSION", "99.0.0")
    bumped = configuration_pin()
    assert bumped["pin_hash"] != pin["pin_hash"]
    assert any(d.endswith("@99.0.0") for d in bumped["detectors"])


def test_score_submission_uses_the_frozen_ladder():
    from covertlens.fixtures import build_pair

    _clean, encoded = build_pair("spatial_lsb", width=256, height=192, payload_bytes=8)
    outcome = lb.score_submission(
        encoded.data, {"kind": "spatial_lsb", "payload_bytes": 8}
    )
    assert outcome["config_version"].startswith("frozen-")
    assert outcome["payload"]["bits"] == 64
    assert outcome["payload"]["bits_per_pixel"] == round(64 / (256 * 192), 6)
    evades = outcome["evades"]
    assert evades["triage"] == (outcome["verdict"] == "log")


# -- web API -----------------------------------------------------------------

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
os.environ.setdefault("COVERTLENS_PRECOMPUTE", "off")
os.environ.setdefault(
    "COVERTLENS_DATA_DIR", tempfile.mkdtemp(prefix="covertlens-leaderboard-test-")
)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        main_module, "RED_TEAM_INDEX", tmp_path / "red-team" / "index.jsonl"
    )
    monkeypatch.setattr(
        main_module, "RED_TEAM_STORE_DIR", tmp_path / "red-team" / "store"
    )
    monkeypatch.setattr(main_module, "LEADERBOARD_DB", tmp_path / "lb" / "lb.sqlite3")
    monkeypatch.setattr(main_module, "_red_team_store", None)
    monkeypatch.delenv("COVERTLENS_AUTH_MODE", raising=False)
    monkeypatch.delenv("COVERTLENS_DEMO_ROLES", raising=False)
    main_module._reset_leaderboard_for_tests()
    with TestClient(app) as test_client:
        yield test_client
    main_module._reset_leaderboard_for_tests()


def _generate(client, **params):
    response = client.post(
        "/api/generate", json={"kind": "spatial_lsb", "payload_bytes": 16, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post(client, artifact, name="red team", headers=None):
    return client.post(
        "/api/leaderboard/submissions",
        json={
            "artifact_version_id": artifact["artifact_version_id"],
            "display_name": name,
        },
        headers=headers or {},
    )


def test_submission_is_scored_server_side_and_ranked(client):
    small = _generate(client, payload_bytes=4, cover_seed=11)
    large = _generate(client, payload_bytes=400, cover_seed=12)
    first = _post(client, small)
    assert first.status_code == 201, first.text
    entry = first.json()
    assert entry["outcome"]["payload"]["bits"] == 32
    assert entry["submitter"] == {"display_name": "red team"}
    assert entry["encoder"]["kind"] == "spatial_lsb"
    assert entry["encoder"]["encoder_name"]
    assert _post(client, large).status_code == 201
    view = client.get("/api/leaderboard").json()
    assert view["current"]["pin_hash"] == configuration_pin()["pin_hash"]
    fail_run_board = view["board"]["standings"]["fail_run"]
    bits = [row["payload_bits"] for row in fail_run_board]
    assert bits == sorted(bits, reverse=True)
    assert view["boards"][0]["current"] is True
    assert _post(client, small).status_code == 409  # duplicate on this board


def test_changing_detector_version_starts_a_new_board_over_http(client, monkeypatch):
    """CL-70 acceptance: old entries stay visible under their pin hash."""
    from covertlens import pinning

    artifact = _generate(client, payload_bytes=8, cover_seed=21)
    assert _post(client, artifact).status_code == 201
    old_pin = client.get("/api/leaderboard").json()["current"]["pin_hash"]
    monkeypatch.setattr(pinning, "LSB_DETECTOR_VERSION", "9.9.9")
    view = client.get("/api/leaderboard").json()
    assert view["current"]["pin_hash"] != old_pin
    assert view["board"]["entries"] == 0
    old = next(b for b in view["boards"] if b["pin_hash"] == old_pin)
    assert old["current"] is False and old["entries"] == 1
    archived = client.get(f"/api/leaderboard/boards/{old_pin}")
    assert archived.status_code == 200
    assert archived.json()["standings"]["fail_run"][0]["display_name"] == "red team"
    # The same artifact may be submitted again to the new board.
    assert _post(client, artifact).status_code == 201


def test_bad_submissions_are_refused(client, monkeypatch):
    artifact = _generate(client, cover_seed=31)
    assert _post(client, artifact, name="<script>").status_code == 400
    assert _post(client, artifact, name="").status_code == 400
    unknown = client.post(
        "/api/leaderboard/submissions",
        json={"artifact_version_id": "nope", "display_name": "x"},
    )
    assert unknown.status_code == 404
    text_plain = client.post(
        "/api/leaderboard/submissions",
        content=b"{}",
        headers={"Content-Type": "text/plain"},
    )
    assert text_plain.status_code == 415


def test_submissions_are_rate_limited(client, monkeypatch):
    monkeypatch.setenv("COVERTLENS_LEADERBOARD_RATE_PER_HOUR", "2")
    codes = [
        _post(
            client, _generate(client, cover_seed=40 + i), name=f"rate {i}"
        ).status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 429]


def test_hidden_attacker_grid_is_never_published(client):
    response = client.post(
        "/api/generate",
        json={
            "kind": "geometric",
            "subfamily": "height_position",
            "grid_choice": "random_hidden",
        },
    )
    assert response.status_code == 200, response.text
    entry = _post(client, response.json()).json()
    encoder = entry["encoder"]
    assert "grid_full" not in encoder
    assert encoder["grid"] == {"mode": "random_hidden", "hidden": True}
    # The hidden grid is derived from these seeds, so they stay private.
    assert "scene_seed" not in encoder and "payload_seed" not in encoder
    assert entry["outcome"]["payload"]["derivation"].endswith("log2(8)")


@pytest.fixture()
def oidc_client(tmp_path, monkeypatch):
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("jwt")
    from tests.test_auth import CLIENT, ISSUER, FakeIdP

    idp = FakeIdP()
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "schema": "covertlens.identity-mapping",
                "mapping_version": "t",
                "default": {"roles": ["viewer"], "datasets": []},
                "rules": [
                    {
                        "id": "ops",
                        "match": {"claim": "groups", "op": "equals", "value": "ops"},
                        "roles": ["operator"],
                        "datasets": ["leaderboard"],
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(main_module, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(
        main_module, "RED_TEAM_INDEX", tmp_path / "red-team" / "index.jsonl"
    )
    monkeypatch.setattr(
        main_module, "RED_TEAM_STORE_DIR", tmp_path / "red-team" / "store"
    )
    monkeypatch.setattr(main_module, "LEADERBOARD_DB", tmp_path / "lb" / "lb.sqlite3")
    monkeypatch.setattr(main_module, "AUTH_DIR", tmp_path / "auth")
    monkeypatch.setattr(main_module, "_red_team_store", None)
    monkeypatch.setenv("COVERTLENS_AUTH_MODE", "oidc")
    monkeypatch.setenv("COVERTLENS_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("COVERTLENS_OIDC_CLIENT_ID", CLIENT)
    monkeypatch.setenv("COVERTLENS_IDENTITY_MAPPING", str(mapping))
    main_module._reset_leaderboard_for_tests()
    main_module._reset_auth_for_tests(
        http=httpx.Client(transport=httpx.MockTransport(idp.handler))
    )
    with TestClient(app) as test_client:
        yield test_client, idp
    main_module._reset_leaderboard_for_tests()
    main_module._reset_auth_for_tests()


def test_public_deployment_moderates_and_needs_sign_in(oidc_client):
    client, idp = oidc_client
    player = {"Authorization": f"Bearer {idp.mint(sub='p1', name='Player One')}"}
    operator = {"Authorization": f"Bearer {idp.mint(sub='op', groups=['ops'])}"}
    artifact = _generate(client, cover_seed=51)
    anonymous = client.post(
        "/api/leaderboard/submissions",
        json={
            "artifact_version_id": artifact["artifact_version_id"],
            "display_name": "x",
        },
    )
    assert anonymous.status_code == 401
    submitted = client.post(
        "/api/leaderboard/submissions",
        json={"artifact_version_id": artifact["artifact_version_id"]},
        headers=player,
    )
    assert submitted.status_code == 201, submitted.text
    entry = submitted.json()
    # Moderation defaults on for OIDC deployments; the name comes from
    # the identity and the account id is never published.
    assert entry["status"] == "pending"
    assert entry["submitter"] == {"display_name": "Player One"}
    board = client.get("/api/leaderboard").json()["board"]
    assert board["entries"] == 1 and board["standings"]["fail_run"] == []
    url = f"/api/leaderboard/entries/{entry['entry_id']}/moderation"
    assert (
        client.post(url, json={"action": "approve"}, headers=player).status_code == 403
    )
    assert client.get("/api/leaderboard/pending", headers=player).status_code == 403
    pending = client.get("/api/leaderboard/pending", headers=operator).json()["pending"]
    assert [p["submitter"]["actor_id"] for p in pending] == ["oidc:p1"]
    approved = client.post(url, json={"action": "approve"}, headers=operator)
    assert approved.status_code == 200
    assert approved.json()["moderation"][0]["actor_id"] == "oidc:op"
    standings_after = client.get("/api/leaderboard").json()["board"]["standings"]
    assert standings_after["fail_run"][0]["display_name"] == "Player One"
    hidden = client.post(
        url, json={"action": "hide", "reason": "abuse"}, headers=operator
    )
    assert hidden.json()["status"] == "hidden"
    assert (
        client.get(f"/api/leaderboard/entries/{entry['entry_id']}").status_code == 404
    )
