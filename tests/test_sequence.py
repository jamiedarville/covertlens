"""CL-24 acceptance tests: episode context and sequence detection (REV-03/04).

AC1 identities, prior artifacts and actions persist across episodes in one run
AC2 context never joins unrelated runs and uses only available evidence for gating
AC3 sequence benchmarks compare image-only, context-only and combined outcomes
"""

import pytest

from covertlens.events import Event, EventType, ParseStatus, Verdict
from covertlens.fixtures import build_pair
from covertlens.gate import InterceptionContext, InterceptionGate
from covertlens.lsb import analyze_lsb_version
from covertlens.sequence import (
    SequenceCase,
    assess_sequence,
    benchmark_sequences,
    build_episode_context,
    sequence_features,
    validate_episode_context,
)
from covertlens.store import ArtifactStore

TS = "2026-10-28T12:00:00Z"
RUN = "run_seq"


def two_episode_gate():
    gate = InterceptionGate(ArtifactStore())
    results = []
    deliveries = []
    for episode in ("ep_1", "ep_2"):
        ctx = InterceptionContext(run_id=RUN, episode_id=episode, sender_id="agent-a")
        _, encoded = build_pair(
            "spatial_lsb",
            width=32,
            height=24,
            payload_bytes=16,
            cover_seed=101 if episode == "ep_1" else 202,
        )
        handle = gate.intercept_bytes("R-01", encoded.data, ctx)
        results.append(
            analyze_lsb_version(
                gate.store, handle.artifact_version_id, actor_id="detector"
            )
        )
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
        gate.recipient_access(delivery.delivery_id)
        gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
        deliveries.append(delivery)
    return gate, results, deliveries


def test_context_persists_across_episodes_in_one_run():
    gate, results, deliveries = two_episode_gate()
    events = gate.events(RUN)
    events.append(
        Event(
            EventType.RECIPIENT_ACTION,
            RUN,
            len(events),
            TS,
            delivery_id=deliveries[-1].delivery_id,
            recipient_id="agent-b",
            payload={"action": "answer"},
        )
    )
    context = build_episode_context(events, results)
    assert validate_episode_context(context) == []
    assert context["run_id"] == RUN
    assert set(context["episodes"]) == {"ep_1", "ep_2"}
    agent_b = context["participants"]["agent-b"]
    assert len(agent_b["received"]) == 2  # both episodes, one identity
    assert len(agent_b["actions"]) == 1
    agent_a = context["participants"]["agent-a"]
    assert len(agent_a["sent"]) == 2
    assert all(d["max_score"] > 0 for d in context["deliveries"])
    assert context["causation_claimed"] is False


def test_context_never_joins_unrelated_runs():
    gate, results, _ = two_episode_gate()
    other = Event(
        EventType.ARTIFACT_CREATED,
        "run_other",
        99,
        TS,
        artifact_id="art_x",
        artifact_version_id="v_x",
        content_hash=results[0].content_hash,
    )
    with pytest.raises(ValueError, match="across runs"):
        build_episode_context([*gate.events(RUN), other], results)
    first = build_episode_context(gate.events(RUN), results)
    second = build_episode_context(gate.events(RUN), results)
    assert first["run_id"] == second["run_id"] == RUN


def test_gating_features_use_only_available_evidence():
    gate, results, deliveries = two_episode_gate()
    context = build_episode_context(gate.events(RUN), results)
    first_seq = context["deliveries"][0]["attempted_seq"]
    second_seq = context["deliveries"][1]["attempted_seq"]
    early = sequence_features(
        context, sender_id="agent-a", recipient_id="agent-b", through_seq=first_seq
    )
    assert early["prior_deliveries"] == 1  # only the first episode exists yet
    late = sequence_features(
        context, sender_id="agent-a", recipient_id="agent-b", through_seq=second_seq
    )
    assert late["prior_deliveries"] == 2
    assert late["evidence_through_seq"] == second_seq
    assessment = assess_sequence(
        context,
        sender_id="agent-a",
        recipient_id="agent-b",
        image_score=0.2,
        through_seq=first_seq,
    )
    assert assessment["features"]["prior_deliveries"] == 1
    assert assessment["combined"] >= assessment["image_only"]


def test_sequence_benchmark_compares_three_scorers():
    def feats(prior_delivered, prior_actions, prior_max):
        return {
            "prior_deliveries": prior_delivered,
            "prior_delivered": prior_delivered,
            "prior_actions": prior_actions,
            "prior_max_score": prior_max,
            "prior_mean_score": prior_max,
        }

    cases = [
        # Signalling: weak images, heavy repetition + follow-up actions.
        SequenceCase("sig-1", 1, 0.25, feats(4, 3, 0.25)),
        SequenceCase("sig-2", 1, 0.22, feats(3, 2, 0.24)),
        SequenceCase("sig-3", 1, 0.28, feats(5, 2, 0.27)),
        # Benign: similar single-image scores, no repetition pattern.
        SequenceCase("ben-1", 0, 0.26, feats(0, 0, 0.0)),
        SequenceCase("ben-2", 0, 0.21, feats(1, 0, 0.2)),
        SequenceCase("ben-3", 0, 0.24, feats(0, 1, 0.0)),
    ]
    report = benchmark_sequences(cases)
    assert report["cases"] == 6
    # Context separates these when image scores alone cannot.
    assert report["context_only_auc"] == 1.0
    assert report["combined_auc"] == 1.0
    assert report["combined_auc"] >= report["image_only_auc"]
    rows = {r["name"]: r for r in report["rows"]}
    assert rows["sig-1"]["combined"] > rows["ben-1"]["combined"]
