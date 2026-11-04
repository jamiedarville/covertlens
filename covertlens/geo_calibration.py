"""Development corpus and scorer-only held-out evaluation for CL-54."""

from __future__ import annotations

from typing import Any

from .geometric import SIGNAL_STRUCTURE, analyze_geometric_bytes
from .geometric_fixtures import (
    DEFAULT_HEIGHT,
    SUBFAMILIES,
    GeoFixture,
    assign_geo_splits,
    build_geo_dataset,
    validate_geo_splits,
)
from .splits import SplitPolicy
from .splits import split_for_group as _split_for_group
from .verdicts import ThresholdConfig, decide_verdict


def geometric_calibration_dataset() -> tuple[list[GeoFixture], dict[str, str]]:
    """Fixed corpus; scene lineage keeps pairs and derivatives in one split.

    Structured and unstructured encodings are both positives. This exposes
    enforcement misses on random payloads rather than redefining them benign.

    Structured pairs vary payload, letter code, grid and palette (CL-78).
    Each pair's lineage split is known before it is built, and a held-out
    pair draws its payload from the held-out pool, so no held-out payload
    is ever seen by calibration.
    """
    from .geo_benchmark import STRUCTURED_SPECS, build_structured_pair

    policy = SplitPolicy()
    fixtures = build_geo_dataset()
    for subfamily in SUBFAMILIES:
        spec = STRUCTURED_SPECS[subfamily]
        for index in range(12):
            width = spec["width"] + 3 * index
            group = f"scene:{subfamily}:{20000 + 977 * index}:{width}x{DEFAULT_HEIGHT}"
            pool = (
                "held_out"
                if _split_for_group(group, policy) == "held_out"
                else "development"
            )
            fixtures.extend(
                build_structured_pair(
                    subfamily, index, pool=pool, width_offset=3 * index
                )
            )
    assignments = assign_geo_splits(fixtures, policy)
    errors = validate_geo_splits(fixtures, assignments)
    if errors:
        raise ValueError("; ".join(errors))
    return fixtures, assignments


def evaluate_geometric_held_out(
    config: ThresholdConfig | None = None,
) -> dict[str, Any]:
    """Evaluate only held-out rows; no labels feed back into calibration."""
    from .calibration import load_frozen_thresholds
    from .geo_benchmark import benign_controls, rate
    from .pinning import dataset_hash

    frozen_config, provenance = load_frozen_thresholds()
    active = config or frozen_config
    fixtures, assignments = geometric_calibration_dataset()
    held = [f for f in fixtures if assignments[f.fixture_id] == "held_out"]
    development_ids = set(provenance["development_fixture_ids"])
    if development_ids.intersection(f.fixture_id for f in held):
        raise ValueError("held-out evaluation overlaps frozen development data")
    rows = {}
    for subfamily in SUBFAMILIES:
        encoded = [f for f in held if f.subfamily == subfamily and f.role == "encoded"]
        results = [analyze_geometric_bytes(f.data) for f in encoded]
        decisions = [decide_verdict([r["finding"]], active) for r in results]
        rows[subfamily] = {
            "fixture_ids": [f.fixture_id for f in encoded],
            "recall_triage": rate(
                sum(d.verdict.value != "log" for d in decisions), len(encoded)
            ),
            "recall_enforcement": rate(
                sum(d.delivery == "withhold" for d in decisions), len(encoded)
            ),
            "recall_structure": rate(
                sum(r["classification"] == SIGNAL_STRUCTURE for r in results),
                len(encoded),
            ),
        }
    charts = [c for c in benign_controls(12) if c["kind"] == "chart"]
    controls = {}
    for name, context in (
        ("undeclared", None),
        ("declared_height", {"declared_channels": ["height"]}),
    ):
        reports = [
            analyze_geometric_bytes(c["data"], declared_context=context) for c in charts
        ]
        decisions = [decide_verdict([r["finding"]], active) for r in reports]
        controls[name] = {
            "false_structure": rate(
                sum(r["classification"] == SIGNAL_STRUCTURE for r in reports),
                len(reports),
            ),
            "false_enforcement": rate(
                sum(d.delivery == "withhold" for d in decisions), len(decisions)
            ),
        }
    return {
        "schema": "covertlens.geometric-held-out",
        "schema_version": 1,
        "threshold_config_version": active.version,
        "held_out_only": True,
        "development_overlap": False,
        "dataset_hash": dataset_hash(held),
        "fixture_ids": sorted(f.fixture_id for f in held),
        "subfamilies": rows,
        "chart_controls": controls,
        "chart_control_hashes": [c["content_hash"] for c in charts],
        "universal_claim": False,
        "limitations": [
            "Procedural synthetic PNG scenes only; no natural-image or JPEG calibration claim.",
            "Small lineage-held-out sample; held-out structured payloads come from a pool calibration never sees, but the codes and grids are the same families.",
            "The A-H letter-position height code is weak with the 313-word trigram model: many real A-H words do not beat the shuffle null.",
            "Unstructured encoded payloads may flag but do not establish structure for enforcement.",
        ],
    }
