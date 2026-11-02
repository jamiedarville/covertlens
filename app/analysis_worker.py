"""Process-pool analysis worker for the web service (CL-47, CL-48).

Runs the library pipeline on original bytes and returns
JSON-shaped data. Reviewer-only material is stripped here: the
geometric candidate decode never crosses into an API response
(it belongs to the EvidenceGateway reviewer path, CL-46), and
the segmentation ``decoded_message`` slot is removed entirely
so the API cannot carry decoded text (CL-48).

CL-48 adds ``geometric.overlay``: the display series the Analyze
page plots, computed here from the measured sequences with the
library's own ``rayleigh`` statistic, so every number on screen
is present verbatim in the ``/api/analyze`` response and the
frontend only renders. Per geometric channel it carries the raw
attribute values, a sampled Rayleigh periodogram over the same
candidate-step range the grid discovery sweeps (with the
discovered step and its headline R included verbatim), and
server-binned residual histogram counts.
"""

from __future__ import annotations

import os
from typing import Any

MAX_PIXELS_DEFAULT = 20_000_000

OVERLAY_VERSION = "1.0.0"
_HISTOGRAM_BINS = 9
# Display sweep budget: enough points to show the Rayleigh peak
# shape without making the worker do discovery-scale work twice.
_PERIODOGRAM_POINTS = 140
_PERIODOGRAM_POINTS_LARGE = 60
_LARGE_SEQUENCE = 2_000
_PRIMARY_ONLY_ABOVE = 5_000


def _max_pixels() -> int:
    try:
        return int(os.environ.get("COVERTLENS_MAX_PIXELS", MAX_PIXELS_DEFAULT))
    except ValueError:
        return MAX_PIXELS_DEFAULT


def _candidate_steps(values: list[float], tolerance: float) -> list[float]:
    """Candidate steps over the grid-discovery sweep range (CL-43).

    Mirrors ``covertlens.grid`` bounds: from twice the channel
    tolerance to half the observed range. The periodogram samples
    this list for display; discovery itself stays in the library.
    """
    low, high = min(values), max(values)
    span = high - low
    min_step = 2.0 * max(tolerance, 1e-9)
    max_step = span / 2.0
    if span <= 0 or max_step <= min_step:
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


def _periodogram(
    values: list[float], tolerance: float, channel: dict[str, Any]
) -> dict[str, Any]:
    """Sampled Rayleigh R(step) sweep for one channel (CL-48)."""
    from covertlens.grid import rayleigh

    discovered_step = channel.get("step")
    base: dict[str, Any] = {
        "discovered_step": discovered_step,
        "discovered_rayleigh_R": channel.get("rayleigh_R"),
    }
    if len(values) < 3 or max(values) == min(values):
        return {
            **base,
            "available": False,
            "reason": "constant or too-short sequence; no sweep",
            "points": [],
        }
    candidates = _candidate_steps(values, tolerance)
    if not candidates:
        return {
            **base,
            "available": False,
            "reason": "observed range too small for a resolvable step",
            "points": [],
        }
    budget = (
        _PERIODOGRAM_POINTS
        if len(values) <= _LARGE_SEQUENCE
        else _PERIODOGRAM_POINTS_LARGE
    )
    if len(candidates) > budget:
        stride = (len(candidates) - 1) / (budget - 1)
        sampled = [candidates[round(i * stride)] for i in range(budget)]
    else:
        sampled = candidates
    points = [
        {"step": round(s, 4), "rayleigh_R": round(rayleigh(values, s), 6)}
        for s in sampled
    ]
    # The headline discovered step/R must appear verbatim so the
    # marker the page draws is exactly the library measurement.
    if discovered_step is not None and not any(
        abs(p["step"] - discovered_step) < 1e-9 for p in points
    ):
        points.append(
            {
                "step": round(float(discovered_step), 4),
                "rayleigh_R": channel.get("rayleigh_R"),
            }
        )
        points.sort(key=lambda p: p["step"])
    return {**base, "available": True, "reason": None, "points": points}


def _histogram(residuals: list[float], tolerance: float) -> dict[str, Any]:
    """Fixed-bin residual histogram, counted server-side (CL-48)."""
    if not residuals:
        return {"bin_edges": [], "counts": [], "tolerance": tolerance}
    bound = max(max(abs(r) for r in residuals), abs(tolerance))
    if bound <= 0:
        bound = 1.0
    edges = [
        round(-bound + 2.0 * bound * i / _HISTOGRAM_BINS, 4)
        for i in range(_HISTOGRAM_BINS + 1)
    ]
    counts = [0] * _HISTOGRAM_BINS
    width = 2.0 * bound / _HISTOGRAM_BINS
    for r in residuals:
        idx = int((r + bound) / width)
        counts[min(idx, _HISTOGRAM_BINS - 1)] += 1
    return {"bin_edges": edges, "counts": counts, "tolerance": tolerance}


def _overlay_block(geometric: dict[str, Any]) -> dict[str, Any] | None:
    """Build the CL-48 display series from a geometric report."""
    from covertlens.geometric import GeometricConfig

    segmentation = geometric.get("segmentation") or {}
    sequences = segmentation.get("sequences") or {}
    channels = geometric.get("channels") or {}
    if not sequences or not channels:
        return None
    config = GeometricConfig()
    # Channel -> (segmentation attribute, unit, tolerance). This is
    # the detector's own mapping (covertlens.geometric._channels);
    # colour residuals are palette distances, hence its distance
    # tolerance, and it has no Rayleigh grid by construction.
    specs: dict[str, tuple[str, str, float]] = {
        "height": ("height", "px", config.residual_tolerance),
        "gap": ("gap_to_next", "px", config.residual_tolerance),
        "lit": ("brightness", "grey levels", config.brightness_tolerance),
        "angle": ("angle_deg", "degrees", config.angle_residual_tolerance),
        "colour": ("colour_index", "palette index", config.colour_distance_tolerance),
    }
    primary = geometric.get("primary_channel")
    out: dict[str, Any] = {}
    for name, (attribute, unit, tolerance) in specs.items():
        channel = channels.get(name)
        if channel is None or attribute not in sequences:
            continue
        values = [float(v) for v in sequences[attribute] if v is not None]
        residuals = [float(r) for r in channel.get("residuals") or []]
        entry: dict[str, Any] = {
            "sequence_attribute": attribute,
            "unit": unit,
            "tolerance": tolerance,
            "values": values,
            "residual_histogram": _histogram(residuals, tolerance),
        }
        if name == "colour":
            entry["periodogram"] = {
                "available": False,
                "reason": (
                    "colour is scored by exact palette repetition, not a Rayleigh grid"
                ),
                "discovered_step": None,
                "discovered_rayleigh_R": channel.get("rayleigh_R"),
                "points": [],
            }
        elif len(values) > _PRIMARY_ONLY_ABOVE and name != primary:
            entry["periodogram"] = {
                "available": False,
                "reason": "sequence too long; sweep shown for primary channel",
                "discovered_step": channel.get("step"),
                "discovered_rayleigh_R": channel.get("rayleigh_R"),
                "points": [],
            }
        else:
            entry["periodogram"] = _periodogram(values, tolerance, channel)
        out[name] = entry
    if not out:
        return None
    return {"version": OVERLAY_VERSION, "channels": out}


def analyze_bytes(data: bytes, max_pixels: int | None = None) -> dict[str, Any]:
    """Analyze one uploaded artifact; explicit oversized status (CL-47)."""
    if max_pixels is None:
        max_pixels = _max_pixels()
    from covertlens.geometric import analyze_geometric_bytes
    from covertlens.metadata import analyze_all_bytes
    from covertlens.parsing import analyze_bytes as parse_bytes
    from covertlens.verdicts import decide_verdict

    parsed = parse_bytes(data)
    base: dict[str, Any] = {
        "status": parsed.status.value,
        "analysis": None,
        "geometric": None,
        "decision": None,
    }
    if parsed.status.value != "parsed":
        return base
    image = parsed.image or {}
    if parsed.media_kind in ("png", "jpeg") and image.get("width"):
        width, height = int(image["width"]), int(image["height"])
        if width * height > max_pixels:
            # Explicit oversized status instead of an unbounded
            # pure-Python decode/segmentation (CL-47 acceptance).
            base["status"] = "oversized"
            base["detail"] = (
                f"image is {width}x{height} "
                f"({width * height} px > {max_pixels} px limit)"
            )
            return base

    result = analyze_all_bytes(data)
    base["analysis"] = result.to_dict()
    if parsed.media_kind in ("png", "jpeg"):
        geometric = analyze_geometric_bytes(data)
        geometric.pop("candidate_decode", None)  # reviewer-only (CL-46)
        geometric.pop("finding", None)  # already in analysis.findings
        segmentation = geometric.get("segmentation")
        if isinstance(segmentation, dict):
            # No decoded text crosses the API, not even an empty
            # slot a future change could fill (CL-48).
            segmentation.pop("decoded_message", None)
        overlay = _overlay_block(geometric)
        if overlay is not None:
            geometric["overlay"] = overlay
        base["geometric"] = geometric
    if result.findings:
        base["decision"] = decide_verdict(result.findings).to_dict()
    return base
