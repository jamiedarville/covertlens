"""Development corpus and scorer-only held-out evaluation for CL-54."""

from __future__ import annotations

from typing import Any

from .geometric import SIGNAL_STRUCTURE, analyze_geometric_bytes
from .geometric_fixtures import (
    SUBFAMILIES,
    GeoFixture,
    assign_geo_splits,
    build_geo_dataset,
    build_geo_pair,
    validate_geo_splits,
)
from .verdicts import ThresholdConfig, decide_verdict


def geometric_calibration_dataset() -> tuple[list[GeoFixture], dict[str, str]]:
    """Fixed corpus; scene lineage keeps pairs and derivatives in one split.

    Structured and unstructured encodings are both positives. This exposes
    enforcement misses on random payloads rather than redefining them benign.
    """
    from .geo_benchmark import STRUCTURED_SPECS

    fixtures = build_geo_dataset()
    for subfamily in SUBFAMILIES:
        for index in range(12):
            spec = STRUCTURED_SPECS[subfamily]
            fixtures.extend(
                build_geo_pair(
                    subfamily,
                    payload_mode="word",
                    payload_text=spec["payload_text"],
                    n_elements=spec["n_elements"],
                    width=spec["width"] + 3 * index,
                    scene_seed=20000 + 977 * index,
                    payload_seed=555,
                )
            )
    assignments = assign_geo_splits(fixtures)
    errors = validate_geo_splits(fixtures, assignments)
    if errors:
        raise ValueError("; ".join(errors))
    return fixtures, assignments


def evaluate_geometric_held_out(
    config: ThresholdConfig | None = None,
) -> dict[str, Any]:
    """Evaluate only held-out rows; no labels feed back into calibration."""
    from .calibration import load_frozen_thresholds
    from .geo_benchmark import _rate, benign_controls
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
            "recall_triage": _rate(
                sum(d.verdict.value != "log" for d in decisions), len(encoded)
            ),
            "recall_enforcement": _rate(
                sum(d.delivery == "withhold" for d in decisions), len(encoded)
            ),
            "recall_structure": _rate(
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
            "false_structure": _rate(
                sum(r["classification"] == SIGNAL_STRUCTURE for r in reports),
                len(reports),
            ),
            "false_enforcement": _rate(
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
            "Small lineage-held-out sample; repeated structured words are not held-out codebooks or vocabulary.",
            "Unstructured encoded payloads may flag but do not establish structure for enforcement.",
        ],
    }
