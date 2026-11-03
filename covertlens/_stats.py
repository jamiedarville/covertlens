"""Shared statistics helpers (CL-63).

One home for the threshold-free benchmark statistics that used to
live as private helpers in `covertlens.lsb` and were imported across
modules by private name: Wilson intervals, ROC-AUC, average
precision, percentiles, stratified bootstrap intervals and score
summaries. Public names only; behaviour is unchanged from the
original `lsb` implementations.
"""

from __future__ import annotations

import math
import random
from typing import Any


def wilson(successes: int, total: int, z: float = 1.96) -> dict[str, Any]:
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


def roc_auc(positive: list[float], negative: list[float]) -> float | None:
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


def average_precision(scored: list[tuple[float, int]]) -> float | None:
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


def percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(
        len(sorted_values) - 1,
        max(0, int(math.floor(fraction * len(sorted_values)))),
    )
    return sorted_values[index]


def bootstrap_interval(
    positive: list[float],
    negative: list[float],
    *,
    replicates: int,
    seed: int,
    metric: str,
) -> dict[str, Any]:
    """Stratified bootstrap percentile interval for AUC / average precision."""
    estimate = (
        roc_auc(positive, negative)
        if metric == "roc_auc"
        else average_precision([(s, 1) for s in positive] + [(s, 0) for s in negative])
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
            roc_auc(pos, neg)
            if metric == "roc_auc"
            else average_precision([(s, 1) for s in pos] + [(s, 0) for s in neg])
        )
        if value is not None:
            values.append(value)
    values.sort()
    return {
        "estimate": estimate,
        "ci_low": round(percentile(values, 0.025), 6) if values else estimate,
        "ci_high": round(percentile(values, 0.975), 6) if values else estimate,
        "bootstrap_replicates": replicates,
        "bootstrap_seed": seed,
    }


def score_summary(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(scores),
        "min": round(min(scores), 6),
        "max": round(max(scores), 6),
        "mean": round(sum(scores) / len(scores), 6),
    }
