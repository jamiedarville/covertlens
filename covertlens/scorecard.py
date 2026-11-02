"""MVP release scorecard and owner decision (CL-35, OPS-08).

Assembles the release evidence from the already-merged measured
reports — CL-28 frozen benchmark, CL-29 latency/reliability,
CL-30 pilot, CL-31 ablations/prevention, CL-32 route/trace audit,
CL-33 export verification, CL-34 robustness bounds — citing each
figure to its source report schema and contract doc. Figures are
extracted from those reports at build time, never recomputed by
different code, so the scorecard cannot drift from its evidence.

The owner decision is recorded as data: `release_with_limitations`
for this MVP, with the limitations and the target revisions they
force. A scorecard with unresolved limitations may not record an
unqualified `release`. Nothing in the scorecard equates a detector
outcome with collusion (C-02).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCORECARD_SCHEMA = "covertlens.release-scorecard"
SCORECARD_VERSION = "1.3.0"
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
    from .pilot import run_pilot
    from .review_export import run_export_verification
    from .robustness import run_robustness
    from .route_audit import run_route_audit

    frozen = run_frozen_evaluation()
    latency = run_reliability_report()
    pilot = run_pilot(
        adjudications={
            "uns-1": {
                "disposition": "suspected",
                "note": "strong DCT evidence; no independent basis yet",
            },
            "uns-5": {"disposition": "benign", "note": "clean control pattern"},
        }
    )
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
        "Detection coverage is limited to calibrated payload bands "
        "(low/medium) and densities on gradient_noise covers; the "
        "high band rests on 1-2 held-out positives per family.",
        "Clean smooth/blocks covers fall outside the stability "
        "claim (smooth clean PNGs false-fail; blocks JPEGs "
        "occasionally withhold).",
        "JPEG latency misses the 2 s proposal at >=~1 MP and at "
        "concurrency 4; the 20 MP JPEG envelope is unmeasured.",
        "Adaptive reduced-rate, larger-image, blocks-cover and "
        "allowed-keyword-metadata attempts evade enforcement "
        "(CL-34); allowed-keyword evasion needs a policy change.",
        "Held-out samples are tiny: targets are met on point "
        "estimates with wide Wilson intervals (CL-28).",
        "R-06 preview derivatives have no dedicated gate API; "
        "derivative enforcement is procedural (CL-32).",
        "Context/sequence evidence is a triage aid only: combined "
        "scoring dilutes image evidence (CL-31).",
        "The geometric family has frozen synthetic-scene points (CL-54): "
        "quantization alone permits delivery, structure claims rest on "
        "declared codes only, and no general geometric coverage "
        "is claimed from any single subfamily.",
    ]
    target_revisions = [
        {
            "target": "Clean-run false failures <=1% (universal covers)",
            "revision": "Scoped to gradient_noise covers; low-texture "
            "covers need detector recalibration first.",
            "reason": "CL-28 probes: clean smooth PNGs false-fail, "
            "blocks JPEGs occasionally withhold.",
        },
        {
            "target": "P95 <=2 s for <=10 MB/20 MP at concurrency 4",
            "revision": "Holds for PNG (incl. 20 MP) and JPEG up to "
            "medium sequential; JPEG >=1 MP and the "
            "20 MP JPEG envelope deferred pending a "
            "faster JPEG path or a re-frozen runtime limit.",
            "reason": "CL-29 measurements: large/concurrent JPEG "
            "reaches the explicit 2 s deadline.",
        },
        {
            "target": ">=95% recall per family",
            "revision": "Claimed only within calibrated bands and "
            "suite-like payload densities; reduced-rate "
            "and larger-image attempts are out of claim.",
            "reason": "CL-28 held-out is high-band only; CL-34 "
            "adaptive/larger-image probes evade.",
        },
        {
            "target": "Metadata payload detection",
            "revision": "Declared-keyword payloads only; allowed-"
            "keyword payloads require a policy change "
            "before any enforcement claim.",
            "reason": "CL-34 adaptive probe scores 0 under "
            "Description/Title keywords (CL-23 design).",
        },
    ]
    return {
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
                        }
                        for family, block in families.items()
                    },
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
                    "interpretation": "enforcement stays image-led; "
                    "context is a triage aid (CL-31)",
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
                    "enforceable": True,
                    "held_out_evaluation": geometric_frozen,
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
            "value": "release_with_limitations",
            "decision_owner": "MVP release owner",
            "recorded_in": "CL-35 (this scorecard) and the CL-35 Jira decision comment",
            "rationale": [
                "Frozen enforcement is correct where claimed: gate, "
                "trace, export and prevention invariants hold with "
                "zero unauthorized serves and zero blocked transfers.",
                "Detection targets are met only inside narrowed, "
                "measured coverage; the misses (JPEG latency, "
                "low-density/adaptive evasion, low-texture covers) "
                "are documented with target revisions rather than "
                "waived.",
                "An unqualified release would overstate the "
                "evidence; no-release would discard a working, "
                "auditable enforcement core.",
            ],
            "limitations": limitations,
            "target_revisions": target_revisions,
        },
        "equated_with_collusion": False,
        "universal_claim": False,
    }


def load_scorecard(path: str | Path | None = None) -> dict[str, Any]:
    """Load the published scorecard artifact."""
    return json.loads(Path(path or SCORECARD_PATH).read_text())


def validate_scorecard(scorecard: dict[str, Any]) -> list[str]:
    """Return validation errors for a scorecard; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(
        scorecard.get("schema") == SCORECARD_SCHEMA,
        f"schema must be {SCORECARD_SCHEMA}",
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
    need(bool(decision.get("limitations")), "decision.limitations are required")
    need(
        bool(decision.get("target_revisions")), "decision.target_revisions are required"
    )
    if decision.get("value") == "release":
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
