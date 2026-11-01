"""Frozen synthetic benchmark + clean-run stability (CL-28, OPS-03).

Evaluates the CL-27 frozen config (`frozen-1.0.0`) exactly as shipped:

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
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from .calibration import load_frozen_thresholds
from .fixtures import Fixture, _save_png, build_dataset, encode_dct_jpeg, generate_cover
from .metadata import analyze_all_bytes
from .metadata_fixtures import build_metadata_dataset
from .pinning import dataset_hash
from .splits import assign_splits
from .verdicts import ThresholdConfig, decide_verdict

BENCHMARK_SCHEMA = "covertlens.frozen-benchmark"
BENCHMARK_VERSION = "1.0.0"
FAMILIES = ("spatial_lsb", "jpeg_dct", "metadata")
RECALL_TARGET = 0.95
PRECISION_TARGET = 0.99
CLEAN_FAILURE_TARGET = 0.01
MIN_CLEAN_RUNS = 300
# Cover patterns inside the frozen claim: the CL-9/CL-27 suite and
# calibration covers are gradient_noise. Other patterns are probed
# and reported, but excluded from the stability claim (see tradeoffs).
IN_COVERAGE_PATTERNS = ("gradient_noise",)
PROBE_PATTERNS = ("smooth", "blocks")


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


def _family_score(fixture: Fixture, family: str) -> float | None:
    result = analyze_all_bytes(fixture.data)
    for finding in result.findings:
        if finding.family == family:
            return finding.score
    return None


def evaluate_held_out(
    fixtures: Iterable[Fixture],
    assignments: dict[str, str],
    config: ThresholdConfig,
) -> dict[str, Any]:
    """Score held-out fixtures per family/band under the frozen config."""
    held_out = [f for f in fixtures if assignments.get(f.fixture_id) == "held_out"]
    families: dict[str, Any] = {}
    for family in FAMILIES:
        owned = [f for f in held_out if f.family == family]
        thresholds = config.for_family(family)
        rows = []
        for fixture in owned:
            score = _family_score(fixture, family)
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "role": fixture.role,
                    "payload_band": fixture.payload_band,
                    "score": round(score, 6) if score is not None else None,
                    "at_triage": bool(
                        score is not None
                        and thresholds.triage_flag_at is not None
                        and score >= float(thresholds.triage_flag_at)
                    ),
                    "at_enforcement": bool(
                        score is not None
                        and thresholds.enforcement_quarantine_at is not None
                        and score >= float(thresholds.enforcement_quarantine_at)
                    ),
                }
            )
        pos_rows = [r for r in rows if r["role"] == "encoded"]
        neg_rows = [r for r in rows if r["role"] in ("clean", "negative")]
        tp_triage = sum(1 for r in pos_rows if r["at_triage"])
        tp_enf = sum(1 for r in pos_rows if r["at_enforcement"])
        fp_enf = sum(1 for r in neg_rows if r["at_enforcement"])
        bands: dict[str, Any] = {}
        for band in ("low", "medium", "high", "none"):
            band_pos = [r for r in pos_rows if r["payload_band"] == band]
            if band_pos:
                bands[band] = _rate(
                    sum(1 for r in band_pos if r["at_triage"]), len(band_pos)
                )
        families[family] = {
            "positives": len(pos_rows),
            "negatives": len(neg_rows),
            "prevalence": _rate(len(pos_rows), len(pos_rows) + len(neg_rows)),
            "recall_at_triage": _rate(tp_triage, len(pos_rows)),
            "enforcement_precision": _rate(tp_enf, tp_enf + fp_enf),
            "enforcement_recall": _rate(tp_enf, len(pos_rows)),
            "recall_by_band": bands,
            "bands_without_held_out_positives": [
                b for b in ("low", "medium", "high") if b not in bands
            ],
            "rows": rows,
        }
    return {
        "held_out_fixture_ids": sorted(f.fixture_id for f in held_out),
        "held_out_dataset_hash": dataset_hash(held_out),
        "families": families,
    }


def _clean_artifact(family: str, pattern: str, seed: int) -> bytes:
    pixels = generate_cover(64, 48, pattern=pattern, seed=seed)
    if family == "spatial_lsb":
        return _save_png(pixels, 64, 48)
    return encode_dct_jpeg(pixels, 64, 48, b"")


def clean_run_stability(
    config: ThresholdConfig,
    *,
    runs: int = 320,
    seed_base: int = 100_000,
    patterns: tuple[str, ...] = IN_COVERAGE_PATTERNS,
) -> dict[str, Any]:
    """Run independent clean artifacts through the frozen ladder."""
    per_pattern: dict[str, Any] = {}
    total_runs = 0
    total_failures = 0
    verdict_counts: dict[str, int] = {}
    for pattern in patterns:
        counts: dict[str, int] = {}
        failures = 0
        for i in range(runs):
            family = "spatial_lsb" if i % 2 == 0 else "jpeg_dct"
            data = _clean_artifact(family, pattern, seed_base + i)
            decision = decide_verdict(analyze_all_bytes(data).findings, config)
            counts[decision.verdict.value] = counts.get(decision.verdict.value, 0) + 1
            if decision.verdict.value == "fail_run":
                failures += 1
        per_pattern[pattern] = {
            "runs": runs,
            "false_failures": failures,
            "false_failure_rate": _rate(failures, runs),
            "verdict_counts": counts,
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
        "per_pattern": per_pattern,
        "patterns_claimed": list(patterns),
    }


def run_frozen_evaluation(
    *,
    clean_runs: int = 320,
    probe_runs: int = 60,
) -> dict[str, Any]:
    """Full CL-28 evaluation: held-out benchmark + stability + targets."""
    config, frozen = load_frozen_thresholds()
    fixtures: list[Fixture] = []
    assignments: dict[str, str] = {}
    for dataset in (build_dataset(), build_metadata_dataset()):
        split = assign_splits(dataset)
        assignments.update(split)
        fixtures.extend(dataset)
    held_out = evaluate_held_out(fixtures, assignments, config)
    development_ids = set(frozen.get("development_fixture_ids") or [])
    overlap = sorted(development_ids & set(held_out["held_out_fixture_ids"]))

    stability = clean_run_stability(config, runs=clean_runs)
    probes = clean_run_stability(
        config, runs=probe_runs, seed_base=200_000, patterns=PROBE_PATTERNS
    )

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
    stability_rate = stability["false_failure_rate"]["value"]
    stability_met = bool(
        stability["runs"] >= MIN_CLEAN_RUNS
        and stability_rate is not None
        and stability_rate <= CLEAN_FAILURE_TARGET
    )
    probe_failures = {
        pattern: block["false_failure_rate"]["value"]
        for pattern, block in probes["per_pattern"].items()
    }
    tradeoffs = [
        "Held-out positives exist only in the high payload band; low/medium "
        "recall is validated on CL-27 development data only, so the recall "
        "claim does not extend to held-out low/medium evidence.",
        "Held-out samples are tiny (1-2 positives per family); Wilson "
        "intervals are wide and the targets are met on point estimates, "
        "not on interval lower bounds.",
        f"Clean smooth-PNG covers false-fail at rate "
        f"{probe_failures.get('smooth')} and blocks-JPEG covers at "
        f"{probe_failures.get('blocks')} under the frozen points; the "
        f"clean-run stability claim is narrowed to "
        f"{'/'.join(IN_COVERAGE_PATTERNS)} covers, the calibrated "
        "distribution. Low-texture covers need recalibration before any "
        "enforcement claim.",
        f"Triage flag rate on clean in-coverage runs is "
        f"{stability['flag_rate']['value']}: flags permit delivery and "
        "create review volume, not run failures.",
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
        },
        "held_out": held_out,
        "clean_run_stability": stability,
        "out_of_coverage_probes": probes,
        "assessment": {
            "recall_target_met_by_family": recall_met,
            "precision_target_met_by_family": precision_met,
            "clean_stability_met_within_claimed_coverage": stability_met,
            "universal_claim": False,
            "claim_scope": (
                "Frozen points meet the numeric targets on the held-out "
                "point estimates and on >=300 clean "
                f"{'/'.join(IN_COVERAGE_PATTERNS)} runs; coverage is "
                "narrowed per tradeoffs (bands, cover texture, tiny n)."
            ),
        },
        "tradeoffs": tradeoffs,
        "equated_with_collusion": False,
    }


def validate_frozen_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a CL-28 report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

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
