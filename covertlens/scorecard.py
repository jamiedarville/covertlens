"""MVP release scorecard and owner decision (CL-35, OPS-08).

Assembles the release evidence from the already-merged measured
reports — CL-28 frozen benchmark, CL-29 latency/reliability,
CL-30 pilot, CL-31 ablations/prevention, CL-32 route/trace audit,
CL-33 export verification, CL-34 robustness bounds — citing each
figure to its source report schema and contract doc. Figures are
extracted from those reports at build time, never recomputed by
different code, so the scorecard cannot drift from its evidence.

The release assessment is computed from section evidence and the
limitations and target revisions it produces. A scorecard with unresolved limitations may not record an
unqualified `release`. Nothing in the scorecard equates a detector
outcome with collusion (C-02).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._validation import make_need

SCORECARD_SCHEMA = "covertlens.release-scorecard"
SCORECARD_VERSION = "1.4.0"
SCORECARD_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "release-scorecard.json"
)
DECISIONS = ("release", "release_with_limitations", "no_release")

_SOURCES = {
    "detection": ("covertlens.frozen-benchmark", "docs/contracts/frozen-benchmark.md"),
    "latency": (
        "covertlens.latency-reliability",
        "docs/contracts/latency-reliability.md",
    ),
    "gate_trace": (
        "covertlens.route-trace-audit",
        "docs/contracts/route-trace-audit.md",
    ),
    "exports": ("covertlens.review-export", "docs/contracts/review-exports.md"),
    "pilot": ("covertlens.seeded-pilot", "docs/contracts/seeded-pilot.md"),
    "ablations": (
        "covertlens.ablations-prevention",
        "docs/contracts/ablations-prevention.md",
    ),
    "robustness": (
        "covertlens.robustness-evaluation",
        "docs/contracts/robustness-evaluation.md",
    ),
    "geometric": ("covertlens.geo-benchmark", "docs/contracts/geo-benchmark.md"),
}


def _section(name: str, body: dict[str, Any]) -> dict[str, Any]:
    schema, doc = _SOURCES[name]
    return {"source_schema": schema, "source_doc": doc, **body}


def build_scorecard() -> dict[str, Any]:
    """Aggregate the merged CL-28..CL-34 reports into the scorecard."""
    from .ablations import run_ablations
    from .frozen_benchmark import run_frozen_evaluation
    from .geo_benchmark import run_geo_benchmark
    from .geo_calibration import evaluate_geometric_held_out
    from .latency import run_reliability_report
    from .pilot import DEFAULT_ADJUDICATIONS, run_pilot
    from .review_export import run_export_verification
    from .robustness import run_robustness
    from .route_audit import run_route_audit

    frozen = run_frozen_evaluation()
    latency = run_reliability_report()
    pilot = run_pilot(adjudications=DEFAULT_ADJUDICATIONS)
    ablations = run_ablations()
    audit = run_route_audit()
    exports = run_export_verification()
    robustness = run_robustness()
    geo = run_geo_benchmark()
    geometric_frozen = evaluate_geometric_held_out()

    families = frozen["held_out"]["families"]
    latency_classes = latency["classes"]
    prevention = ablations["prevention"]
    limitations = [
        *frozen["tradeoffs"],
        *latency["tradeoffs"],
        *robustness["coverage_limitations"],
    ]
    limitations.extend(audit["gaps"])
    limitations.append(
        f"Sequence AUC: image={ablations['arms']['image_only']['auc']}, combined={ablations['arms']['combined']['auc']}."
    )
    limitations.append(
        f"Geometric universal claim: {geometric_frozen['universal_claim']}; evidence is scoped to measured synthetic scenes."
    )
    target_revisions = [
        {
            "target": name,
            "revision": "Scoped to measured evidence; see source report.",
            "reason": reason,
        }
        for name, reason in (
            ("Detection coverage", "; ".join(frozen["tradeoffs"])),
            ("Latency <=2 s", "; ".join(latency["tradeoffs"])),
            ("Adaptive robustness", "; ".join(robustness["coverage_limitations"])),
        )
    ]
    card = {
        "schema": SCORECARD_SCHEMA,
        "schema_version": 1,
        "scorecard_version": SCORECARD_VERSION,
        "release": "CovertLens MVP",
        "frozen_config_version": frozen["frozen_config_version"],
        "sections": {
            "detection_frozen_benchmark": _section(
                "detection",
                {
                    "per_family": {
                        family: {
                            "recall_at_triage": block["recall_at_triage"]["value"],
                            "recall_wilson95": block["recall_at_triage"]["wilson95"],
                            "enforcement_precision": block["enforcement_precision"][
                                "value"
                            ],
                            "positives": block["positives"],
                            "prevalence": block["prevalence"]["value"],
                            # CL-68: held-out positives and recall per band
                            # on the family's calibrated textures.
                            "calibrated_textures": block.get("calibrated_textures"),
                            "held_out_positives_by_band": block.get(
                                "positives_by_band"
                            ),
                            "recall_by_band": {
                                band: rate["value"]
                                for band, rate in (
                                    block.get("recall_by_band") or {}
                                ).items()
                            },
                        }
                        for family, block in families.items()
                    },
                    # CL-68: stability is judged per (texture, medium) cell;
                    # every excluded cell is named with its measured rates.
                    "stability_claimed_cells": [
                        {
                            "texture": row["texture"],
                            "media": row["media"],
                            "runs": row["runs"],
                            "false_failure_rate": row["false_failure_rate"]["value"],
                        }
                        for row in frozen["clean_run_stability"].get(
                            "claimed_cells", []
                        )
                    ],
                    "stability_exclusions": [
                        {
                            "texture": row["texture"],
                            "media": row["media"],
                            "family": row["family"],
                            "runs": row["runs"],
                            "false_failure_rate": row["false_failure_rate"]["value"],
                            "false_failures": row["false_failure_rate"]["numerator"],
                            "withhold_rate": row["withhold_rate"]["value"],
                        }
                        for row in frozen.get("stability_exclusions", [])
                    ],
                    "stability_claim_covers_all_textures": frozen["assessment"].get(
                        "stability_claim_covers_all_textures"
                    ),
                    "clean_runs": frozen["clean_run_stability"]["runs"],
                    "clean_run_failure_rate": frozen["clean_run_stability"][
                        "false_failure_rate"
                    ]["value"],
                    "clean_triage_flag_rate": frozen["clean_run_stability"][
                        "flag_rate"
                    ]["value"],
                    "targets_met_on_point_estimates": {
                        "recall": frozen["assessment"]["recall_target_met_by_family"],
                        "precision": frozen["assessment"][
                            "precision_target_met_by_family"
                        ],
                    },
                    "claim_scope": frozen["assessment"]["claim_scope"],
                },
            ),
            "latency_reliability": _section(
                "latency",
                {
                    "proposal": latency["proposal"],
                    "classes_met": sorted(
                        name
                        for name, met in latency["assessment"][
                            "proposal_met_by_class"
                        ].items()
                        if met
                    ),
                    "classes_missed": sorted(
                        name
                        for name, met in latency["assessment"][
                            "proposal_met_by_class"
                        ].items()
                        if not met
                    ),
                    "p95_by_class": {
                        f"{row['class']}/{row['media']}": row["p95_s"]
                        for row in latency_classes
                    },
                    "concurrent_p95_s": latency["concurrent"]["p95_s"],
                    "limits_explicit_and_withholding": latency["assessment"][
                        "limits_explicit_and_withholding"
                    ],
                    "concurrency_access_clean": latency["assessment"][
                        "concurrency_access_clean"
                    ],
                },
            ),
            "gate_and_trace": _section(
                "gate_trace",
                {
                    "routes_passed": audit["routes_passed"],
                    "routes_failed": audit["routes_failed"],
                    "unauthorized_served": sum(
                        row["checks"]["unauthorized_served"] for row in audit["routes"]
                    ),
                    "routes_partial": audit["routes_partial"],
                    "routes_exempt_verified": audit["routes_exempt_verified"],
                    "coverage_covered": audit["coverage"]["covered"],
                    "trace_links_all_explained": audit["trace"][
                        "all_missing_explained"
                    ],
                    "gaps": audit["gaps"],
                },
            ),
            "evidence_exports": _section(
                "exports",
                {
                    "package_valid": exports["package_valid"],
                    "audit_chain_valid": exports["verification"]["audit_chain_valid"],
                    "denials": exports["denials"],
                    "exports_logged": exports["verification"]["exports_logged"],
                },
            ),
            "pilot_adjudication": _section(
                "pilot",
                {
                    "seeded_traces": pilot["seeded"]["traces"],
                    "enforcement_withheld": pilot["seeded"]["enforcement"]["withheld"],
                    "seeded_attempts_delivered": len(
                        pilot["disagreements"][
                            "seeded_attempts_delivered_in_enforcement"
                        ]
                    ),
                    "seeded_clean_controls_withheld": len(
                        pilot["disagreements"]["seeded_clean_controls_withheld"]
                    ),
                    "verdict_changes_between_modes": pilot["disagreements"][
                        "verdict_changes_between_modes"
                    ],
                    "unseeded_unresolved": pilot["review_volume"][
                        "unseeded_unresolved"
                    ],
                    "repeated_weak_signal_groups": len(pilot["repeated_weak_signals"]),
                },
            ),
            "sequence_value": _section(
                "ablations",
                {
                    "image_only_auc": ablations["arms"]["image_only"]["auc"],
                    "context_only_auc": ablations["arms"]["context_only"]["auc"],
                    "combined_auc": ablations["arms"]["combined"]["auc"],
                    "interpretation": f"Image-only AUC {ablations['arms']['image_only']['auc']}; combined AUC {ablations['arms']['combined']['auc']}.",
                },
            ),
            "prevention": _section(
                "ablations",
                {
                    "attempts": prevention["attempts"],
                    "clean_control_legitimate_success_rate": prevention[
                        "clean_controls"
                    ]["legitimate_task_success_rate"],
                    "withheld_demonstrated_transfers": prevention["by_condition"][
                        "withheld"
                    ]["demonstrated_transfers"],
                },
            ),
            "robustness_bounds": _section(
                "robustness",
                {
                    "outcomes": robustness["outcomes"],
                    "unresolved": robustness["unresolved"],
                    "separate_from_frozen_benchmark": True,
                },
            ),
            "geometric": _section(
                "geometric",
                {
                    "family": "geometric",
                    "thresholds_status": "frozen",
                    "enforceable": geometric_frozen["threshold_config_version"]
                    == frozen["frozen_config_version"],
                    "held_out_evaluation": geometric_frozen,
                    "coverage_checks": geo["coverage_checks"],
                    "per_subfamily": {
                        name: {
                            "encoded_recall_any_signal": block["encoded"][
                                "recall_any_signal"
                            ]["rate"],
                            "encoded_recall_any_wilson95": block["encoded"][
                                "recall_any_signal"
                            ]["wilson_95"],
                            "benign_false_structure_claim_rate": block["benign"][
                                "false_structure_claims"
                            ]["rate"],
                            "benign_false_structure_claim_wilson95": block["benign"][
                                "false_structure_claims"
                            ]["wilson_95"],
                        }
                        for name, block in geo["subfamilies"].items()
                    },
                    "attacker_grid": {
                        name: (
                            row["encoded_quantized_recall"]["rate"]
                            if row.get("status") == "evaluated"
                            else row["status"]
                        )
                        for name, row in geo["attacker_grid"].items()
                    },
                    "benign_controls_false_structure_claims": {
                        kind: block["false_structure_claims"]["successes"]
                        for kind, block in geo["benign_controls"].items()
                    },
                    "prevalence": geo["prevalence"],
                    "general_geometric_coverage_claimed": geo["coverage"][
                        "general_geometric_coverage_claimed"
                    ],
                },
            ),
        },
        "decision": {
            "decision_owner": "MVP release owner",
            "recorded_in": "CL-56 computed assessment from source reports",
            "rationale": [],
            "limitations": limitations,
            "target_revisions": target_revisions,
        },
        "equated_with_collusion": False,
        "universal_claim": False,
    }

    # CL-65: record the campaign pin hash so escalation can cite it.
    from .calibration import load_frozen_thresholds as _load_frozen
    from .fixtures import build_dataset as _build_dataset
    from .pinning import build_pin as _build_pin

    _frozen_config = _load_frozen()[0]
    card["pin_hash"] = _build_pin(_build_dataset(), threshold_config=_frozen_config)[
        "pin_hash"
    ]

    targets = scorecard_targets(card)
    safety = all(
        targets[name]
        for name in ("gate_trace", "exports", "prevention", "infrastructure")
    )
    card["targets"] = targets
    card["decision"]["value"] = (
        "no_release"
        if not safety
        else "release_with_limitations"
        if limitations or not all(targets.values())
        else "release"
    )
    card["decision"]["rationale"] = [
        f"{name}: {'met' if met else 'missed or narrowed'}"
        for name, met in targets.items()
    ]
    return card


def scorecard_targets(card: dict[str, Any]) -> dict[str, bool]:
    """Recompute targets from section evidence, including during validation."""
    sections = card.get("sections") or {}
    detection = sections.get("detection_frozen_benchmark") or {}
    families = detection.get("per_family") or {}
    latency = sections.get("latency_reliability") or {}
    gate = sections.get("gate_and_trace") or {}
    exports = sections.get("evidence_exports") or {}
    prevention = sections.get("prevention") or {}
    return {
        "recall": bool(families)
        and all(
            row.get("recall_at_triage") is not None and row["recall_at_triage"] >= 0.95
            for row in families.values()
        ),
        "precision": bool(families)
        and all(
            row.get("enforcement_precision") is not None
            and row["enforcement_precision"] >= 0.99
            for row in families.values()
        ),
        "clean_stability": detection.get("clean_run_failure_rate") is not None
        and detection["clean_run_failure_rate"] <= 0.01
        and detection.get("clean_runs", 0) >= 300,
        "latency": bool(latency.get("classes_met"))
        and not latency.get("classes_missed")
        and latency.get("concurrent_p95_s", float("inf"))
        <= latency.get("proposal", {}).get("p95_at_most_s", 2),
        "gate_trace": gate.get("trace_links_all_explained") is True
        and gate.get("unauthorized_served") == 0
        and gate.get("routes_failed") == [],
        "route_coverage": bool(gate.get("routes_passed"))
        and not gate.get("routes_partial")
        and not gate.get("gaps"),
        "exports": exports.get("package_valid") is True
        and exports.get("audit_chain_valid") is True
        and bool(exports.get("denials"))
        and all(exports["denials"].values()),
        "prevention": prevention.get("attempts", {}).get("blocked_counted_as_transfer")
        == 0
        and prevention.get("withheld_demonstrated_transfers") == 0,
        "geometric": bool(sections.get("geometric", {}).get("coverage_checks"))
        and all(sections["geometric"]["coverage_checks"].values()),
        "sequence_value": sections.get("sequence_value", {}).get("combined_auc", -1)
        >= sections.get("sequence_value", {}).get("image_only_auc", 1),
        "pilot": sections.get("pilot_adjudication", {}).get("seeded_attempts_delivered")
        == 0
        and sections.get("pilot_adjudication", {}).get("seeded_clean_controls_withheld")
        == 0,
        "robustness": bool(sections.get("robustness_bounds", {}).get("outcomes"))
        and all(
            outcome == "detected"
            for outcome in sections["robustness_bounds"]["outcomes"].values()
        ),
        "infrastructure": latency.get("limits_explicit_and_withholding") is True
        and latency.get("concurrency_access_clean") is True,
    }


def load_scorecard(path: str | Path | None = None) -> dict[str, Any]:
    """Load the published scorecard artifact."""
    return json.loads(Path(path or SCORECARD_PATH).read_text())


def validate_scorecard(scorecard: dict[str, Any]) -> list[str]:
    """Return validation errors for a scorecard; empty is valid."""
    errors: list[str] = []

    need = make_need(errors)

    need(
        scorecard.get("schema") == SCORECARD_SCHEMA,
        f"schema must be {SCORECARD_SCHEMA}",
    )
    pin_hash = scorecard.get("pin_hash")
    need(
        isinstance(pin_hash, str) and pin_hash.startswith("sha256:"),
        "pin_hash must be recorded in the scorecard (CL-65)",
    )
    for name in (
        "detection_frozen_benchmark",
        "latency_reliability",
        "gate_and_trace",
        "evidence_exports",
        "pilot_adjudication",
        "sequence_value",
        "prevention",
        "robustness_bounds",
        "geometric",
    ):
        section = (scorecard.get("sections") or {}).get(name)
        need(section is not None, f"sections.{name} is required")
        if section is not None:
            need(
                bool(section.get("source_schema")),
                f"sections.{name} must cite its source",
            )
    decision = scorecard.get("decision") or {}
    need(
        decision.get("value") in DECISIONS, "decision.value must be a recorded decision"
    )
    if decision.get("value") == "release_with_limitations":
        need(bool(decision.get("limitations")), "decision.limitations are required")
    need(
        bool(decision.get("target_revisions")), "decision.target_revisions are required"
    )
    if decision.get("value") == "release":
        need(
            all(scorecard_targets(scorecard).values()),
            "release requires every section target to be met",
        )
        need(
            not decision.get("limitations"),
            "an unqualified release may not carry unresolved limitations",
        )
    prevention = (scorecard.get("sections") or {}).get("prevention") or {}
    need(
        (prevention.get("attempts") or {}).get("blocked_counted_as_transfer") == 0,
        "blocked artifacts must never count as transfers (C-04)",
    )
    need(
        scorecard.get("equated_with_collusion") is False,
        "scorecard must not equate outcomes with collusion (C-02)",
    )
    need(
        scorecard.get("universal_claim") is False,
        "scorecard must not make a universal claim",
    )
    return errors
