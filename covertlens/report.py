"""Researcher run report and triage workflow (CL-25, REV-05).

One versioned report assembles everything a researcher needs to
review a run without touching raw evidence stores: the originals
(exact version + hash references), component findings per family,
gate verdicts, prior episode context (CL-24), and the ordered action
timeline (CL-16 join). Original *bytes* are deliberately not embedded
— the report carries references and hashes; byte access stays on the
audited CL-18/R-08 path.

Review is a triage workflow over that report. Every delivery starts
`unresolved`; a reviewer may record one of five dispositions
(`benign`, `unresolved`, `suspected`, `demonstrated_transfer`,
`policy_supported`). `demonstrated_transfer` additionally requires a
recorded basis (what independent recovery/action evidence shows the
transfer) — a score alone can never create it. Scores and score-bars
("heatmaps") are labelled `evidence_aid_not_decoded_message`
everywhere they appear: they summarise detector evidence, they are
not decoded content and not proof of collusion (C-02).
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from .events import Event
from .parsing import AnalysisResult
from .sequence import build_episode_context
from .trace_join import join_trace

REPORT_SCHEMA = "covertlens.run-report"
REPORT_SCHEMA_VERSION = 1
REPORT_VERSION = "1.0.0"
DISPOSITIONS = (
    "benign",
    "unresolved",
    "suspected",
    "demonstrated_transfer",
    "policy_supported",
)
EVIDENCE_AID_LABEL = "evidence_aid_not_decoded_message"


def _bar(score: float) -> str:
    filled = int(round(min(1.0, max(0.0, score)) * 10))
    return "#" * filled + "-" * (10 - filled)


def build_run_report(
    events: Iterable[Event | dict[str, Any]],
    results: Iterable[AnalysisResult | dict[str, Any]] = (),
    *,
    report_id: str | None = None,
) -> dict[str, Any]:
    """Assemble the researcher report for one run (read-only projection)."""
    event_list = list(events)
    result_list = list(results)
    joined = join_trace(event_list, result_list)
    context = build_episode_context(event_list, result_list)

    originals: dict[str, dict[str, Any]] = {}
    for delivery in joined["deliveries"]:
        version = delivery["artifact_version_id"]
        if version and version not in originals:
            originals[version] = {
                "artifact_id": delivery["artifact_id"],
                "artifact_version_id": version,
                "content_hash": delivery["content_hash"],
                "findings": delivery["findings"],
                "evidence_aids": [
                    {
                        "family": f["family"],
                        "detector": f"{f['detector_name']}@{f['detector_version']}",
                        "score": f["score"],
                        "bar": _bar(float(f["score"])),
                        "label": EVIDENCE_AID_LABEL,
                    }
                    for f in delivery["findings"]
                ],
            }
    timeline = [
        e.to_dict() if isinstance(e, Event) else dict(e) for e in event_list
    ]
    timeline.sort(key=lambda e: int(e.get("seq") or 0))
    triage = sorted(
        (
            {
                "delivery_id": d["delivery_id"],
                "artifact_version_id": d["artifact_version_id"],
                "max_score": max(
                    [float(f["score"]) for f in d["findings"]], default=0.0
                ),
                "verdict": (d["verdict"] or {}).get("verdict"),
                "delivered": d["delivered"],
                "parse_status": d["parse"]["parse_status"],
                "disposition": "unresolved",
            }
            for d in joined["deliveries"]
        ),
        key=lambda row: row["max_score"],
        reverse=True,
    )
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_version": REPORT_VERSION,
        "report_id": report_id,
        "run_id": joined["run_id"],
        "causation_claimed": False,
        "evidence_aid_label": EVIDENCE_AID_LABEL,
        "originals": list(originals.values()),
        "deliveries": joined["deliveries"],
        "timeline": timeline,
        "prior_context": {
            "participants": context["participants"],
            "episodes": context["episodes"],
        },
        "actions": joined["actions"],
        "triage_queue": triage,
        "reviews": {},
        "disposition_counts": {name: 0 for name in DISPOSITIONS},
    }


def apply_review(
    report: dict[str, Any],
    delivery_id: str,
    *,
    reviewer: str,
    disposition: str,
    note: str = "",
    demonstrated_basis: str | None = None,
) -> dict[str, Any]:
    """Record one review disposition; returns an updated report copy.

    `demonstrated_transfer` requires `demonstrated_basis` describing
    the independent evidence (recovery + behaviour), never a score.
    Re-review replaces the previous disposition for that delivery.
    """
    if disposition not in DISPOSITIONS:
        raise ValueError(f"disposition must be one of {DISPOSITIONS}")
    if disposition == "demonstrated_transfer" and not demonstrated_basis:
        raise ValueError(
            "demonstrated_transfer requires a recorded basis in independent "
            "recovery/action evidence; a detector score is never sufficient"
        )
    updated = copy.deepcopy(report)
    known = {d["delivery_id"] for d in updated.get("deliveries") or []}
    if delivery_id not in known:
        raise KeyError(delivery_id)
    updated.setdefault("reviews", {})[delivery_id] = {
        "reviewer": reviewer,
        "disposition": disposition,
        "note": note,
        "demonstrated_basis": demonstrated_basis,
    }
    for row in updated.get("triage_queue") or []:
        if row["delivery_id"] == delivery_id:
            row["disposition"] = disposition
    counts = {name: 0 for name in DISPOSITIONS}
    for row in updated.get("triage_queue") or []:
        counts[row["disposition"]] += 1
    updated["disposition_counts"] = counts
    problems = validate_run_report(updated)
    if problems:
        raise ValueError(f"invalid report after review: {'; '.join(problems)}")
    return updated


def validate_run_report(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one run report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == REPORT_SCHEMA, f"schema must be {REPORT_SCHEMA}")
    need(bool(report.get("run_id")), "run_id is required")
    need(report.get("causation_claimed") is False, "reports never claim causation")
    need(
        report.get("evidence_aid_label") == EVIDENCE_AID_LABEL,
        "scores/heatmaps must be labelled evidence aids, not decoded messages",
    )
    for i, original in enumerate(report.get("originals") or []):
        need(
            str(original.get("content_hash") or "").startswith("sha256:"),
            f"originals[{i}] must reference exact bytes by hash (no embedded bytes)",
        )
        need("data" not in original, f"originals[{i}] must not embed original bytes")
        for aid in original.get("evidence_aids") or []:
            need(
                aid.get("label") == EVIDENCE_AID_LABEL,
                f"originals[{i}] evidence aids must carry the evidence-aid label",
            )
    for delivery_id, review in (report.get("reviews") or {}).items():
        need(
            review.get("disposition") in DISPOSITIONS,
            f"reviews[{delivery_id}] disposition is not a supported value",
        )
        if review.get("disposition") == "demonstrated_transfer":
            need(
                bool(review.get("demonstrated_basis")),
                f"reviews[{delivery_id}] demonstrated_transfer needs a recorded basis",
            )
    return errors
