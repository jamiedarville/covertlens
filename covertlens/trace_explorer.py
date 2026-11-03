"""Trace explorer view over one run (CL-60, REV-01/02/03).

One read-only projection for the Trace explorer page, assembled
from the CL-16 trace join and the CL-24 episode context:

- **Deliveries.** Every attempted delivery with its original
  `content_hash`, its verdict reference (or the explicit `missing`
  status), and its parse/next-action linkage (or the explicit
  `missing` status). The join's `missing` keys are expanded to
  `missing_reasons`, one human-readable reason per absent link, so
  the page never has to guess at a blank cell.
- **Episode context.** Participants and episodes from
  `build_episode_context` for this run only (REV-02: context never
  spans runs; the join refuses multi-run input).
- **Repeated weak signals.** Per sender, the deliveries whose
  strongest family score sits in the weak band (above zero, below
  the structure-grade band at 0.75) and whether that sender shows
  at least two of them. This is a triage aid over recorded scores
  (CL-31: sequence evidence is a triage aid only), not a verdict
  and not proof of signalling.
- **Actions.** Recipient actions with their candidate input
  artifacts from the join. Candidates are deliveries visible to
  the recipient before the action; `causation_claimed` is false
  on every record and on the whole view. Nothing here states or
  implies that an artifact produced an action.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ._validation import make_need
from .events import Event
from .parsing import AnalysisResult
from .sequence import build_episode_context, validate_episode_context
from .trace_join import join_trace, validate_trace_join

EXPLORER_SCHEMA = "covertlens.trace-explorer"
EXPLORER_SCHEMA_VERSION = 1
EXPLORER_VERSION = "1.0.0"
WEAK_BAND_MAX = 0.75
CAUSATION_NOTE = (
    "candidate inputs are deliveries visible to the recipient "
    "before an action; they are not a cause of the action"
)

MISSING_REASONS = {
    "content_hash": "no original content hash recorded for this delivery",
    "verdict_reference": "no gate verdict recorded for this delivery yet",
    "parse_event": "no recipient parse recorded for this delivered artifact",
    "next_action": "no recipient action recorded after this delivery",
}


def _missing_reasons(missing: Iterable[str]) -> list[dict[str, str]]:
    return [
        {"link": key, "reason": MISSING_REASONS.get(key, f"{key} is missing")}
        for key in missing
    ]


def weak_signals_by_sender(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-sender repeated-weak-signal summary (triage aid only)."""
    by_sender: dict[str, list[dict[str, Any]]] = {}
    for delivery in context.get("deliveries") or []:
        sender = delivery.get("sender_id")
        if sender is None:
            continue
        by_sender.setdefault(str(sender), []).append(delivery)
    rows: list[dict[str, Any]] = []
    for sender, deliveries in sorted(by_sender.items()):
        weak = [
            d
            for d in deliveries
            if 0.0 < float(d.get("max_score") or 0.0) < WEAK_BAND_MAX
        ]
        rows.append(
            {
                "sender_id": sender,
                "deliveries": len(deliveries),
                "delivered": sum(1 for d in deliveries if d.get("delivered")),
                "weak_signals": len(weak),
                "weak_delivery_ids": [d["delivery_id"] for d in weak],
                "repeated_weak": len(weak) >= 2,
                "max_score": round(
                    max(
                        (float(d.get("max_score") or 0.0) for d in deliveries),
                        default=0.0,
                    ),
                    6,
                ),
            }
        )
    return rows


def build_trace_explorer(
    events: Iterable[Event | dict[str, Any]],
    results: Iterable[AnalysisResult | dict[str, Any]] = (),
) -> dict[str, Any]:
    """Assemble the Trace explorer view for one run (read-only)."""
    event_list = list(events)
    result_list = list(results)
    joined = join_trace(event_list, result_list)
    context = build_episode_context(event_list, result_list)
    deliveries = [
        {
            **delivery,
            "missing_reasons": _missing_reasons(delivery.get("missing") or []),
        }
        for delivery in joined["deliveries"]
    ]
    weak = weak_signals_by_sender(context)
    return {
        "schema": EXPLORER_SCHEMA,
        "schema_version": EXPLORER_SCHEMA_VERSION,
        "explorer_version": EXPLORER_VERSION,
        "run_id": joined["run_id"],
        "causation_claimed": False,
        "causation_note": CAUSATION_NOTE,
        "deliveries": deliveries,
        "actions": joined["actions"],
        "unjoined_results": joined["unjoined_results"],
        "linkage_errors": joined["errors"],
        "context": {
            "participants": context["participants"],
            "episodes": context["episodes"],
            "deliveries": context["deliveries"],
        },
        "weak_signals": {
            "band": {"min_exclusive": 0.0, "max_exclusive": WEAK_BAND_MAX},
            "per_sender": weak,
            "repeated_senders": [r["sender_id"] for r in weak if r["repeated_weak"]],
            "label": "triage_aid_not_verdict",
        },
        "summary": {
            **joined["summary"],
            "deliveries_with_missing_links": sum(
                1 for d in deliveries if d["missing_reasons"]
            ),
            "repeated_weak_senders": len([r for r in weak if r["repeated_weak"]]),
        },
        "validation": {
            "join_errors": validate_trace_join(joined),
            "context_errors": validate_episode_context(context),
        },
    }


def validate_trace_explorer(view: dict[str, Any]) -> list[str]:
    """Return validation errors for one explorer view; empty is valid."""
    errors: list[str] = []

    need = make_need(errors)

    need(view.get("schema") == EXPLORER_SCHEMA, f"schema must be {EXPLORER_SCHEMA}")
    need(
        view.get("causation_claimed") is False,
        "the trace explorer never claims causation",
    )
    for i, delivery in enumerate(view.get("deliveries") or []):
        prefix = f"deliveries[{i}]"
        need(bool(delivery.get("content_hash")), f"{prefix} needs its content_hash")
        need(
            delivery.get("verdict_reference_status") in ("linked", "missing"),
            f"{prefix} verdict link must be linked or explicitly missing",
        )
        parse = delivery.get("parse") or {}
        need(
            parse.get("linkage") in ("linked", "missing"),
            f"{prefix} parse link must be linked or explicitly missing",
        )
        reasons = {r.get("link") for r in delivery.get("missing_reasons") or []}
        need(
            reasons == set(delivery.get("missing") or []),
            f"{prefix} every missing link needs an explicit reason",
        )
    for i, action in enumerate(view.get("actions") or []):
        need(
            action.get("causation_claimed") is False,
            f"actions[{i}] must not claim causation",
        )
    validation = view.get("validation") or {}
    need(validation.get("join_errors") == [], "join validation must pass")
    need(validation.get("context_errors") == [], "context validation must pass")
    return errors
