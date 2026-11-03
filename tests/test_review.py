"""CL-59 acceptance tests: demo roles, reviewer page API, sealed exports.

AC1 a researcher-role request for a candidate decode is denied and
    appears in the audit chain
AC2 after a full demo session the audit chain verifies
AC3 a downloaded package passes `validate_review_package`
Plus: candidate text is stripped from every non-decode response,
viewer holds no evidence permissions, and review state survives a
workspace restart with the chain intact.
"""

import json
import os
import tempfile

import pytest

from covertlens.review import ReviewWorkspace, demo_principal
from covertlens.runtime import can, load_runtime_policy
from covertlens.store import ArtifactStore

POLICY = load_runtime_policy()
RUN = "run_review"


def test_demo_role_mapping_to_principals():
    viewer = demo_principal("viewer", RUN)
    researcher = demo_principal("researcher", RUN)
    reviewer = demo_principal("reviewer", RUN)
    assert viewer.actor_id == "demo-viewer"
    assert researcher.actor_id == "demo-researcher"
    assert reviewer.actor_id == "demo-reviewer"
    # Viewer holds no evidence permissions (deny-by-default).
    for permission in POLICY["permissions"]:
        assert not can(POLICY, viewer, RUN, permission), permission
    # Candidate decodes are reviewer-only; exports are researcher-only.
    assert not can(POLICY, researcher, RUN, "candidate.decode.read")
    assert can(POLICY, reviewer, RUN, "candidate.decode.read")
    assert can(POLICY, researcher, RUN, "export.create")
    assert not can(POLICY, reviewer, RUN, "export.create")
    # Grants are dataset-scoped: the same role elsewhere gets nothing.
    assert not can(POLICY, reviewer, "run_other", "candidate.decode.read")
    with pytest.raises(ValueError, match="demo role"):
        demo_principal("admin", RUN)


def test_workspace_state_survives_reopen_with_chain_intact(tmp_path):
    from covertlens.geo_benchmark import build_structured_pair
    from covertlens.geometric import analyze_geometric_bytes

    _clean, encoded = build_structured_pair("height_position", 0)
    candidate = analyze_geometric_bytes(encoded.data)["candidate_decode"]
    assert candidate is not None
    store = ArtifactStore(tmp_path / "store")
    db_path = tmp_path / "review.sqlite3"
    workspace = ReviewWorkspace(store, db_path=db_path)
    decode_id = workspace.record_candidate_decode(RUN, "ver_structured", candidate)
    assert decode_id is not None
    workspace.apply_disposition(
        demo_principal("reviewer", RUN),
        RUN,
        "del_structured",
        disposition="suspected",
        note="structured heights",
    )
    assert workspace.audit.verify_chain() is True

    reopened = ReviewWorkspace(ArtifactStore(tmp_path / "store"), db_path=db_path)
    assert reopened.audit.verify_chain() is True
    assert reopened.disposition(RUN, "del_structured") == "suspected"
    decode = reopened.read_candidate_decode(
        demo_principal("reviewer", RUN), RUN, decode_id
    )
    assert decode["text"] == candidate["text"]


# -- Reviewer API --------------------------------------------------------

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ.setdefault("COVERTLENS_PRECOMPUTE", "off")
os.environ.setdefault(
    "COVERTLENS_DATA_DIR", tempfile.mkdtemp(prefix="covertlens-review-test-")
)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from covertlens.geo_benchmark import build_structured_pair  # noqa: E402
from covertlens.review import DISPOSITIONS  # noqa: E402,F401  (re-export check)
from covertlens.review_export import validate_review_package  # noqa: E402

REVIEWER = {"X-Demo-Role": "reviewer"}
RESEARCHER = {"X-Demo-Role": "researcher"}
VIEWER = {"X-Demo-Role": "viewer"}


@pytest.fixture()
def review_client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "GATE_STORE_DIR", tmp_path / "gate-store")
    main_module._reset_gate_for_tests()
    with TestClient(app) as client:
        yield client
    main_module._reset_gate_for_tests()


def _quarantined_delivery(client, run_id=RUN):
    _clean, encoded = build_structured_pair("height_position", 0)
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
    decided = client.post(
        f"/api/gate/deliveries/{delivery['delivery_id']}/verdict",
        json={"verdict": "quarantine"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["state"] == "withheld"
    return delivery["delivery_id"], encoded.data


def test_roles_endpoint_labels_demo_roles(review_client):
    body = review_client.get("/api/review/roles").json()
    assert [r["role"] for r in body["roles"]] == ["viewer", "researcher", "reviewer"]
    assert all("demo role" in r["label"] for r in body["roles"])
    by_role = {r["role"]: r["permissions"] for r in body["roles"]}
    assert by_role["viewer"] == []
    assert "candidate.decode.read" not in by_role["researcher"]
    assert "candidate.decode.read" in by_role["reviewer"]
    bad = review_client.get(
        "/api/review/runs/run_review/queue", headers={"X-Demo-Role": "admin"}
    )
    assert bad.status_code == 400


def test_researcher_decode_denied_and_audited(review_client):
    delivery_id, _raw = _quarantined_delivery(review_client)

    queue = review_client.get(f"/api/review/runs/{RUN}/queue", headers=REVIEWER)
    assert queue.status_code == 200
    row = queue.json()["quarantined"][0]
    assert row["delivery_id"] == delivery_id
    assert row["has_candidate_decode"] is True
    assert row["disposition"] == "unresolved"

    # Reviewer can read the candidate decode (the only text path).
    allowed = review_client.get(
        f"/api/review/deliveries/{delivery_id}/candidate-decode", headers=REVIEWER
    )
    assert allowed.status_code == 200, allowed.text
    candidate_text = allowed.json()["text"]
    assert candidate_text

    # AC1: researcher is denied, and the denial is in the audit chain.
    denied = review_client.get(
        f"/api/review/deliveries/{delivery_id}/candidate-decode", headers=RESEARCHER
    )
    assert denied.status_code == 403
    assert candidate_text not in denied.text
    denied_viewer = review_client.get(
        f"/api/review/deliveries/{delivery_id}/candidate-decode", headers=VIEWER
    )
    assert denied_viewer.status_code == 403

    # The text never leaks through queue or detail responses, and
    # no response carries a candidate_decode payload (metadata keys
    # like has_candidate_decode/decode_id are identifiers, not text).
    def _keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(_keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(_keys(v) for v in value)) if value else set()
        return set()

    for headers in (REVIEWER, RESEARCHER, VIEWER):
        detail = review_client.get(
            f"/api/review/deliveries/{delivery_id}", headers=headers
        )
        assert detail.status_code == 200
        assert candidate_text not in detail.text
        assert "candidate_decode" not in _keys(detail.json())
        assert candidate_text not in json.dumps(detail.json())

    audit = review_client.get("/api/review/audit", params={"run_id": RUN}).json()
    assert audit["chain_valid"] is True
    denials = [
        e
        for e in audit["entries"]
        if e["action"] == "candidate_decode.read" and e["outcome"] == "denied"
    ]
    assert {e["actor_id"] for e in denials} == {"demo-researcher", "demo-viewer"}
    assert candidate_text not in json.dumps(audit)


def test_original_bytes_follow_role_permissions(review_client):
    delivery_id, raw = _quarantined_delivery(review_client)
    denied = review_client.get(
        f"/api/review/deliveries/{delivery_id}/original", headers=VIEWER
    )
    assert denied.status_code == 403
    assert denied.content != raw
    for headers in (RESEARCHER, REVIEWER):
        served = review_client.get(
            f"/api/review/deliveries/{delivery_id}/original", headers=headers
        )
        assert served.status_code == 200
        assert served.content == raw


def test_disposition_workflow_and_validation(review_client):
    delivery_id, _raw = _quarantined_delivery(review_client)
    url = f"/api/review/deliveries/{delivery_id}/disposition"

    viewer_attempt = review_client.post(
        url, json={"disposition": "benign"}, headers=VIEWER
    )
    assert viewer_attempt.status_code == 403

    unknown = review_client.post(url, json={"disposition": "guilty"}, headers=REVIEWER)
    assert unknown.status_code == 400

    needs_basis = review_client.post(
        url, json={"disposition": "demonstrated_transfer"}, headers=REVIEWER
    )
    assert needs_basis.status_code == 400
    assert "basis" in needs_basis.json()["detail"]

    applied = review_client.post(
        url,
        json={
            "disposition": "demonstrated_transfer",
            "note": "receiver reproduced the word",
            "demonstrated_basis": "independent decode plus receiver action log",
        },
        headers=REVIEWER,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["disposition"] == "demonstrated_transfer"

    queue = review_client.get(f"/api/review/runs/{RUN}/queue", headers=VIEWER)
    row = queue.json()["quarantined"][0]
    assert row["disposition"] == "demonstrated_transfer"
    assert set(DISPOSITIONS) == {
        "benign",
        "unresolved",
        "suspected",
        "demonstrated_transfer",
        "policy_supported",
    }


def test_full_demo_session_export_and_audit(review_client):
    """AC2 + AC3: full session, chain verifies, package validates."""
    delivery_id, _raw = _quarantined_delivery(review_client)

    # Researcher decode denied; reviewer decode allowed.
    assert (
        review_client.get(
            f"/api/review/deliveries/{delivery_id}/candidate-decode",
            headers=RESEARCHER,
        ).status_code
        == 403
    )
    assert (
        review_client.get(
            f"/api/review/deliveries/{delivery_id}/candidate-decode",
            headers=REVIEWER,
        ).status_code
        == 200
    )
    # Disposition recorded by the reviewer.
    applied = review_client.post(
        f"/api/review/deliveries/{delivery_id}/disposition",
        json={"disposition": "suspected", "note": "structured heights"},
        headers=REVIEWER,
    )
    assert applied.status_code == 200

    # Reviewer lacks export.create; researcher downloads the package.
    forbidden = review_client.get(f"/api/review/runs/{RUN}/export", headers=REVIEWER)
    assert forbidden.status_code == 403
    download = review_client.get(f"/api/review/runs/{RUN}/export", headers=RESEARCHER)
    assert download.status_code == 200, download.text
    assert "attachment" in download.headers["content-disposition"]
    package = download.json()
    assert validate_review_package(package) == []
    assert package["run_id"] == RUN
    assert package["decisions"][0]["disposition"] == "suspected"
    assert package["contains_raw_bytes"] is False
    # Tampering with the sealed package breaks validation.
    package["decisions"][0]["disposition"] = "benign"
    assert validate_review_package(package) != []

    audit = review_client.get("/api/review/audit", params={"run_id": RUN}).json()
    assert audit["chain_valid"] is True
    assert audit["denied"] >= 2  # decode denial + export denial
    actions = {(e["action"], e["outcome"]) for e in audit["entries"]}
    assert ("candidate_decode.read", "allowed") in actions
    assert ("candidate_decode.read", "denied") in actions
    assert ("review.disposition", "applied") in actions
    assert ("export.create", "allowed") in actions


def test_review_state_survives_api_restart(review_client, tmp_path, monkeypatch):
    delivery_id, _raw = _quarantined_delivery(review_client)
    applied = review_client.post(
        f"/api/review/deliveries/{delivery_id}/disposition",
        json={"disposition": "benign", "note": "chart by design"},
        headers=RESEARCHER,
    )
    assert applied.status_code == 200
    # Simulate a container restart: drop singletons, keep the files.
    main_module._reset_gate_for_tests()
    queue = review_client.get(f"/api/review/runs/{RUN}/queue", headers=VIEWER)
    assert queue.json()["quarantined"][0]["disposition"] == "benign"
    audit = review_client.get("/api/review/audit", params={"run_id": RUN}).json()
    assert audit["chain_valid"] is True
    assert (tmp_path / "gate-store" / "review.sqlite3").exists()


def test_review_spa_route_served(review_client, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    monkeypatch.setattr(main_module, "STATIC_CANDIDATES", [tmp_path])
    page = review_client.get("/review")
    assert page.status_code == 200
    assert "<title>spa</title>" in page.text
    from pathlib import Path

    source = (
        Path(main_module.__file__).parent / "frontend" / "src" / "pages" / "Review.tsx"
    ).read_text()
    assert "X-Demo-Role" not in source  # header lives in the API client
    assert "Demo role" in source
    assert "candidate" in source
    api_source = (
        Path(main_module.__file__).parent / "frontend" / "src" / "api.ts"
    ).read_text()
    assert "X-Demo-Role" in api_source
