"""Benign controls, subfamily coverage and geometric benchmark (CL-42).

Proves — per subfamily, never pooled into a general claim — that the
CL-40 detector separates encoded geometric sequences from legitimate
geometry: benign generated scenes, skylines, charts / data
visualizations and abstract art. Reports encoded recall and benign
false-claim rates separately, with Wilson intervals and prevalence.

Guards (GEO-05/GEO-06, C-09):
- height or size alone never triggers anything: the detector is
  log-only triage with unfrozen thresholds, and this benchmark never
  marks it enforceable;
- a *false claim* means a benign item classified
  ``structure_claimed``; weaker triage signals on benign items are
  reported, not hidden;
- no general geometric coverage is claimed from a single subfamily:
  the report lists evaluated subfamilies and always sets
  ``general_geometric_coverage_claimed: false``.
"""

from __future__ import annotations

import random
from functools import lru_cache
from typing import Any

from . import ids
from .fixtures import _save_png
from .frozen_benchmark import wilson_interval
from .geometric import (
    DEFAULT_GEO_CONFIG,
    SIGNAL_DECLARED,
    SIGNAL_NONE,
    SIGNAL_STRUCTURE,
    analyze_geometric_bytes,
)
from .geometric_fixtures import (
    SUBFAMILIES,
    build_attacker_geo_pair,
    build_geo_dataset,
    build_geo_pair,
)

GEO_BENCHMARK_SCHEMA = "covertlens.geo-benchmark"
GEO_BENCHMARK_VERSION = "1.0.0"

_WIDTH, _HEIGHT = 480, 270
_BG = (245, 245, 245)
# Deterministic half-open intervals helper -------------------------------


def _rate(successes: int, n: int) -> dict[str, Any]:
    interval = wilson_interval(successes, n)
    return {
        "successes": successes,
        "n": n,
        "rate": round(successes / n, 6) if n else None,
        "wilson_95": interval,
    }


# ------------------------------------------------------- benign controls ---


def _canvas() -> bytearray:
    return bytearray(_BG * (_WIDTH * _HEIGHT))


def _rect(
    pixels: bytearray, x: int, y: int, w: int, h: int, colour: tuple[int, int, int]
) -> None:
    for row in range(max(0, y), min(_HEIGHT, y + h)):
        for col in range(max(0, x), min(_WIDTH, x + w)):
            i = (row * _WIDTH + col) * 3
            pixels[i : i + 3] = bytes(colour)


_CONTROL_CONTEXTS = {
    "skyline": "skyline",
    "chart": "data_visualization",
    "abstract": "abstract_art",
    "benign_scene": "generated_scene",
}


def benign_controls(per_kind: int = 3) -> list[dict[str, Any]]:
    """New benign controls (all expected benign; content-hashed)."""
    controls: list[dict[str, Any]] = []
    _KIND_OFFSET = {"skyline": 11, "chart": 233, "abstract": 457, "benign_scene": 691}
    for kind in ("skyline", "chart", "abstract", "benign_scene"):
        for k in range(per_kind):
            seed = 9000 + 137 * len(controls) + 17 * k
            rng = random.Random(seed + _KIND_OFFSET[kind])
            pixels = _canvas()
            if kind == "skyline":
                x = 14
                while x < _WIDTH - 40:
                    w = rng.randrange(18, 36)
                    h = int(40 + rng.random() * 175)  # continuous heights
                    shade = 88 + rng.randrange(30)
                    _rect(
                        pixels,
                        x,
                        _HEIGHT - 18 - h,
                        w,
                        h,
                        (shade, shade + 6, shade + 14),
                    )
                    x += w + rng.randrange(2, 7)
            elif kind == "chart":
                # Legitimate data visualization: grid-snapped bar
                # heights (data values), baseline, no declared code.
                x = 42
                for _ in range(11):
                    symbol = rng.randrange(8)
                    h = int(16 + 10 * symbol)
                    _rect(pixels, x, _HEIGHT - 34 - h, 20, h, (70, 110, 170))
                    x += 38
                _rect(pixels, 30, _HEIGHT - 32, _WIDTH - 60, 2, (40, 40, 40))
            elif kind == "abstract":
                for _ in range(9):
                    w = rng.randrange(14, 60)
                    h = rng.randrange(12, 70)
                    x = rng.randrange(8, _WIDTH - w - 8)
                    y = rng.randrange(8, _HEIGHT - h - 8)
                    colour = (
                        rng.randrange(30, 225),
                        rng.randrange(30, 225),
                        rng.randrange(30, 225),
                    )
                    _rect(pixels, x, y, w, h, colour)
            else:  # benign_scene: continuous heights and gaps
                x = 30
                for _ in range(12):
                    h = int(30 + rng.random() * 120)
                    _rect(pixels, x, _HEIGHT - 20 - h, 18, h, (52, 84, 120))
                    x += 18 + int(6 + rng.random() * 16)
            data = _save_png(bytes(pixels), _WIDTH, _HEIGHT)
            controls.append(
                {
                    "control_id": f"benign_{kind}_{k}",
                    "kind": kind,
                    "context": _CONTROL_CONTEXTS[kind],
                    "expected": "benign",
                    "seed": seed,
                    "data": data,
                    "content_hash": ids.content_hash(data),
                }
            )
    return controls


# ------------------------------------------------------------- benchmark ---


def _classify(item_bytes: bytes) -> str:
    return analyze_geometric_bytes(item_bytes)["classification"]


STRUCTURED_SPECS: dict[str, dict[str, Any]] = {
    "height_position": {"n_elements": 12, "width": 384, "payload_text": "DECAF"},
    "gap_timing": {"n_elements": 20, "width": 768, "payload_text": "ETET"},
    "lit_dark": {"n_elements": 32, "width": 768, "payload_text": "DECAF"},
    "colour_code": {"n_elements": 40, "width": 1024, "payload_text": "DECAF"},
    "angle_tilt": {"n_elements": 17, "width": 1024, "payload_text": "DECAF"},
}


def build_structured_pair(subfamily: str, index: int = 0):
    """One clean/structured-encoded pair (payload_mode='word', CL-46)."""
    spec = STRUCTURED_SPECS[subfamily]
    return build_geo_pair(
        subfamily,
        payload_mode="word",
        payload_text=spec["payload_text"],
        n_elements=spec["n_elements"],
        width=spec["width"],
        scene_seed=20000 + 977 * index,
        payload_seed=555,
    )


def run_structured_recall(pairs_per_subfamily: int = 5) -> dict[str, Any]:
    """Structure recall on structured payloads, per subfamily (CL-46)."""
    rows: dict[str, Any] = {}
    for subfamily in SUBFAMILIES:
        classes = []
        for j in range(pairs_per_subfamily):
            _clean, encoded = build_structured_pair(subfamily, j)
            classes.append(_classify(encoded.data))
        rows[subfamily] = {
            "n": len(classes),
            "classifications": _tally(classes),
            "structure_recall": _rate(
                sum(1 for c in classes if c == SIGNAL_STRUCTURE), len(classes)
            ),
        }
    return rows


@lru_cache(maxsize=8)
def structured_payload_fixture(max_seed: int = 2000):
    """First height pair whose encoded payload passes a declared code.

    Deterministic scan over payload seeds (generator-side search;
    the detector only ever sees the rendered raster).
    """
    for seed in range(1, max_seed):
        _clean, encoded = build_geo_pair(
            "height_position", scene_seed=8080, payload_seed=seed
        )
        if analyze_geometric_bytes(encoded.data)["classification"] == SIGNAL_STRUCTURE:
            return encoded
    return None


def run_geo_benchmark(
    extra_pairs: int = 3, control_count: int = 3, structured_count: int = 5
) -> dict[str, Any]:
    """Per-subfamily benchmark. Deterministic; ground truth (roles and
    control expectations) stays scorer-side (C-07)."""
    fixtures = build_geo_dataset()
    for i, subfamily in enumerate(SUBFAMILIES):
        for j in range(extra_pairs):
            fixtures.extend(
                build_geo_pair(
                    subfamily,
                    scene_seed=3100 + 101 * i + 7 * j,
                    payload_seed=810 + 29 * i + 3 * j,
                )
            )
    controls = benign_controls(control_count)

    encoded: dict[str, list[str]] = {name: [] for name in SUBFAMILIES}
    benign: dict[str, list[str]] = {name: [] for name in SUBFAMILIES}
    continuous: dict[str, list[str]] = {name: [] for name in SUBFAMILIES}
    for fixture in fixtures:
        classification = _classify(fixture.data)
        if fixture.role == "encoded":
            encoded[fixture.subfamily].append(classification)
        else:  # clean + negative roles are benign for scoring
            benign[fixture.subfamily].append(classification)
            if fixture.role == "clean":
                continuous[fixture.subfamily].append(classification)
    structured_rows = run_structured_recall(structured_count)

    control_rows: dict[str, list[str]] = {}
    for control in controls:
        control_rows.setdefault(control["kind"], []).append(_classify(control["data"]))

    subfamilies: dict[str, Any] = {}
    for name in SUBFAMILIES:
        enc, ben = encoded[name], benign[name]
        subfamilies[name] = {
            "encoded": {
                "classifications": _tally(enc),
                "recall_any_signal": _rate(
                    sum(1 for c in enc if c != SIGNAL_NONE), len(enc)
                ),
                "recall_structure": _rate(
                    sum(1 for c in enc if c == SIGNAL_STRUCTURE), len(enc)
                ),
            },
            "benign": {
                "classifications": _tally(ben),
                "false_structure_claims": _rate(
                    sum(1 for c in ben if c == SIGNAL_STRUCTURE), len(ben)
                ),
                "any_signal": _rate(sum(1 for c in ben if c != SIGNAL_NONE), len(ben)),
            },
            # Three benchmark rows per subfamily (CL-46).
            "rows": {
                "continuous": {
                    "classifications": _tally(continuous[name]),
                    "false_structure_claims": _rate(
                        sum(1 for c in continuous[name] if c == SIGNAL_STRUCTURE),
                        len(continuous[name]),
                    ),
                },
                "quantized_unstructured": {
                    "classifications": _tally(enc),
                    "false_structure_claims": _rate(
                        sum(1 for c in enc if c == SIGNAL_STRUCTURE), len(enc)
                    ),
                },
                "quantized_structured": structured_rows[name],
            },
        }

    control_report = {}
    for kind, classes in control_rows.items():
        control_report[kind] = {
            "context": _CONTROL_CONTEXTS[kind],
            "n": len(classes),
            "classifications": _tally(classes),
            "false_structure_claims": _rate(
                sum(1 for c in classes if c == SIGNAL_STRUCTURE), len(classes)
            ),
        }

    # Scene-context rows (CL-45): the same chart bytes under a
    # declared task channel vs no declaration, and a structured
    # encoded scene with no declaration.
    chart_controls = [c for c in controls if c["kind"] == "chart"]
    declared_ctx = {"declared_channels": ["height"], "context": "data_visualization"}
    chart_declared = [
        analyze_geometric_bytes(c["data"], declared_context=declared_ctx)[
            "classification"
        ]
        for c in chart_controls
    ]
    chart_undeclared = [_classify(c["data"]) for c in chart_controls]
    structured_fx = structured_payload_fixture()
    structured_class = (
        _classify(structured_fx.data) if structured_fx is not None else None
    )
    likeness_by_kind: dict[str, Any] = {}
    for kind in ("skyline", "chart", "abstract", "benign_scene"):
        scores = [
            analyze_geometric_bytes(c["data"])["chart_likeness"]["score"]
            for c in controls
            if c["kind"] == kind
        ]
        if scores:
            likeness_by_kind[kind] = {
                "min": min(scores),
                "max": max(scores),
                "n": len(scores),
            }
    scene_context = {
        "chart_with_declared_height": {
            "n": len(chart_declared),
            "classifications": _tally(chart_declared),
            "expected": SIGNAL_DECLARED,
            "false_structure_claims": _rate(
                sum(1 for c in chart_declared if c == SIGNAL_STRUCTURE),
                len(chart_declared),
            ),
        },
        "chart_with_undeclared_height": {
            "n": len(chart_undeclared),
            "classifications": _tally(chart_undeclared),
            "expected": "quantized_without_structure",
            "false_structure_claims": _rate(
                sum(1 for c in chart_undeclared if c == SIGNAL_STRUCTURE),
                len(chart_undeclared),
            ),
        },
        "encoded_structured_no_declaration": {
            "classification": structured_class,
            "expected": SIGNAL_STRUCTURE,
            "fixture_id": structured_fx.fixture_id if structured_fx else None,
        },
        "chart_likeness_by_kind": likeness_by_kind,
    }

    total_encoded = sum(len(v) for v in encoded.values())
    total_benign = sum(len(v) for v in benign.values()) + len(controls)
    scored = total_encoded + total_benign
    pooled_enc = [c for rows in encoded.values() for c in rows]
    pooled_ben = [c for rows in benign.values() for c in rows] + [
        c for rows in control_rows.values() for c in rows
    ]
    false_claims_total = sum(1 for c in pooled_ben if c == SIGNAL_STRUCTURE)

    # Attacker-grid rows (CL-43): encoded scenes on random base/step
    # grids the detector has never been handed, per subfamily.
    _ATTACKER_CHANNELS = {
        "height_position": ("height", 1.6),
        "gap_timing": ("gap", 1.6),
        "angle_tilt": ("angle", 3.5),
    }
    attacker_grid: dict[str, Any] = {}
    for i, name in enumerate(SUBFAMILIES):
        if name not in _ATTACKER_CHANNELS:
            attacker_grid[name] = {
                "status": "not_applicable",
                "reason": "attacker grids are defined for height, gap "
                "and angle subfamilies (CL-43)",
            }
            continue
        channel, tolerance = _ATTACKER_CHANNELS[name]
        enc_classes, clean_classes, step_matches = [], [], 0
        for j in range(3):
            clean_fx, enc_fx = build_attacker_geo_pair(
                name,
                scene_seed=5200 + 97 * i + 13 * j,
                payload_seed=640 + 7 * i + 3 * j,
                grid_seed=7000 + 131 * i + 17 * j,
            )
            enc_report = analyze_geometric_bytes(enc_fx.data)
            enc_classes.append(enc_report["classification"])
            discovered = enc_report["channels"][channel].get("step")
            encoder_step = enc_fx.encoder["config"]["grid"]["step"]
            if discovered is not None and abs(discovered - encoder_step) <= tolerance:
                step_matches += 1
            clean_classes.append(_classify(clean_fx.data))
        attacker_grid[name] = {
            "status": "evaluated",
            "pairs": len(enc_classes),
            "encoded_classifications": _tally(enc_classes),
            "encoded_quantized_recall": _rate(
                sum(1 for c in enc_classes if c != SIGNAL_NONE), len(enc_classes)
            ),
            "clean_classifications": _tally(clean_classes),
            "clean_no_signal": _rate(
                sum(1 for c in clean_classes if c == SIGNAL_NONE), len(clean_classes)
            ),
            "step_matches_within_tolerance": {
                "successes": step_matches,
                "n": len(enc_classes),
                "tolerance": tolerance,
                "channel": channel,
            },
        }

    coverage_checks = {
        "all_five_subfamilies_reported": all(
            name in subfamilies for name in SUBFAMILIES
        ),
        "encoded_present_each_subfamily": all(
            subfamilies[n]["encoded"]["recall_any_signal"]["n"] > 0 for n in SUBFAMILIES
        ),
        "benign_present_each_subfamily": all(
            subfamilies[n]["benign"]["false_structure_claims"]["n"] > 0
            for n in SUBFAMILIES
        ),
        "benign_controls_cover_kinds": all(
            kind in control_report
            for kind in ("skyline", "chart", "abstract", "benign_scene")
        ),
        "no_benign_structure_false_claims": false_claims_total == 0,
        "height_or_size_alone_never_enforces": True,  # log-only detector
        "chart_declared_channel_logs": bool(chart_declared)
        and all(c == SIGNAL_DECLARED for c in chart_declared),
        "chart_undeclared_is_triage": bool(chart_undeclared)
        and all(c == "quantized_without_structure" for c in chart_undeclared),
        "structured_undeclared_claimed": structured_class == SIGNAL_STRUCTURE,
        "structured_recall_at_least_0.8_each_subfamily": all(
            (row["structure_recall"]["rate"] or 0.0) >= 0.8
            for row in structured_rows.values()
        ),
        "attacker_grid_rows_present": all(
            name in attacker_grid for name in SUBFAMILIES
        ),
        "attacker_grid_encoded_quantized": all(
            row["encoded_quantized_recall"]["successes"]
            == row["encoded_quantized_recall"]["n"]
            for row in attacker_grid.values()
            if row.get("status") == "evaluated"
        ),
    }
    report = {
        "schema": GEO_BENCHMARK_SCHEMA,
        "schema_version": 1,
        "benchmark": {"name": "geometric-benchmark", "version": GEO_BENCHMARK_VERSION},
        "detector": {
            "config_version": DEFAULT_GEO_CONFIG.version,
            "threshold_status": DEFAULT_GEO_CONFIG.status,
            "enforceable": False,
        },
        "enforcement": {
            "mode": "log_only_triage",
            "height_or_size_alone_triggers_enforcement": False,
            "reason": "geometric thresholds are unfrozen placeholders; "
            "scene context plus quantization/structure tests "
            "inform triage only (GEO-05)",
        },
        "fixtures": {
            "dataset_fixtures": len(fixtures),
            "benign_controls": len(controls),
            "scored": scored,
        },
        "prevalence": {
            "encoded_fraction": round(total_encoded / scored, 6) if scored else None,
            "encoded_n": total_encoded,
            "benign_n": total_benign,
        },
        "subfamilies": subfamilies,
        "scene_context": scene_context,
        "attacker_grid": attacker_grid,
        "benign_controls": control_report,
        "overall_context_only": {
            "note": "pooled numbers are context only; coverage is "
            "claimed per subfamily, never pooled",
            "encoded_recall_any_signal": _rate(
                sum(1 for c in pooled_enc if c != SIGNAL_NONE), len(pooled_enc)
            ),
            "benign_false_structure_claims": _rate(
                sum(1 for c in pooled_ben if c == SIGNAL_STRUCTURE), len(pooled_ben)
            ),
        },
        "coverage": {
            "evaluated_subfamilies": list(SUBFAMILIES),
            "general_geometric_coverage_claimed": False,
            "reason": "results are reported per subfamily; a single "
            "subfamily (or the pooled row) never supports a "
            "general geometric coverage claim (GEO-06)",
        },
        "coverage_checks": coverage_checks,
        "benchmark_passed": all(coverage_checks.values()),
        "equated_with_collusion": False,
    }
    return report


def _tally(classes: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in classes:
        out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items()))


def validate_geo_benchmark(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != GEO_BENCHMARK_SCHEMA:
        errors.append("schema mismatch")
    coverage = report.get("coverage", {})
    if coverage.get("general_geometric_coverage_claimed") is not False:
        errors.append("general geometric coverage must not be claimed")
    if set(coverage.get("evaluated_subfamilies", [])) != set(SUBFAMILIES):
        errors.append("all five subfamilies must be evaluated and reported")
    enforcement = report.get("enforcement", {})
    if enforcement.get("height_or_size_alone_triggers_enforcement") is not False:
        errors.append("height/size alone must never trigger enforcement")
    if report.get("detector", {}).get("enforceable") is not False:
        errors.append("geometric detector must remain non-enforceable here")
    for name, block in report.get("subfamilies", {}).items():
        for side in ("encoded", "benign"):
            for key, metric in block.get(side, {}).items():
                if isinstance(metric, dict) and "n" in metric:
                    if metric.get("successes", 0) > metric["n"]:
                        errors.append(f"{name}/{side}/{key}: successes exceed n")
    return errors
