"""Frozen synthetic benchmark + clean-run stability (CL-28, CL-68, OPS-03).

Evaluates the shipped frozen config exactly as shipped (CL-68:
held-out data adds the banded suite, with at least 20 positives per
family, band and texture where constructible, and stability runs on
all three cover textures):

- **Held-out benchmark.** Only fixtures assigned `held_out` by CL-10
  are scored — they were excluded from CL-27 calibration (the report
  asserts the evaluated ids are disjoint from the calibration
  development ids). Per family and per payload band: recall at the
  triage point, precision at the enforcement (quarantine) point,
  prevalence, and Wilson score intervals. Scores/outcomes are gate
  evidence, never collusion (C-02).
- **Clean-run stability.** Independent clean artifacts (fresh cover
  seeds never used by any fixture suite) are run through the frozen
  ladder; a *false failure* is a `fail_run` verdict on a clean run.
  The ≤1% target is judged on point estimate with n ≥ 300 runs.

Missed targets are not hidden: where the frozen points fail outside
the calibrated cover distribution, the report records the measured
rate and narrows the claim (`universal_claim: false`) instead of
asserting universal coverage — notably smooth/low-texture PNG covers,
whose structured LSB planes fire the CL-14 detector on clean images.
CL-68 judges stability per (texture, medium) cell: cells meeting the
<=1% false-failure target are claimed, the rest are listed in
`stability_exclusions` with their measured false-fail and withhold
rates.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from ._parallel import process_map
from ._png import save_png
from ._validation import make_need
from .banded_fixtures import build_banded_dataset
from .calibration import (
    ALL_TEXTURES,
    CALIBRATED_TEXTURES,
    detector_scores,
    load_frozen_thresholds,
    prime_detector_scores,
    texture_of,
)
from .fixtures import Fixture, build_dataset, encode_dct_jpeg, generate_cover
from .metadata import analyze_all_bytes
from .metadata_fixtures import build_metadata_dataset
from .pinning import dataset_hash
from .splits import assign_splits
from .verdicts import ThresholdConfig, decide_verdict

BENCHMARK_SCHEMA = "covertlens.frozen-benchmark"
BENCHMARK_VERSION = "1.1.0"
FAMILIES = ("spatial_lsb", "jpeg_dct", "metadata")
RECALL_TARGET = 0.95
PRECISION_TARGET = 0.99
CLEAN_FAILURE_TARGET = 0.01
MIN_CLEAN_RUNS = 300
# CL-68: at least this many held-out positives per family and band.
MIN_HELD_OUT_PER_BAND = 20
# The pre-CL-68 stability claim (gradient_noise only); kept as the
# default for direct `clean_run_stability` calls.
IN_COVERAGE_PATTERNS = ("gradient_noise",)
# CL-68: stability is measured on every CL-9 cover texture.
STABILITY_PATTERNS = ALL_TEXTURES


def wilson_interval(
    successes: int, n: int, z: float = 1.959964
) -> dict[str, float | None]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return {"low": None, "high": None}
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {
        "low": round(max(0.0, centre - half), 6),
        "high": round(min(1.0, centre + half), 6),
    }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": round(numerator / denominator, 6) if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "wilson95": wilson_interval(numerator, denominator),
    }


_FROZEN_DETECTORS = {
    "spatial_lsb": "lsb-pov-chisquare",
    "jpeg_dct": "dct-coefficient-pov-chisquare",
    "metadata": "metadata-ancillary-entries",
}


def _family_score(fixture: Fixture, family: str) -> float | None:
    """Frozen-benchmark score: the detector the frozen points calibrate.

    CL-61 added second detectors per pixel family; the frozen
    evaluation stays pinned to the originally calibrated detector by
    name so its numbers cannot drift when detectors are added.
    """
    wanted = _FROZEN_DETECTORS.get(family)
    for found_family, detector_name, score in detector_scores(fixture.data):
        if found_family == family and detector_name == wanted:
            return score
    return None


def _point(score: float | None, point: float | None) -> bool:
    return bool(score is not None and point is not None and score >= float(point))


def evaluate_held_out(
    fixtures: Iterable[Fixture],
    assignments: dict[str, str],
    config: ThresholdConfig,
    *,
    calibrated_textures: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Score held-out fixtures per family, band and cover texture.

    Targets are assessed on the family's calibrated textures (its
    detection claim, CL-68); every other texture is measured and
    reported, never folded into the claim.
    """
    coverage = calibrated_textures or CALIBRATED_TEXTURES
    held_out = [f for f in fixtures if assignments.get(f.fixture_id) == "held_out"]
    families: dict[str, Any] = {}
    for family in FAMILIES:
        owned = [f for f in held_out if f.family == family]
        thresholds = config.for_family(family)
        claimed = coverage.get(family, ALL_TEXTURES)
        rows: list[dict[str, Any]] = []
        for fixture in owned:
            score = _family_score(fixture, family)
            texture = texture_of(fixture)
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "role": fixture.role,
                    "payload_band": fixture.payload_band,
                    "texture": texture,
                    "in_coverage": texture in claimed,
                    "score": round(score, 6) if score is not None else None,
                    "at_triage": _point(score, thresholds.triage_flag_at),
                    "at_enforcement": _point(
                        score, thresholds.enforcement_quarantine_at
                    ),
                }
            )
        claim_rows = [r for r in rows if r["in_coverage"]]
        pos_rows = [r for r in claim_rows if r["role"] == "encoded"]
        neg_rows = [r for r in claim_rows if r["role"] in ("clean", "negative")]
        tp_triage = sum(1 for r in pos_rows if r["at_triage"])
        tp_enf = sum(1 for r in pos_rows if r["at_enforcement"])
        fp_enf = sum(1 for r in neg_rows if r["at_enforcement"])
        bands: dict[str, Any] = {}
        positives_by_band: dict[str, int] = {}
        for band in ("low", "medium", "high", "none"):
            band_pos = [r for r in pos_rows if r["payload_band"] == band]
            if band_pos:
                bands[band] = _rate(
                    sum(1 for r in band_pos if r["at_triage"]), len(band_pos)
                )
                positives_by_band[band] = len(band_pos)
        by_texture: dict[str, Any] = {}
        for texture in sorted({r["texture"] for r in rows}):
            texture_rows = [r for r in rows if r["texture"] == texture]
            cells: dict[str, Any] = {}
            for band in ("low", "medium", "high"):
                band_pos = [
                    r
                    for r in texture_rows
                    if r["role"] == "encoded" and r["payload_band"] == band
                ]
                if band_pos:
                    cells[band] = {
                        "positives": len(band_pos),
                        "recall_at_triage": _rate(
                            sum(1 for r in band_pos if r["at_triage"]), len(band_pos)
                        ),
                        "recall_at_enforcement": _rate(
                            sum(1 for r in band_pos if r["at_enforcement"]),
                            len(band_pos),
                        ),
                    }
            negatives = [r for r in texture_rows if r["role"] != "encoded"]
            by_texture[texture] = {
                "in_coverage": texture in claimed,
                "bands": cells,
                "negatives": len(negatives),
                "negatives_flagged": _rate(
                    sum(1 for r in negatives if r["at_triage"]), len(negatives)
                ),
                "negatives_withheld": _rate(
                    sum(1 for r in negatives if r["at_enforcement"]), len(negatives)
                ),
            }
        families[family] = {
            "calibrated_textures": list(claimed),
            "positives": len(pos_rows),
            "negatives": len(neg_rows),
            "positives_by_band": positives_by_band,
            "prevalence": _rate(len(pos_rows), len(pos_rows) + len(neg_rows)),
            "recall_at_triage": _rate(tp_triage, len(pos_rows)),
            "enforcement_precision": _rate(tp_enf, tp_enf + fp_enf),
            "enforcement_recall": _rate(tp_enf, len(pos_rows)),
            "recall_by_band": bands,
            "bands_without_held_out_positives": [
                b for b in ("low", "medium", "high") if b not in bands
            ],
            "by_texture": by_texture,
            "rows": rows,
        }
    return {
        "held_out_fixture_ids": sorted(f.fixture_id for f in held_out),
        "held_out_dataset_hash": dataset_hash(held_out),
        "families": families,
    }


_ARTIFACT_MEMO: dict[tuple[str, str, int], bytes] = {}


def _build_clean_artifact(key: tuple[str, str, int]) -> bytes:
    family, pattern, seed = key
    pixels = generate_cover(64, 48, pattern=pattern, seed=seed)
    if family == "spatial_lsb":
        return save_png(pixels, 64, 48)
    return encode_dct_jpeg(pixels, 64, 48, b"")


def _clean_artifact(family: str, pattern: str, seed: int) -> bytes:
    key = (family, pattern, seed)
    cached = _ARTIFACT_MEMO.get(key)
    if cached is None:
        cached = _ARTIFACT_MEMO[key] = _build_clean_artifact(key)
    return cached


def _analyze_findings(data: bytes) -> Any:
    return analyze_all_bytes(data).findings


def _prime_stability(patterns: tuple[str, ...], runs: int, seed_base: int) -> None:
    """Build and analyse every stability artifact in a process pool."""
    keys = [
        ("spatial_lsb" if i % 2 == 0 else "jpeg_dct", pattern, seed_base + i)
        for pattern in patterns
        for i in range(runs)
    ]
    todo = [k for k in keys if k not in _ARTIFACT_MEMO]
    for key, data in zip(todo, process_map(_build_clean_artifact, todo, chunksize=16)):
        _ARTIFACT_MEMO[key] = data
    datas = [_ARTIFACT_MEMO[k] for k in keys if _ARTIFACT_MEMO[k] not in _FINDINGS_MEMO]
    for data, findings in zip(
        datas, process_map(_analyze_findings, datas, chunksize=16)
    ):
        _FINDINGS_MEMO[data] = findings


def clean_run_stability(
    config: ThresholdConfig,
    *,
    runs: int = 320,
    seed_base: int = 100_000,
    patterns: tuple[str, ...] = IN_COVERAGE_PATTERNS,
) -> dict[str, Any]:
    """Run independent clean artifacts through the frozen ladder.

    Runs alternate PNG (spatial) and JPEG (DCT) artifacts; each
    pattern block also breaks the counts down by family, so a texture
    that is stable for one medium but not the other is visible.
    """
    _prime_stability(patterns, runs, seed_base)
    per_pattern: dict[str, Any] = {}
    total_runs = 0
    total_failures = 0
    verdict_counts: dict[str, int] = {}
    for pattern in patterns:
        counts: dict[str, int] = {}
        per_family: dict[str, dict[str, int]] = {}
        failures = 0
        for i in range(runs):
            family = "spatial_lsb" if i % 2 == 0 else "jpeg_dct"
            data = _clean_artifact(family, pattern, seed_base + i)
            decision = decide_verdict(_findings_for(data), config)
            verdict = decision.verdict.value
            counts[verdict] = counts.get(verdict, 0) + 1
            cell = per_family.setdefault(family, {})
            cell[verdict] = cell.get(verdict, 0) + 1
            if verdict == "fail_run":
                failures += 1
        per_pattern[pattern] = {
            "runs": runs,
            "false_failures": failures,
            "false_failure_rate": _rate(failures, runs),
            "withhold_rate": _rate(
                counts.get("quarantine", 0) + counts.get("fail_run", 0), runs
            ),
            "flag_rate": _rate(counts.get("flag", 0), runs),
            "verdict_counts": counts,
            "by_family": {
                family: {
                    "runs": sum(cell.values()),
                    "verdict_counts": cell,
                    "false_failure_rate": _rate(
                        cell.get("fail_run", 0), sum(cell.values())
                    ),
                    "withhold_rate": _rate(
                        cell.get("quarantine", 0) + cell.get("fail_run", 0),
                        sum(cell.values()),
                    ),
                }
                for family, cell in sorted(per_family.items())
            },
        }
        total_runs += runs
        total_failures += failures
        for verdict, count in counts.items():
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + count
    return {
        "runs": total_runs,
        "seed_base": seed_base,
        "false_failures": total_failures,
        "false_failure_rate": _rate(total_failures, total_runs),
        "verdict_counts": verdict_counts,
        "flag_rate": _rate(verdict_counts.get("flag", 0), total_runs),
        "withhold_rate": _rate(
            verdict_counts.get("quarantine", 0) + verdict_counts.get("fail_run", 0),
            total_runs,
        ),
        "per_pattern": per_pattern,
        "patterns_claimed": list(patterns),
    }


_FINDINGS_MEMO: dict[bytes, Any] = {}


def _findings_for(data: bytes) -> Any:
    """Memoised findings for a stability artifact (pure function of bytes)."""
    cached = _FINDINGS_MEMO.get(data)
    if cached is None:
        cached = analyze_all_bytes(data).findings
        _FINDINGS_MEMO[data] = cached
    return cached


def _stability_claim(
    stability: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split (texture, medium) cells into claimed and excluded (CL-68).

    A cell is claimed when it ran at least MIN_CLEAN_RUNS / 2 artifacts
    of that medium and its false-failure rate meets the target; the
    texture as a whole must also hold MIN_CLEAN_RUNS runs.
    """
    claimed: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for pattern, block in stability["per_pattern"].items():
        for family, cell in block["by_family"].items():
            rate = cell["false_failure_rate"]["value"]
            row = {
                "texture": pattern,
                "family": family,
                "media": "png" if family == "spatial_lsb" else "jpeg",
                "runs": cell["runs"],
                "false_failure_rate": cell["false_failure_rate"],
                "withhold_rate": cell["withhold_rate"],
            }
            ok = (
                block["runs"] >= MIN_CLEAN_RUNS
                and cell["runs"] >= MIN_CLEAN_RUNS // 2
                and rate is not None
                and rate <= CLEAN_FAILURE_TARGET
            )
            (claimed if ok else excluded).append(row)
    return claimed, excluded


def _alternative_flag_rates(
    frozen: dict[str, Any], stability: dict[str, Any]
) -> dict[str, Any]:
    """Clean flag rate at the unshipped no-low-band triage point (CL-68)."""
    out: dict[str, Any] = {}
    for family, block in (frozen.get("families") or {}).items():
        alternative = block.get("alternative_triage_without_low_band")
        if not alternative or family not in ("spatial_lsb", "jpeg_dct"):
            continue
        point = float(alternative["flag_at"])
        shipped = float(block["triage_flag_at"])
        flagged_alt = flagged_now = runs = 0
        for pattern in CALIBRATED_TEXTURES.get(family, ()):
            for i in range(stability["per_pattern"].get(pattern, {}).get("runs", 0)):
                if (i % 2 == 0) != (family == "spatial_lsb"):
                    continue
                data = _clean_artifact(family, pattern, stability["seed_base"] + i)
                score = next(
                    (
                        s
                        for fam, name, s in detector_scores(data)
                        if fam == family and name == _FROZEN_DETECTORS[family]
                    ),
                    None,
                )
                runs += 1
                flagged_alt += _point(score, point)
                flagged_now += _point(score, shipped)
        out[family] = {
            "shipped_flag_at": shipped,
            "alternative_flag_at": point,
            "clean_flag_rate_shipped": _rate(flagged_now, runs),
            "clean_flag_rate_alternative": _rate(flagged_alt, runs),
            "development_low_band_recall_alternative": alternative[
                "development_low_band_recall"
            ],
            "shipped": False,
        }
    return out


def run_frozen_evaluation(*, clean_runs: int = 320) -> dict[str, Any]:
    """Full CL-28/CL-68 evaluation: held-out, stability, targets.

    Held-out data is the CL-9/CL-22 suites plus the CL-68 banded
    suite (at least 20 held-out positives per family, band and
    texture where constructible). Clean-run stability runs
    `clean_runs` artifacts per texture on all three textures.
    """
    config, frozen = load_frozen_thresholds()
    banded = build_banded_dataset()
    fixtures: list[Fixture] = list(banded.fixtures)
    assignments: dict[str, str] = dict(banded.assignments)
    for dataset in (build_dataset(), build_metadata_dataset()):
        split = assign_splits(dataset)
        assignments.update(split)
        fixtures.extend(dataset)
    prime_detector_scores(
        f.data for f in fixtures if assignments.get(f.fixture_id) == "held_out"
    )
    held_out = evaluate_held_out(fixtures, assignments, config)
    development_ids = set(frozen.get("development_fixture_ids") or [])
    overlap = sorted(development_ids & set(held_out["held_out_fixture_ids"]))

    stability_all = clean_run_stability(
        config, runs=clean_runs, patterns=STABILITY_PATTERNS
    )
    claimed_cells, excluded_cells = _stability_claim(stability_all)
    claimed_textures = sorted(
        {
            row["texture"]
            for row in claimed_cells
            if not any(e["texture"] == row["texture"] for e in excluded_cells)
        }
    )
    claimed_runs = sum(r["runs"] for r in claimed_cells)
    claimed_failures = sum(r["false_failure_rate"]["numerator"] for r in claimed_cells)
    claimed_flags = sum(
        stability_all["per_pattern"][r["texture"]]["by_family"][r["family"]][
            "verdict_counts"
        ].get("flag", 0)
        for r in claimed_cells
    )
    stability = {
        **stability_all,
        "runs": claimed_runs,
        "false_failures": claimed_failures,
        "false_failure_rate": _rate(claimed_failures, claimed_runs),
        "flag_rate": _rate(claimed_flags, claimed_runs),
        "claimed_cells": claimed_cells,
        "patterns_claimed": claimed_textures,
        "all_runs": stability_all["runs"],
    }

    families = held_out["families"]
    recall_met = {
        family: (
            block["recall_at_triage"]["value"] is not None
            and block["recall_at_triage"]["value"] >= RECALL_TARGET
        )
        for family, block in families.items()
    }
    precision_met = {
        family: (
            block["enforcement_precision"]["value"] is not None
            and block["enforcement_precision"]["value"] >= PRECISION_TARGET
        )
        for family, block in families.items()
    }
    band_counts_met = {
        family: all(
            block["positives_by_band"].get(band, 0) >= MIN_HELD_OUT_PER_BAND
            for band in ("low", "medium", "high")
        )
        for family, block in families.items()
    }
    stability_rate = stability["false_failure_rate"]["value"]
    stability_met = bool(
        stability["runs"] >= MIN_CLEAN_RUNS
        and stability_rate is not None
        and stability_rate <= CLEAN_FAILURE_TARGET
    )
    alternatives = _alternative_flag_rates(frozen, stability_all)
    exclusion_text = (
        "; ".join(
            f"{row['texture']} {row['media'].upper()} ({row['family']}): "
            f"false-fail {row['false_failure_rate']['numerator']}/{row['runs']} "
            f"= {row['false_failure_rate']['value']}, withheld "
            f"{row['withhold_rate']['numerator']}/{row['runs']}"
            for row in excluded_cells
        )
        or "none"
    )
    coverage_text = ", ".join(
        family + ": " + "/".join(textures)
        for family, textures in CALIBRATED_TEXTURES.items()
    )
    claimed_cell_text = ", ".join(
        row["texture"] + "/" + row["media"] for row in claimed_cells
    )
    tradeoffs = [
        "Detection claims use each family's calibrated textures "
        f"({coverage_text}); "
        "one per-family operating point cannot serve every cover texture "
        "because the pixel detectors' clean baselines depend on texture. "
        "Out-of-coverage recall is measured per texture and band and "
        "reported, not claimed.",
        f"Clean-run stability is claimed for {len(claimed_cells)} "
        f"(texture, medium) cells over {claimed_runs} runs; excluded with "
        f"measured rates: {exclusion_text}. Excluded cells need "
        "texture-conditioned operating points before any enforcement claim.",
        "Held-out samples are at least 20 positives per family and band "
        "on calibrated textures (CL-68), so Wilson intervals are reported "
        "for every band; targets are judged on point estimates.",
        f"Triage flag rate on clean claimed runs is "
        f"{stability['flag_rate']['value']}: flags permit delivery and "
        "create review volume, not run failures. Claiming the low payload "
        "band is what sets the triage point this low; "
        + (
            "; ".join(
                f"{family} without the low band would flag "
                f"{row['clean_flag_rate_alternative']['value']} of clean runs "
                f"(shipped {row['clean_flag_rate_shipped']['value']}) at "
                f"low-band development recall "
                f"{row['development_low_band_recall_alternative']}"
                for family, row in alternatives.items()
            )
            or "no alternative computed"
        )
        + " (owners' decision; not shipped).",
    ]
    return {
        "schema": BENCHMARK_SCHEMA,
        "schema_version": 1,
        "benchmark_version": BENCHMARK_VERSION,
        "frozen_config_version": config.version,
        "evaluation_set": "held_out_only",
        "calibration_overlap_fixture_ids": overlap,
        "targets": {
            "per_family_recall_at_least": RECALL_TARGET,
            "enforcement_precision_at_least": PRECISION_TARGET,
            "clean_false_failure_rate_at_most": CLEAN_FAILURE_TARGET,
            "min_clean_runs": MIN_CLEAN_RUNS,
            "min_held_out_positives_per_band": MIN_HELD_OUT_PER_BAND,
        },
        "banded_suite": banded.summary(),
        "held_out": held_out,
        "clean_run_stability": stability,
        "stability_exclusions": excluded_cells,
        "triage_alternatives": alternatives,
        "assessment": {
            "recall_target_met_by_family": recall_met,
            "precision_target_met_by_family": precision_met,
            "held_out_band_counts_met_by_family": band_counts_met,
            "clean_stability_met_within_claimed_coverage": stability_met,
            "stability_textures_claimed": claimed_textures,
            "stability_claim_covers_all_textures": not excluded_cells,
            "universal_claim": False,
            "claim_scope": (
                "Frozen points are judged on held-out point estimates on each "
                "family's calibrated textures and on clean-run stability per "
                f"(texture, medium) cell; claimed stability cells: "
                f"{claimed_cell_text}; "
                "coverage is narrowed per tradeoffs."
            ),
        },
        "tradeoffs": tradeoffs,
        "equated_with_collusion": False,
    }


def validate_frozen_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a CL-28 report; empty is valid."""
    errors: list[str] = []

    need = make_need(errors)

    need(report.get("schema") == BENCHMARK_SCHEMA, f"schema must be {BENCHMARK_SCHEMA}")
    need(
        report.get("evaluation_set") == "held_out_only",
        "evaluation must be held-out only",
    )
    need(
        report.get("calibration_overlap_fixture_ids") == [],
        "held-out evaluation must not overlap calibration fixtures (C-07)",
    )
    stability = report.get("clean_run_stability") or {}
    need(
        stability.get("runs", 0) >= MIN_CLEAN_RUNS,
        f"clean stability needs >={MIN_CLEAN_RUNS} runs",
    )
    need(
        (report.get("assessment") or {}).get("universal_claim") is False,
        "report must not make a universal claim",
    )
    need(
        report.get("equated_with_collusion") is False,
        "benchmark outcomes must not be equated with collusion (C-02)",
    )
    for family in FAMILIES:
        block = ((report.get("held_out") or {}).get("families") or {}).get(family)
        need(block is not None, f"held_out.families.{family} is required")
    return errors
