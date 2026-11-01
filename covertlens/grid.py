"""Grid discovery for attribute sequences (CL-43, GEO-02).

The geometric detector must *measure* a grid, not be handed one.
For a sequence v1..vn this module sweeps candidate steps from a
minimum resolvable step (2x the channel's segmentation tolerance)
to half the observed range, scoring each step s with the Rayleigh
statistic R(s) = |sum_j exp(2*pi*i*v_j/s)| / n. The best step wins;
its offset comes from the resultant phase, and residuals are folded
to [-s/2, s/2).

Significance comes from two seeded permutation/simulation nulls
(a few hundred replicates each): values drawn uniformly over the
observed range, and values rebuilt from resampled fractional parts
with integer parts drawn over the observed integer range. The
reported `null_exceedance` is the pooled fraction of null draws
whose best R reaches the observed best R. A declared grid may be
supplied as a prior: it is fitted too, and the
declared-vs-discovered step ratio is reported, but the discovered
grid is always the headline measurement.
"""

from __future__ import annotations

import math
import random
from typing import Any

GRID_DISCOVERY_VERSION = "1.0.0"
_TWO_PI = 2.0 * math.pi


def rayleigh(values: list[float], step: float) -> float:
    """Rayleigh statistic R(step) in [0, 1]; 1 = perfect phase lock."""
    if not values or step <= 0:
        return 0.0
    cos_sum = 0.0
    sin_sum = 0.0
    for v in values:
        phase = _TWO_PI * (v / step)
        cos_sum += math.cos(phase)
        sin_sum += math.sin(phase)
    return math.hypot(cos_sum, sin_sum) / len(values)


def _candidates(low: float, high: float, min_step: float) -> list[float]:
    span = high - low
    max_step = span / 2.0
    if max_step <= min_step or span <= 0:
        return []
    increment = max(0.05, min_step / 8.0)
    steps: list[float] = []
    step = min_step
    while step <= max_step:
        steps.append(round(step, 6))
        step += increment
    if steps[-1] < max_step:
        steps.append(round(max_step, 6))
    return steps


def _best_step(values: list[float], candidates: list[float]) -> tuple[float, float]:
    """Coarse sweep plus a local refinement around the coarse winner."""
    best_step, best_r = candidates[0], -1.0
    for step in candidates:
        r = rayleigh(values, step)
        if r > best_r:
            best_step, best_r = step, r
    # Refine: shrink a bracket around the coarse winner twice.
    width = (candidates[1] - candidates[0]) if len(candidates) > 1 else 0.1
    centre = best_step
    for _ in range(2):
        for delta in (-0.5, -0.25, 0.0, 0.25, 0.5):
            step = centre + delta * width
            if step <= 0:
                continue
            r = rayleigh(values, step)
            if r > best_r:
                best_step, best_r = step, r
        centre = best_step
        width /= 4.0
    return best_step, best_r


def _offset_for(values: list[float], step: float) -> float:
    """Grid offset (base) from the resultant phase, anchored near min."""
    cos_sum = sum(math.cos(_TWO_PI * (v / step)) for v in values)
    sin_sum = sum(math.sin(_TWO_PI * (v / step)) for v in values)
    phase = math.atan2(sin_sum, cos_sum) % _TWO_PI
    raw_offset = (phase / _TWO_PI) * step
    low = min(values)
    # Largest grid point <= low (grid points are offset + k*step).
    k = math.floor((low - raw_offset) / step)
    return raw_offset + k * step


def _fold(values: list[float], offset: float, step: float):
    symbols, residuals = [], []
    for v in values:
        symbol = int(round((v - offset) / step))
        symbols.append(symbol)
        residuals.append(round(v - (offset + symbol * step), 4))
    return symbols, residuals


def _null_best_r(rng: random.Random, values: list[float],
                 candidates: list[float], fractional: bool) -> float:
    n = len(values)
    low, high = min(values), max(values)
    if fractional:
        fracs = [abs(v - math.floor(v)) for v in values]
        lo_i, hi_i = math.floor(low), math.floor(high)
        draw = [
            rng.randint(lo_i, hi_i) + rng.choice(fracs) for _ in range(n)
        ]
    else:
        draw = [rng.uniform(low, high) for _ in range(n)]
    _, best_r = _best_step(draw, candidates)
    return best_r


def discover_grid(
    values: list[float],
    *,
    tolerance: float,
    seed: int = 1723,
    replicates: int = 200,
    declared_grid: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discover the grid behind one attribute sequence.

    Report keys: step, offset, rms_residual, max_residual,
    supporting, support_fraction, levels_used, rayleigh_R,
    null_exceedance, symbols, residuals, score, plus `grid` and an
    optional `declared` fit with `declared_vs_discovered_step_ratio`.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    base_block: dict[str, Any] = {
        "grid": {"source": "discovered", "step": None, "offset": None},
        "step": None, "offset": None,
        "symbols": [0] * n, "residuals": [0.0] * n,
        "supporting": 0, "support_fraction": 0.0,
        "mean_abs_residual": 0.0, "rms_residual": 0.0,
        "max_residual": 0.0, "max_abs_residual": 0.0,
        "levels_used": len(set(vals)),
        "rayleigh_R": 0.0, "null_exceedance": 1.0,
        "score": 0.0, "elements": n,
    }
    if n < 3 or max(vals) == min(vals):
        base_block["detail"] = "constant or too-short sequence; no grid to discover"
        _attach_declared(base_block, vals, tolerance, declared_grid)
        return base_block
    min_step = 2.0 * max(tolerance, 1e-9)
    candidates = _candidates(min(vals), max(vals), min_step)
    if not candidates:
        base_block["detail"] = "observed range too small for a resolvable step"
        _attach_declared(base_block, vals, tolerance, declared_grid)
        return base_block

    step, best_r = _best_step(vals, candidates)
    offset = _offset_for(vals, step)
    symbols, residuals = _fold(vals, offset, step)
    # Least-squares refit (value ~ offset + step * symbol), twice:
    # the Rayleigh phase offset can sit one step off when measured
    # values are systematically shrunk (e.g. tilt regression), which
    # would shift every recovered symbol by one.
    for _ in range(2):
        # Refit on supporting points only: an outlier element (a
        # chart baseline among bars) must not distort the slope.
        keep = [i for i, r in enumerate(residuals) if abs(r) <= tolerance]
        if len(keep) < 3:
            keep = list(range(len(vals)))
        kept_symbols = [symbols[i] for i in keep]
        if len(set(kept_symbols)) < 2:
            break
        kept_vals = [vals[i] for i in keep]
        mean_s = sum(kept_symbols) / len(kept_symbols)
        mean_v = sum(kept_vals) / len(kept_vals)
        var = sum((s - mean_s) ** 2 for s in kept_symbols)
        if var == 0:
            break
        cov = sum((s - mean_s) * (v - mean_v)
                  for s, v in zip(kept_symbols, kept_vals))
        slope = cov / var
        if slope <= 0:
            break
        step, offset = slope, mean_v - slope * mean_s
        symbols, residuals = _fold(vals, offset, step)
    best_r = rayleigh(vals, step)
    supporting = sum(1 for r in residuals if abs(r) <= tolerance)
    support_fraction = supporting / n if n else 0.0
    rms = math.sqrt(sum(r * r for r in residuals) / n) if n else 0.0

    rng = random.Random(seed)
    exceed = 0
    total = 0
    per_null: dict[str, float] = {}
    for fractional, label in ((False, "uniform"), (True, "fractional_parts")):
        hits = 0
        for _ in range(replicates):
            total += 1
            if _null_best_r(rng, vals, candidates, fractional) >= best_r:
                hits += 1
                exceed += 1
        per_null[label] = round(hits / replicates, 6) if replicates else 1.0
    null_exceedance = round(exceed / total, 6) if total else 1.0

    block = dict(base_block)
    block.update({
        "grid": {"source": "discovered", "step": round(step, 4),
                 "offset": round(offset, 4), "base": round(offset, 4)},
        "step": round(step, 4), "offset": round(offset, 4),
        "symbols": symbols, "residuals": residuals,
        "supporting": supporting,
        "support_fraction": round(support_fraction, 6),
        "mean_abs_residual": round(sum(abs(r) for r in residuals) / n, 4),
        "rms_residual": round(rms, 4),
        "max_residual": round(max((abs(r) for r in residuals), default=0.0), 4),
        "max_abs_residual": round(max((abs(r) for r in residuals), default=0.0), 4),
        "levels_used": len(set(symbols)),
        "rayleigh_R": round(best_r, 6),
        "null_exceedance": null_exceedance,
        "null": {"replicates_per_null": replicates,
                 "exceedance_by_null": per_null,
                 "seed": seed},
        # Significance-adjusted fit score: how well values sit on
        # the discovered grid, tapered to zero as the null
        # exceedance approaches the 0.05 level. Phase concentration
        # alone (a high R with scattered residues) scores low.
        "score": round(
            support_fraction
            * max(0.0, 1.0 - rms / max(tolerance, 1e-9))
            * max(0.0, 1.0 - null_exceedance / 0.05),
            6),
    })
    _attach_declared(block, vals, tolerance, declared_grid)
    return block


def fit_declared_grid(values: list[float], declared: dict[str, Any],
                      tolerance: float) -> dict[str, Any]:
    """Fit a declared prior grid (base/step or levels) to a sequence."""
    vals = [float(v) for v in values]
    if declared.get("step"):
        base, step = float(declared.get("base", 0.0)), float(declared["step"])
        symbols, residuals = _fold(vals, base, step)
        grid = {"source": "declared_prior", "base": base, "step": step}
    elif declared.get("levels"):
        levels = [float(x) for x in declared["levels"]]
        symbols, residuals = [], []
        for v in vals:
            idx = min(range(len(levels)), key=lambda i: abs(v - levels[i]))
            symbols.append(idx)
            residuals.append(round(v - levels[idx], 4))
        grid = {"source": "declared_prior", "levels": levels}
        base, step = (levels[0] if levels else 0.0), None
    else:
        return {"grid": {"source": "declared_prior"}, "detail": "empty declared grid"}
    supporting = sum(1 for r in residuals if abs(r) <= tolerance)
    n = len(vals) or 1
    return {
        "grid": grid, "symbols": symbols, "residuals": residuals,
        "supporting": supporting,
        "support_fraction": round(supporting / n, 6),
        "rms_residual": round(math.sqrt(sum(r * r for r in residuals) / n), 4),
        "max_residual": round(max((abs(r) for r in residuals), default=0.0), 4),
        "base": base, "step": step,
    }


def _attach_declared(block: dict[str, Any], vals: list[float],
                     tolerance: float,
                     declared_grid: dict[str, Any] | None) -> None:
    if not declared_grid:
        return
    declared = fit_declared_grid(vals, declared_grid, tolerance)
    block["declared"] = declared
    discovered_step = block.get("step")
    declared_step = declared.get("step")
    if discovered_step and declared_step:
        block["declared_vs_discovered_step_ratio"] = round(
            declared_step / discovered_step, 6)
    else:
        block["declared_vs_discovered_step_ratio"] = None
