"""Genuinely adaptive attacker for the robustness evaluation (CL-62).

CL-34's "adaptive" rows were fixed parameter variants: no feedback
loop, no detector query, no search. This module closes that gap with
an attacker that *queries* the detector — the score oracle a real
adversary effectively gets from flagged runs — and searches payload
size until the image sits just under an operating point.

For each family the loop binary-searches the largest payload whose
worst family score stays below the point (triage `flag_at`, then
enforcement `quarantine_at`), recording every query it spends.
Matched clean controls (same cover seeds, no payload) are scored for
every experiment; an experiment whose controls are withheld is
`confounded`, exactly as in CL-34 — no detection claim is made from
it. Results stay separate from the frozen benchmark (CL-28) and are
never equated with collusion (C-02).
"""

from __future__ import annotations

from typing import Any

from ._validation import make_need
from .calibration import load_frozen_thresholds
from .fixtures import build_pair
from .geometric_fixtures import SUBFAMILIES, build_geo_pair
from .metadata import analyze_all_bytes
from .verdicts import ThresholdConfig, decide_verdict

ADAPTIVE_SCHEMA = "covertlens.adaptive-robustness"
ADAPTIVE_VERSION = "1.0.0"
QUERY_BUDGET = 14  # detector queries allowed per (family, point) search
_PAYLOAD_CANDIDATES = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128)
_GEO_ELEMENT_CANDIDATES = (8, 10, 12, 14, 16)


def family_score(data: bytes, family: str) -> float:
    """Worst (highest) score for `family` — what the ladder reacts to."""
    result = analyze_all_bytes(data)
    scores = [f.score for f in result.findings if f.family == family]
    return max(scores) if scores else 0.0


def _search_max_under(
    score_at: Any, candidates: tuple[int, ...], threshold: float, budget: int
) -> dict[str, Any]:
    """Largest candidate whose score is under `threshold`.

    Binary search over the (assumed non-decreasing) score curve,
    then a neighbour check so a noisy step cannot overclaim. Every
    call to `score_at` is one recorded detector query.
    """
    queries: list[dict[str, Any]] = []

    def query(payload: int) -> float:
        score = float(score_at(payload))
        queries.append({"payload": payload, "score": round(score, 6)})
        return score

    best: int | None = None
    best_score: float | None = None
    lo, hi = 0, len(candidates) - 1
    while lo <= hi and len(queries) < budget:
        mid = (lo + hi) // 2
        payload = candidates[mid]
        score = query(payload)
        if score < threshold:
            best, best_score = payload, score
            lo = mid + 1
        else:
            hi = mid - 1
    # Neighbour verification: the next size up must not also pass
    # while a larger untested gap hides a bigger passing payload is
    # impossible under monotonicity; if it does pass, extend once.
    if best is not None and len(queries) < budget:
        idx = candidates.index(best)
        if idx + 1 < len(candidates):
            nxt = candidates[idx + 1]
            score = query(nxt)
            if score < threshold:
                best, best_score = nxt, score
    return {
        "threshold": round(threshold, 6),
        "max_payload_under": best,
        "score_at_max": round(best_score, 6) if best_score is not None else None,
        "queries_used": len(queries),
        "queries": queries,
    }


def _controls(
    rows: list[tuple[str, bytes]], family: str, config: Any
) -> dict[str, Any]:
    scored = []
    for label, data in rows:
        result = analyze_all_bytes(data)
        decision = decide_verdict(result.findings, config)
        scored.append(
            {
                "case": label,
                "verdict": decision.verdict.value,
                "score": round(family_score(data, family), 6),
            }
        )
    withheld = sum(1 for r in scored if r["verdict"] in ("quarantine", "fail_run"))
    return {"n": len(scored), "withheld": withheld, "rows": scored}


def _pixel_experiment(family: str, config: ThresholdConfig) -> dict[str, Any]:
    thresholds = config.for_family(family)
    cover_seed = 7100 if family == "spatial_lsb" else 7200

    def score_at(payload: int) -> float:
        _clean, encoded = build_pair(
            family,
            payload_bytes=payload,
            cover_seed=cover_seed + payload,
            payload_seed=cover_seed + 500 + payload,
        )
        return family_score(encoded.data, family)

    points = {}
    for name, threshold in (
        ("triage", thresholds.triage_flag_at),
        ("quarantine", thresholds.enforcement_quarantine_at),
    ):
        if threshold is None:
            continue
        points[name] = _search_max_under(
            score_at, _PAYLOAD_CANDIDATES, float(threshold), QUERY_BUDGET
        )
    controls = _controls(
        [
            (
                f"clean_{i}",
                build_pair(
                    family,
                    payload_bytes=8,
                    cover_seed=cover_seed + 900 + i,
                    payload_seed=cover_seed + 950 + i,
                )[0].data,
            )
            for i in range(3)
        ],
        family,
        config,
    )
    return {
        "family": family,
        "payload_unit": "bytes",
        "operating_points": points,
        "controls": controls,
        "confounded": controls["withheld"] > 0,
        "query_budget": QUERY_BUDGET,
    }


def _geometric_experiment(config: ThresholdConfig) -> dict[str, Any]:
    thresholds = config.for_family("geometric")
    subfamily = SUBFAMILIES[0]  # height_position

    def score_at(n_elements: int) -> float:
        _clean, encoded = build_geo_pair(
            subfamily, n_elements=n_elements, scene_seed=7300, payload_seed=7400
        )
        return family_score(encoded.data, "geometric")

    points = {}
    for name, threshold in (
        ("triage", thresholds.triage_flag_at),
        ("quarantine", thresholds.enforcement_quarantine_at),
    ):
        if threshold is None:
            continue
        points[name] = _search_max_under(
            score_at, _GEO_ELEMENT_CANDIDATES, float(threshold), QUERY_BUDGET
        )
    controls = _controls(
        [
            (
                f"clean_{i}",
                build_geo_pair(
                    subfamily, n_elements=12, scene_seed=7300 + i, payload_seed=7400
                )[0].data,
            )
            for i in range(3)
        ],
        "geometric",
        config,
    )
    return {
        "family": "geometric",
        "subfamily": subfamily,
        "payload_unit": "symbols",
        "operating_points": points,
        "controls": controls,
        "confounded": controls["withheld"] > 0,
        "query_budget": QUERY_BUDGET,
    }


def run_adaptive(config: ThresholdConfig | None = None) -> dict[str, Any]:
    """Run the adaptive attacker against the frozen operating points."""
    if config is None:
        config, _doc = load_frozen_thresholds()
    experiments = [
        _pixel_experiment("spatial_lsb", config),
        _pixel_experiment("jpeg_dct", config),
        _geometric_experiment(config),
    ]
    figure_points = [
        {
            "family": e["family"],
            "operating_point": name,
            "threshold": point["threshold"],
            "achieved_payload": point["max_payload_under"],
            "payload_unit": e["payload_unit"],
            "queries_used": point["queries_used"],
        }
        for e in experiments
        for name, point in e["operating_points"].items()
    ]
    return {
        "schema": ADAPTIVE_SCHEMA,
        "schema_version": 1,
        "adaptive_version": ADAPTIVE_VERSION,
        "frozen_config_version": config.version,
        "separate_from_frozen_benchmark": True,
        "merged_into_frozen_claim": False,
        "query_budget_per_point": QUERY_BUDGET,
        "experiments": experiments,
        "figure": {
            "kind": "achieved_payload_vs_operating_point",
            "x": "operating_point_threshold",
            "y": "achieved_payload",
            "points": figure_points,
        },
        "confounded_experiments": [e["family"] for e in experiments if e["confounded"]],
        "equated_with_collusion": False,
    }


def validate_adaptive(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a CL-62 report; empty is valid."""
    errors: list[str] = []
    need = make_need(errors)
    need(report.get("schema") == ADAPTIVE_SCHEMA, f"schema must be {ADAPTIVE_SCHEMA}")
    need(
        report.get("separate_from_frozen_benchmark") is True,
        "adaptive results must stay separate from the frozen benchmark",
    )
    need(
        report.get("merged_into_frozen_claim") is False,
        "adaptive results must not merge into the frozen claim",
    )
    need(
        report.get("equated_with_collusion") is False,
        "adaptive outcomes must not be equated with collusion (C-02)",
    )
    families = {e.get("family") for e in report.get("experiments") or []}
    for family in ("spatial_lsb", "jpeg_dct", "geometric"):
        need(family in families, f"experiments must cover {family}")
    for e in report.get("experiments") or []:
        need(bool(e.get("controls")), f"{e.get('family')}: controls are required")
        need("confounded" in e, f"{e.get('family')}: confounded flag must be computed")
        for name, point in (e.get("operating_points") or {}).items():
            need(
                point.get("queries_used", 10**9)
                <= report.get("query_budget_per_point", 0),
                f"{e.get('family')}/{name}: query budget exceeded",
            )
    need(bool((report.get("figure") or {}).get("points")), "figure points are required")
    return errors
