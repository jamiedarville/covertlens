"""LSB spatial detector and threshold-free benchmark (CL-14, DET-03).

The detector scores PNG sample LSBs on the exact original bytes parsed
by CL-13 (`covertlens.parsing`): no resize, recompression or pixel
reconstruction happens here. It implements the classic pairs-of-values
(PoV) chi-square statistic for LSB replacement. Embedding random payload
bits in sample LSBs equalises each value pair ``(2k, 2k + 1)``; clean
covers keep pair members unequal at a rate set by the cover itself.
The score is ``degrees_of_freedom / chi_square`` clipped to [0, 1]:
near 1 when pairs are as equal as random LSBs predict, lower when the
cover's natural imbalance survives. The score is evidence for triage,
never proof of collusion (C-02), and no threshold is frozen here
(CL-27 freezes triage/enforcement points separately, C-06).

Benchmarking is threshold-free: a sweep over score thresholds reports
precision/recall with Wilson score intervals at every point, plus
ROC-AUC and average precision (PR summary) with stratified bootstrap
confidence intervals. Performance is broken down by the CL-9 payload
band (`none` / `low` / `medium` / `high`) so a strong high-band result
never masquerades as a low-band one.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Any, Iterable

from .fixtures import Fixture
from .parsing import (
    AnalysisResult,
    AnalysisStatus,
    Finding,
    ParserLimits,
    analyze_bytes,
    analyze_version,
)
from .store import ArtifactStore

FAMILY = "spatial_lsb"
LSB_DETECTOR_NAME = "lsb-pov-chisquare"
LSB_DETECTOR_VERSION = "1.0.0"
CONFIG_VERSION = "1.0.0"
BENCHMARK_SCHEMA = "covertlens.lsb-benchmark"
BENCHMARK_SCHEMA_VERSION = 1
BENCHMARK_VERSION = "1.0.0"

PAYLOAD_BANDS = ("none", "low", "medium", "high")

_LIMITATIONS = (
    "global pairs-of-values chi-square over sample LSBs; LSB-matching "
    "(+/-1) and content-adaptive embedding may evade it",
    "calibrated only on procedural synthetic covers; natural-image "
    "covers are untested",
    "score is evidence, not demonstrated collusion (C-02); thresholds "
    "unfrozen until CL-27",
)


@dataclass(frozen=True)
class LsbConfig:
    """Versioned detector configuration; a change bumps ``version``."""

    version: str = CONFIG_VERSION
    # PoV pairs whose total count is below this are too sparse for the
    # chi-square approximation and are excluded (counted in coverage).
    pair_min_count: int = 4

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        if self.pair_min_count < 1:
            raise ValueError("pair_min_count must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "pair_min_count": self.pair_min_count}


DEFAULT_CONFIG = LsbConfig()


def _pov_statistics(
    samples: bytes, config: LsbConfig
) -> tuple[float, dict[str, Any], int]:
    """Return (score, evidence, pairs_used) for raw sample bytes."""
    counts = [0] * 256
    for value in samples:
        counts[value] += 1
    total = len(samples)
    chi_square = 0.0
    pairs_used = 0
    imbalance = 0
    for k in range(128):
        pair_total = counts[2 * k] + counts[2 * k + 1]
        imbalance += abs(counts[2 * k] - counts[2 * k + 1])
        if pair_total >= config.pair_min_count:
            pairs_used += 1
            expected = pair_total / 2.0
            chi_square += (
                (counts[2 * k] - expected) ** 2
                + (counts[2 * k + 1] - expected) ** 2
            ) / expected
    degrees = pairs_used - 1 if pairs_used else 0
    if pairs_used < 2 or chi_square <= 0:
        score = 1.0 if pairs_used >= 2 and total and chi_square <= 0 else 0.0
    else:
        score = min(1.0, degrees / chi_square)
    evidence = {
        "statistic": "pairs_of_values_chi_square",
        "chi_square": round(chi_square, 6),
        "degrees_of_freedom": degrees,
        "chi_square_per_df": (
            round(chi_square / degrees, 6) if degrees else 0.0
        ),
        "pairs_used": pairs_used,
        "lsb_one_fraction": (
            round(sum(counts[1::2]) / total, 6) if total else 0.0
        ),
        "pov_imbalance": round(imbalance / total, 6) if total else 0.0,
        "detector_config_version": config.version,
    }
    return score, evidence, pairs_used


def detect_lsb(
    result: AnalysisResult, config: LsbConfig | None = None
) -> Finding | None:
    """Score one CL-13 result; ``None`` when LSB is not applicable.

    Applicable means: parsed PNG with sample bytes present. JPEGs,
    failed parses and pixel-less results get no LSB finding — a missing
    finding is not a clean score (fail-closed error behaviour, C-02).
    """
    active = config or DEFAULT_CONFIG
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind != "png" or result.pixels is None:
        return None
    samples = result.pixels
    score, evidence, pairs_used = _pov_statistics(samples, active)
    image = result.image or {}
    channels = int(image.get("channels") or 1)
    width = int(image.get("width") or 0)
    height = int(image.get("height") or 0)
    pixels_examined = width * height if width and height else len(samples) // max(channels, 1)
    coverage = {
        "applicable": True,
        "media_kind": "png",
        "samples_examined": len(samples),
        "pixels_examined": pixels_examined,
        "channels": channels,
        "pairs_total": 128,
        "pairs_used": pairs_used,
        "rows_parsed": int((result.coverage or {}).get("rows_parsed") or height),
        "config_version": active.version,
    }
    limitations = list(_LIMITATIONS)
    if pairs_used < 2:
        limitations.append(
            "insufficient pairs-of-values coverage; score is not reliable"
        )
    return Finding(
        family=FAMILY,
        detector_name=LSB_DETECTOR_NAME,
        detector_version=LSB_DETECTOR_VERSION,
        score=score,
        coverage=coverage,
        evidence=evidence,
        limitations=tuple(limitations),
    )


def analyze_lsb_bytes(
    data: bytes,
    *,
    limits: ParserLimits | None = None,
    config: LsbConfig | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
) -> AnalysisResult:
    """Parse exact bytes (CL-13) and attach the LSB finding when applicable."""
    result = analyze_bytes(
        data,
        limits=limits,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
    )
    finding = detect_lsb(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


def _wilson(successes: int, total: int, z: float = 1.96) -> dict[str, Any]:
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return {"estimate": None, "ci_low": 0.0, "ci_high": 1.0, "n": 0}
    p = successes / total
    denom = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return {
        "estimate": round(p, 6),
        "ci_low": round(max(0.0, centre - half), 6),
        "ci_high": round(min(1.0, centre + half), 6),
        "n": total,
    }


def _roc_auc(positive: list[float], negative: list[float]) -> float | None:
    """Mann-Whitney ROC-AUC (ties count half); ``None`` if a class is empty."""
    if not positive or not negative:
        return None
    wins = 0.0
    for pos in positive:
        for neg in negative:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return round(wins / (len(positive) * len(negative)), 6)


def _average_precision(scored: list[tuple[float, int]]) -> float | None:
    """Average precision over (score, label) rows; ``None`` if no positives."""
    positives = sum(label for _, label in scored)
    if positives == 0:
        return None
    ordered = sorted(scored, key=lambda row: row[0], reverse=True)
    hits = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(ordered, start=1):
        if label:
            hits += 1
            precision_sum += hits / rank
    return round(precision_sum / positives, 6)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(
        len(sorted_values) - 1,
        max(0, int(math.floor(fraction * len(sorted_values)))),
    )
    return sorted_values[index]


def _bootstrap_interval(
    positive: list[float],
    negative: list[float],
    *,
    replicates: int,
    seed: int,
    metric: str,
) -> dict[str, Any]:
    """Stratified bootstrap percentile interval for AUC / average precision."""
    estimate = (
        _roc_auc(positive, negative)
        if metric == "roc_auc"
        else _average_precision(
            [(s, 1) for s in positive] + [(s, 0) for s in negative]
        )
    )
    if estimate is None or replicates <= 0:
        return {
            "estimate": estimate,
            "ci_low": estimate,
            "ci_high": estimate,
            "bootstrap_replicates": 0,
            "bootstrap_seed": seed,
        }
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(replicates):
        pos = [positive[rng.randrange(len(positive))] for _ in positive]
        neg = [negative[rng.randrange(len(negative))] for _ in negative]
        value = (
            _roc_auc(pos, neg)
            if metric == "roc_auc"
            else _average_precision([(s, 1) for s in pos] + [(s, 0) for s in neg])
        )
        if value is not None:
            values.append(value)
    values.sort()
    return {
        "estimate": estimate,
        "ci_low": round(_percentile(values, 0.025), 6) if values else estimate,
        "ci_high": round(_percentile(values, 0.975), 6) if values else estimate,
        "bootstrap_replicates": replicates,
        "bootstrap_seed": seed,
    }


def _score_summary(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(scores),
        "min": round(min(scores), 6),
        "max": round(max(scores), 6),
        "mean": round(sum(scores) / len(scores), 6),
    }


def benchmark_lsb(
    fixtures: Iterable[Fixture],
    *,
    config: LsbConfig | None = None,
    thresholds: Iterable[float] | None = None,
    bootstrap_replicates: int = 1000,
    bootstrap_seed: int = 20261028,
) -> dict[str, Any]:
    """Threshold-free LSB benchmark over labelled CL-9 fixtures.

    Positives are ``encoded`` fixtures; ``clean`` and ``negative``
    fixtures are negatives. Fixtures outside the `spatial_lsb` family
    are not applicable and are only counted under ``skipped``. Ground
    truth comes from the caller's fixtures, so held-out labels must
    reach this function through the scorer path (CL-10, C-07).
    """
    active = config or DEFAULT_CONFIG
    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be >= 0")
    rows: list[dict[str, Any]] = []
    skipped = 0
    for fixture in fixtures:
        if fixture.family != FAMILY:
            skipped += 1
            continue
        result = analyze_lsb_bytes(fixture.data, config=active)
        finding = result.findings[0] if result.findings else None
        rows.append(
            {
                "fixture_id": fixture.fixture_id,
                "role": fixture.role,
                "label": 1 if fixture.role == "encoded" else 0,
                "payload_band": fixture.payload_band,
                "payload_bits": fixture.payload_bits,
                "bits_per_pixel": round(fixture.bits_per_pixel, 6),
                "applicable": finding is not None,
                "score": round(finding.score, 6) if finding else None,
            }
        )
    scored = [r for r in rows if r["applicable"] and r["score"] is not None]
    positive = [float(r["score"]) for r in scored if r["label"] == 1]
    negative = [float(r["score"]) for r in scored if r["label"] == 0]

    if thresholds is None:
        sweep_thresholds = sorted({0.0, 1.0} | {float(r["score"]) for r in scored})
    else:
        sweep_thresholds = sorted({float(t) for t in thresholds})
        for value in sweep_thresholds:
            if not 0.0 <= value <= 1.0:
                raise ValueError("thresholds must lie in [0, 1]")

    sweep: list[dict[str, Any]] = []
    for threshold in sweep_thresholds:
        tp = sum(1 for r in scored if r["label"] == 1 and float(r["score"]) >= threshold)
        fp = sum(1 for r in scored if r["label"] == 0 and float(r["score"]) >= threshold)
        tn = sum(1 for r in scored if r["label"] == 0 and float(r["score"]) < threshold)
        fn = sum(1 for r in scored if r["label"] == 1 and float(r["score"]) < threshold)
        sweep.append(
            {
                "threshold": round(threshold, 6),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": _wilson(tp, tp + fp),
                "recall": _wilson(tp, tp + fn),
                "false_positive_rate": _wilson(fp, fp + tn),
            }
        )

    by_band: dict[str, Any] = {}
    for band in PAYLOAD_BANDS:
        band_rows = [r for r in scored if r["payload_band"] == band]
        band_positive = [float(r["score"]) for r in band_rows if r["label"] == 1]
        band_negative = [float(r["score"]) for r in band_rows if r["label"] == 0]
        by_band[band] = {
            "fixture_count": len(band_rows),
            "positive_count": len(band_positive),
            "negative_count": len(band_negative),
            "scores": _score_summary([float(r["score"]) for r in band_rows]),
            # Each encoded band is ranked against every negative, so a
            # band cannot borrow strength from easier bands.
            "roc_auc_vs_negatives": (
                _roc_auc(band_positive, negative) if band_positive else None
            ),
        }

    return {
        "schema": BENCHMARK_SCHEMA,
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "detector": {
            "family": FAMILY,
            "name": LSB_DETECTOR_NAME,
            "version": LSB_DETECTOR_VERSION,
            "config": active.to_dict(),
        },
        "thresholds_status": "unfrozen_placeholder",
        "fixture_count": len(rows),
        "scored_count": len(scored),
        "skipped_non_lsb": skipped,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "rows": rows,
        "by_payload_band": by_band,
        "roc_auc": _bootstrap_interval(
            positive,
            negative,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
            metric="roc_auc",
        ),
        "pr_auc": _bootstrap_interval(
            positive,
            negative,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
            metric="average_precision",
        ),
        "sweep": sweep,
        "limitations": list(_LIMITATIONS)
        + [
            "benchmark fixtures are the CL-9 procedural suite; small "
            "bands give wide Wilson intervals, and bootstrap intervals "
            "are conditional on the observed sample (degenerate under "
            "perfect separation)"
        ],
    }


def validate_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one benchmark report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == BENCHMARK_SCHEMA, f"schema must be {BENCHMARK_SCHEMA}")
    need(
        report.get("schema_version") == BENCHMARK_SCHEMA_VERSION,
        f"schema_version must be {BENCHMARK_SCHEMA_VERSION}",
    )
    need(bool(report.get("benchmark_version")), "benchmark_version is required")
    detector = report.get("detector") or {}
    need(detector.get("family") == FAMILY, f"detector.family must be {FAMILY}")
    need(detector.get("name") == LSB_DETECTOR_NAME, "detector.name is required")
    need(detector.get("version") == LSB_DETECTOR_VERSION, "detector.version is required")
    need(
        (detector.get("config") or {}).get("version") == CONFIG_VERSION,
        "detector.config.version is required",
    )
    need(
        report.get("thresholds_status") == "unfrozen_placeholder",
        "thresholds_status must stay unfrozen_placeholder until CL-27",
    )
    for band in PAYLOAD_BANDS:
        need(band in (report.get("by_payload_band") or {}), f"by_payload_band.{band} is required")
    for key in ("roc_auc", "pr_auc"):
        block = report.get(key) or {}
        estimate = block.get("estimate")
        if estimate is not None:
            need(0.0 <= float(estimate) <= 1.0, f"{key}.estimate must lie in [0, 1]")
            need(
                float(block.get("ci_low", -1)) <= float(estimate) <= float(block.get("ci_high", 2)),
                f"{key} interval must bracket its estimate",
            )
    for i, point in enumerate(report.get("sweep") or []):
        for name in ("precision", "recall"):
            block = point.get(name) or {}
            estimate = block.get("estimate")
            if estimate is not None:
                need(0.0 <= float(estimate) <= 1.0, f"sweep[{i}].{name} must lie in [0, 1]")
                need(
                    float(block.get("ci_low", -1)) <= float(estimate) <= float(block.get("ci_high", 2)),
                    f"sweep[{i}].{name} interval must bracket its estimate",
                )
        need(
            point.get("tp", -1) + point.get("fn", -1) == report.get("positive_count"),
            f"sweep[{i}] tp+fn must equal positive_count",
        )
        need(
            point.get("fp", -1) + point.get("tn", -1) == report.get("negative_count"),
            f"sweep[{i}] fp+tn must equal negative_count",
        )
    return errors


def analyze_lsb_version(
    store: ArtifactStore,
    artifact_version_id: str,
    *,
    actor_id: str,
    limits: ParserLimits | None = None,
    config: LsbConfig | None = None,
) -> AnalysisResult:
    """Score one stored original via its audited, hash-checked read."""
    result = analyze_version(
        store, artifact_version_id, actor_id=actor_id, limits=limits
    )
    finding = detect_lsb(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))
