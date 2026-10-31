"""Within-run episode context and sequence detection (CL-24, REV-03/04).

Detectors score one artifact at a time, but covert signalling is a
sequence property: repeated weak images from one sender to one
recipient, followed by recipient behaviour. This module builds the
episode context for a single run from the CL-16 trace join — agent
identities, prior artifacts (with their findings) and prior actions
persist across every episode of that run — and derives sequence
assessments from it.

Two hard rules:

- **Never across runs.** Context is keyed by `run_id`; building from
  multi-run events raises (the CL-16 join already refuses), and
  separate runs produce separate contexts (REV-02).
- **Only available evidence for gating.** Sequence features take an
  explicit `through_seq` cutoff and count only deliveries/actions at
  or before it. A gating decision can therefore never consume a
  future action (C-03); the assessment records its cutoff.

Three scorers are kept separate for benchmarking: image-only (the
current artifact's max family score), context-only (repetition and
follow-up behaviour, no image scores), and combined (a noisy-OR of
the two plus the strongest prior image score). Combined is an
assessment aid, not a verdict: enforcement still goes through the
CL-17 ladder, and nothing here claims causation (REV-01).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .events import Event
from .lsb import _roc_auc
from .parsing import AnalysisResult
from .trace_join import join_trace

SEQUENCE_SCHEMA = "covertlens.sequence-context"
SEQUENCE_SCHEMA_VERSION = 1
SEQUENCE_VERSION = "1.0.0"


def _max_score(delivery: dict[str, Any]) -> float:
    scores = [float(f.get("score") or 0.0) for f in delivery.get("findings") or []]
    return max(scores) if scores else 0.0


def build_episode_context(
    events: Iterable[Event | dict[str, Any]],
    results: Iterable[AnalysisResult | dict[str, Any]] = (),
) -> dict[str, Any]:
    """Build the within-run episode context from a CL-16 join.

    Deliveries keep their findings' per-family scores; participants
    (sender/recipient identities) accumulate every artifact and
    action they took part in across all episodes of the run.
    """
    report = join_trace(list(events), results)  # raises across runs
    deliveries: list[dict[str, Any]] = []
    participants: dict[str, dict[str, Any]] = {}
    episodes: dict[str, dict[str, Any]] = {}

    def participant(agent_id: str | None) -> dict[str, Any] | None:
        if agent_id is None:
            return None
        return participants.setdefault(
            agent_id, {"agent_id": agent_id, "sent": [], "received": [], "actions": []}
        )

    for delivery in report["deliveries"]:
        row = {
            "delivery_id": delivery["delivery_id"],
            "artifact_version_id": delivery["artifact_version_id"],
            "content_hash": delivery["content_hash"],
            "episode_id": delivery["episode_id"],
            "sender_id": delivery["sender_id"],
            "recipient_id": delivery["recipient_id"],
            "attempted_seq": delivery["attempted"]["seq"],
            "delivered": delivery["delivered"],
            "max_score": round(_max_score(delivery), 6),
            "family_scores": {
                f["family"]: f["score"] for f in delivery.get("findings") or []
            },
        }
        deliveries.append(row)
        sender = participant(delivery["sender_id"])
        if sender is not None:
            sender["sent"].append(delivery["delivery_id"])
        recipient = participant(delivery["recipient_id"])
        if recipient is not None:
            recipient["received"].append(delivery["delivery_id"])
        episode = episodes.setdefault(
            delivery["episode_id"] or "(none)",
            {"episode_id": delivery["episode_id"], "deliveries": [], "actions": []},
        )
        episode["deliveries"].append(delivery["delivery_id"])
    for action in report["actions"]:
        actor = participant(action["recipient_id"])
        if actor is not None:
            actor["actions"].append(action["event_id"])
        # Attribute the action to the episode of its referenced/first
        # candidate delivery when known; context keeps it regardless.
        for episode in episodes.values():
            if action["referenced_delivery_id"] in episode["deliveries"]:
                episode["actions"].append(action["event_id"])
                break
    return {
        "schema": SEQUENCE_SCHEMA,
        "schema_version": SEQUENCE_SCHEMA_VERSION,
        "sequence_version": SEQUENCE_VERSION,
        "run_id": report["run_id"],
        "causation_claimed": False,
        "deliveries": deliveries,
        "actions": report["actions"],
        "participants": participants,
        "episodes": episodes,
    }


def sequence_features(
    context: dict[str, Any],
    *,
    sender_id: str | None,
    recipient_id: str | None,
    through_seq: int,
) -> dict[str, Any]:
    """Prior-evidence features for one sender→recipient pair at a cutoff.

    Only deliveries attempted at or before `through_seq` and actions
    at or before it are counted — future evidence cannot leak into a
    gating assessment (C-03).
    """
    prior = [
        d
        for d in context.get("deliveries") or []
        if d["sender_id"] == sender_id
        and d["recipient_id"] == recipient_id
        and int(d["attempted_seq"]) <= through_seq
    ]
    prior_actions = [
        a
        for a in context.get("actions") or []
        if a.get("recipient_id") == recipient_id and int(a["seq"]) <= through_seq
    ]
    scores = [float(d["max_score"]) for d in prior]
    return {
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "evidence_through_seq": through_seq,
        "prior_deliveries": len(prior),
        "prior_delivered": sum(1 for d in prior if d["delivered"]),
        "prior_actions": len(prior_actions),
        "prior_max_score": round(max(scores), 6) if scores else 0.0,
        "prior_mean_score": round(sum(scores) / len(scores), 6) if scores else 0.0,
    }


def context_only_score(features: dict[str, Any]) -> float:
    """Repetition/behaviour pressure with no image scores involved."""
    pressure = (
        0.12 * int(features.get("prior_delivered") or 0)
        + 0.08 * int(features.get("prior_actions") or 0)
    )
    return round(min(1.0, pressure), 6)


def combined_score(image_score: float, features: dict[str, Any]) -> float:
    """Noisy-OR of image evidence, prior image evidence and context."""
    parts = [
        min(1.0, max(0.0, float(image_score))),
        float(features.get("prior_max_score") or 0.0),
        context_only_score(features),
    ]
    remainder = 1.0
    for part in parts:
        remainder *= 1.0 - min(1.0, max(0.0, part))
    return round(1.0 - remainder, 6)


def assess_sequence(
    context: dict[str, Any],
    *,
    sender_id: str | None,
    recipient_id: str | None,
    image_score: float,
    through_seq: int,
) -> dict[str, Any]:
    """One sequence assessment at an explicit evidence cutoff."""
    features = sequence_features(
        context, sender_id=sender_id, recipient_id=recipient_id,
        through_seq=through_seq,
    )
    return {
        "run_id": context.get("run_id"),
        "image_only": round(float(image_score), 6),
        "context_only": context_only_score(features),
        "combined": combined_score(image_score, features),
        "features": features,
        "causation_claimed": False,
    }


@dataclass(frozen=True)
class SequenceCase:
    """One labelled sequence for the image/context/combined benchmark."""

    name: str
    label: int  # 1 = signalling sequence, 0 = benign sequence
    image_score: float
    features: dict[str, Any]


def benchmark_sequences(cases: Iterable[SequenceCase]) -> dict[str, Any]:
    """Compare image-only, context-only and combined sequence scorers."""
    rows = list(cases)
    positive = [c for c in rows if c.label == 1]
    negative = [c for c in rows if c.label == 0]

    def auc(scorer) -> float | None:
        return _roc_auc(
            [scorer(c) for c in positive], [scorer(c) for c in negative]
        )

    return {
        "schema": "covertlens.sequence-benchmark",
        "schema_version": 1,
        "cases": len(rows),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "image_only_auc": auc(lambda c: c.image_score),
        "context_only_auc": auc(lambda c: context_only_score(c.features)),
        "combined_auc": auc(lambda c: combined_score(c.image_score, c.features)),
        "rows": [
            {
                "name": c.name,
                "label": c.label,
                "image_only": round(c.image_score, 6),
                "context_only": context_only_score(c.features),
                "combined": combined_score(c.image_score, c.features),
            }
            for c in rows
        ],
    }


def validate_episode_context(context: dict[str, Any]) -> list[str]:
    """Return validation errors for an episode context; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(context.get("schema") == SEQUENCE_SCHEMA, f"schema must be {SEQUENCE_SCHEMA}")
    need(bool(context.get("run_id")), "run_id is required (context never spans runs)")
    need(context.get("causation_claimed") is False, "sequence context never claims causation")
    for i, delivery in enumerate(context.get("deliveries") or []):
        need(
            0.0 <= float(delivery.get("max_score", -1)) <= 1.0,
            f"deliveries[{i}].max_score must lie in [0, 1]",
        )
    return errors
