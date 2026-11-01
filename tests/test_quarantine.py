"""CL-18 acceptance tests: quarantine across every access path (ENF-03).

AC1 direct references, cached links and tool outputs enforce the same gate
AC2 no access occurs before verdict under concurrent delivery attempts
AC3 quarantined originals remain available only to authorized reviewers
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from covertlens.events import Verdict
from covertlens.gate import (
    InterceptionContext,
    InterceptionGate,
    PendingDeliveryError,
    ReviewerAccessError,
    UnknownDeliveryError,
    WithheldError,
)
from covertlens.routes import ROUTES
from covertlens.store import ArtifactStore

PNG = b"\x89PNG\r\n\x1a\n" + b"quarantine-test-image"
CTX = InterceptionContext(run_id="run_q", episode_id="ep_1", sender_id="agent-a")


def pending_gate(verdict=None):
    gate = InterceptionGate(ArtifactStore())
    handle = gate.intercept_bytes("R-01", PNG, CTX)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    if verdict is not None:
        gate.record_verdict(delivery.delivery_id, verdict)
    return gate, delivery


def test_all_gated_routes_enforce_the_same_verdict():
    gated = [r.route_id for r in ROUTES if r.gate_required]
    assert len(gated) == 7
    for route_id in gated:
        gate, delivery = pending_gate(Verdict.QUARANTINE)
        with pytest.raises(WithheldError):
            gate.serve_via_route(route_id, delivery.delivery_id)
    for route_id in gated:
        gate, delivery = pending_gate(Verdict.FLAG)
        assert gate.serve_via_route(route_id, delivery.delivery_id) == PNG
    gate, delivery = pending_gate(Verdict.FLAG)
    with pytest.raises(ValueError, match="review-only"):
        gate.serve_via_route("R-08", delivery.delivery_id)


def test_references_and_tool_outputs_hit_the_gate_before_access():
    gate = InterceptionGate(ArtifactStore())
    handle = gate.intercept_reference("R-03", "artifact://img-1", lambda ref: PNG, CTX)
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    with pytest.raises(PendingDeliveryError):
        gate.recipient_access(delivery.delivery_id)
    gate.record_verdict(delivery.delivery_id, Verdict.QUARANTINE)
    with pytest.raises(WithheldError):
        gate.recipient_access(delivery.delivery_id)
    assert gate.access_attempt_report()["unauthorized_served"] == 0


def test_cached_link_grants_nothing_and_rechecks_current_verdict():
    gate, delivery = pending_gate()
    token = gate.issue_cached_link(delivery.delivery_id)
    with pytest.raises(PendingDeliveryError):
        gate.redeem_cached_link(token)
    gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
    assert gate.redeem_cached_link(token) == PNG

    gate2, delivery2 = pending_gate()
    token2 = gate2.issue_cached_link(delivery2.delivery_id)
    gate2.record_verdict(delivery2.delivery_id, Verdict.QUARANTINE)
    with pytest.raises(WithheldError):
        gate2.redeem_cached_link(token2)
    with pytest.raises(UnknownDeliveryError):
        gate2.redeem_cached_link("lnk_unknown")


def test_no_access_before_verdict_under_concurrent_attempts():
    gate, delivery = pending_gate()

    def attempt(_):
        try:
            return gate.recipient_access(delivery.delivery_id)
        except PendingDeliveryError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(32)))
    assert results == [None] * 32  # zero bytes served pre-verdict
    gate.record_verdict(delivery.delivery_id, Verdict.QUARANTINE)

    def attempt_withheld(_):
        try:
            return gate.recipient_access(delivery.delivery_id)
        except WithheldError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt_withheld, range(32)))
    assert results == [None] * 32
    report = gate.access_attempt_report()
    assert report["unauthorized_served"] == 0
    assert report["served"] == 0
    assert report["pending_denied"] == 32
    assert report["withheld_denied"] == 32


def test_concurrent_permitted_access_serves_consistently():
    gate, delivery = pending_gate(Verdict.LOG)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: gate.recipient_access(delivery.delivery_id), range(16))
        )
    assert results == [PNG] * 16
    assert gate.access_attempt_report()["served"] == 16
    seqs = [e.seq for e in gate.events("run_q")]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_quarantined_originals_are_reviewer_only():
    gate, delivery = pending_gate(Verdict.QUARANTINE)
    reviewers = {"researcher-1"}
    assert (
        gate.reviewer_access(
            delivery.delivery_id, actor_id="researcher-1", reviewer_ids=reviewers
        )
        == PNG
    )
    with pytest.raises(ReviewerAccessError):
        gate.reviewer_access(
            delivery.delivery_id, actor_id="agent-b", reviewer_ids=reviewers
        )
    with pytest.raises(ReviewerAccessError):
        gate.reviewer_access(
            delivery.delivery_id, actor_id="researcher-2", reviewer_ids=reviewers
        )
    history = gate.store.access_history(delivery.artifact_version_id)
    assert [(h.actor_id, h.purpose) for h in history] == [("researcher-1", "review")]
    report = gate.access_attempt_report()
    assert report["reviewer_served"] == 1 and report["reviewer_denied"] == 2
    # The recipient path stays withheld throughout.
    with pytest.raises(WithheldError):
        gate.recipient_access(delivery.delivery_id)
