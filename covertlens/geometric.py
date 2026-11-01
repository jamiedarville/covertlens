"""Quantization and structure tests for attribute sequences (CL-40, GEO-02/03).

Two deliberately separate tests over CL-39 segmentations:

**Quantization (GEO-02).** Each extracted channel (heights, gaps,
brightness, colour distances, tilt angles) has its grid
*discovered* from the sequence itself (CL-43: Rayleigh step sweep
with a seeded permutation null in `covertlens/grid.py`). A declared
grid may be supplied as a prior and is fitted and reported
alongside, never as the headline. The report is a measurement, not
a verdict: discovered grid step/offset, per-element residuals,
supporting element count/fraction, Rayleigh R and null exceedance.
A bare “pattern detected” output does not exist in this module.

**Structure (GEO-03).** Only a quantized sequence that maps
through a *simple, declared code* — registered in
`DECLARED_CODES` (alphabet position, timing ratios, bit packing)
— and whose mapped output passes that code's stated validator
may be labelled `structure_claimed`. Everything else that is
quantized is `quantized_without_structure`: a **weak triage
signal only**, never demonstrated encoding (GEO-05: a legitimate
chart is grid-snapped by design).

The finding follows DET-02, is labelled
`evidence_aid_not_decoded_message` (including any candidate mapped
preview — a declared-code mapping is a hypothesis for a
researcher, not a recovered message, C-09/C-02), and the
threshold config is an unfrozen placeholder: geometric has no
calibration or frozen points yet (CL-42 benchmarks first), so
nothing here can withhold or fail a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .grid import discover_grid
from .parsing import Finding
from .segmentation import SegmentationResult, segment_image

GEO_DETECTOR_NAME = "geometric-quantization-structure"
GEO_DETECTOR_VERSION = "1.0.0"
GEO_FAMILY = "geometric"
GEO_CONFIG_VERSION = "1.0.0"
SIGNAL_STRUCTURE = "structure_claimed"
SIGNAL_QUANTIZED = "quantized_without_structure"
SIGNAL_WEAK = "weak_signal"
SIGNAL_NONE = "no_signal"

_LIMITATIONS = (
    "quantization alone is not encoding: legitimate charts and "
    "layouts are grid-snapped by design (GEO-05)",
    "procedural synthetic scenes only; natural-image element "
    "segmentation is not covered",
    "structure is claimed only under a declared code in "
    "DECLARED_CODES; unregistered mappings are never inferred",
    "thresholds are unfrozen placeholders (no geometric freeze "
    "exists); this detector cannot withhold delivery",
)

# Declared lexicon for the alphabet_position code: the only words
# structure may claim through that code. Deliberately tiny and
# explicit — anything outside it is not grammatical *for this code*.
_ALPHABET_LEXICON = frozenset({
    "A", "I", "BE", "DO", "GO", "NO", "ON", "IN", "IS", "IT", "AT",
    "CAB", "BAD", "BED", "BEAD", "DEAD", "FACE", "HEAD", "DECAF",
    "DECODE", "SIGNAL", "GEO",
})


@dataclass(frozen=True)
class GeometricConfig:
    """Unfrozen placeholder operating points (calibration is CL-42+)."""

    version: str = GEO_CONFIG_VERSION
    status: str = "unfrozen_placeholder"
    enforceable: bool = False
    min_support_fraction: float = 0.9
    min_support_elements: int = 4
    null_alpha: float = 0.05  # stated level for a quantization claim (CL-43)
    weak_floor: float = 0.5
    residual_tolerance: float = 1.6          # px (heights/gaps)
    angle_residual_tolerance: float = 3.5    # degrees
    brightness_tolerance: float = 18.0       # grey levels
    colour_distance_tolerance: float = 3.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "enforceable": self.enforceable,
            "min_support_fraction": self.min_support_fraction,
            "min_support_elements": self.min_support_elements,
            "weak_floor": self.weak_floor,
            "operating_points": None,
        }


DEFAULT_GEO_CONFIG = GeometricConfig()


def _map_alphabet(symbols: list[int]) -> str:
    return "".join(chr(ord("A") + s) if 0 <= s < 26 else "?" for s in symbols)


def _valid_alphabet(text: str) -> bool:
    # Declared rule: the mapped text is, or begins with, a lexicon
    # word of at least three letters. Longer symbol streams are
    # judged on their leading word only; the preview shows the rest.
    return bool(text) and (
        text in _ALPHABET_LEXICON
        or any(text.startswith(word) for word in _ALPHABET_LEXICON if len(word) >= 3)
    )


def _map_timing(symbols: list[int]) -> list[int]:
    return [s + 1 for s in symbols]


def _valid_timing(ratios: list[int]) -> bool:
    for period in (1, 2, 3, 4):
        if len(ratios) >= 2 * period and all(
            ratios[i] == ratios[i % period] for i in range(len(ratios))
        ):
            return True
    return False


def _map_bits(symbols: list[int]) -> str:
    chars = []
    for i in range(0, len(symbols) - 7, 8):
        byte = 0
        for bit in symbols[i:i + 8]:
            byte = (byte << 1) | bit
        chars.append(chr(byte) if 32 <= byte < 127 else "�")
    return "".join(chars)


def _valid_bits(text: str) -> bool:
    return bool(text) and "�" not in text


# Simple declared codes (GEO-03). Keys are channel names; a code
# may claim structure only for its channel, only when quantized.
DECLARED_CODES: dict[str, dict[str, Any]] = {
    "height": {
        "code": "alphabet_position",
        "description": "symbol -> A=0 letter position",
        "map": _map_alphabet,
        "validate": _valid_alphabet,
    },
    "gap": {
        "code": "timing_ratios",
        "description": "symbol -> duration ratio (symbol+1), periodic motif",
        "map": _map_timing,
        "validate": _valid_timing,
    },
    "lit": {
        "code": "bit_packing",
        "description": "lit states -> bits -> bytes (MSB first)",
        "map": _map_bits,
        "validate": _valid_bits,
    },
}


_CHANNEL_TOLERANCES = ("height", "gap", "lit", "angle")


def _colour_channel(seg: SegmentationResult,
                    config: GeometricConfig) -> dict[str, Any]:
    """Colour via discovered exact-colour clusters (no declared palette).

    Repeated exact colours are the discovered palette; support is the
    fraction of elements sitting exactly (within tolerance) on one.
    """
    colours = [tuple(c) for c in seg.sequence("colour")]
    counts: dict[tuple[int, int, int], int] = {}
    for colour in colours:
        counts[colour] = counts.get(colour, 0) + 1
    palette = sorted(
        (c for c, n in counts.items() if n >= 2),
        key=lambda c: (-counts[c], c),
    )[:8]
    distances: list[float] = []
    symbols: list[int] = []
    for colour in colours:
        if palette:
            idx = min(range(len(palette)),
                      key=lambda i: _colour_dist(colour, palette[i]))
            symbols.append(idx)
            distances.append(round(_colour_dist(colour, palette[idx]), 4))
        else:
            symbols.append(-1)
            distances.append(999.0)
    n = len(colours) or 1
    supporting = sum(1 for d in distances if d <= config.colour_distance_tolerance)
    return {
        "grid": {"source": "discovered", "step": None, "offset": None,
                 "levels": [list(c) for c in palette],
                 "palette_source": "exact_colour_clusters"},
        "step": None, "offset": None,
        "symbols": symbols,
        "residuals": distances,
        "supporting": supporting,
        "support_fraction": round(supporting / n, 6),
        "mean_abs_residual": round(sum(distances) / n, 4),
        "rms_residual": round((sum(d * d for d in distances) / n) ** 0.5, 4),
        "max_residual": round(max(distances, default=0.0), 4),
        "max_abs_residual": round(max(distances, default=0.0), 4),
        "levels_used": len(set(s for s in symbols if s >= 0)),
        "rayleigh_R": 0.0, "null_exceedance": None,
        "quantization_method": "exact_palette_repetition",
        "score": round(supporting / n, 6),
        "elements": len(colours),
    }


def _colour_dist(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _channels(seg: SegmentationResult, config: GeometricConfig,
              declared_grid: dict[str, dict[str, Any]] | None = None
              ) -> dict[str, Any]:
    raw_values = {
        "height": [float(v) for v in seg.sequence("height")],
        "gap": [float(v) for v in seg.sequence("gap_to_next") if v is not None],
        "lit": [float(v) for v in seg.sequence("brightness")],
        "angle": [float(v) for v in seg.sequence("angle_deg")],
        # Colour varies by palette index, not by distance-to-palette
        # (an all-palette-exact scene has constant distance 0 but a
        # varying, information-carrying index sequence).
        "colour": [float(v) for v in seg.sequence("colour_index")],
    }
    tolerances = {
        "height": config.residual_tolerance,
        "gap": config.residual_tolerance,
        "lit": config.brightness_tolerance,
        "angle": config.angle_residual_tolerance,
    }
    channels: dict[str, Any] = {}
    for name in _CHANNEL_TOLERANCES:
        declared = (declared_grid or {}).get(name)
        block = discover_grid(
            raw_values[name], tolerance=tolerances[name],
            seed=1723 + 101 * _CHANNEL_TOLERANCES.index(name),
            declared_grid=declared,
        )
        # Pixel channels: encoded residuals are only rendering
        # rounding (<= 0.5px), so a claim also needs support at
        # half tolerance — this stops small discovered steps from
        # "fitting" arbitrary integer sequences. Angle measurement
        # carries a regression bias, so it keeps the rms gate only.
        strict_support = (
            sum(1 for r in block["residuals"]
                if abs(r) <= tolerances[name] / 2.0)
            / len(block["residuals"]) if block["residuals"] else 0.0
        )
        block["strict_support_fraction"] = round(strict_support, 6)
        strict_ok = (
            name == "angle"
            or strict_support >= config.min_support_fraction
        )
        block["quantized"] = bool(
            block["support_fraction"] >= config.min_support_fraction
            and block["levels_used"] >= 2
            and block["rayleigh_R"] >= 0.75
            and block["null_exceedance"] <= config.null_alpha
            and block["rms_residual"] <= tolerances[name]
            and strict_ok
        )
        if name != "angle":
            # Pixel/level channels score by strict fit too: a loose
            # grid that only fits at full tolerance is weak evidence.
            block["score"] = round(block["score"] * strict_support, 6)
        # Phase concentration is part of the evidence: a fit with
        # mediocre R is weaker than the residuals alone suggest.
        block["score"] = round(block["score"] * block["rayleigh_R"], 6)
        channels[name] = block
    colour = _colour_channel(seg, config)
    colour["quantized"] = bool(
        colour["support_fraction"] >= config.min_support_fraction
        and colour["levels_used"] >= 2
    )
    if declared_grid and declared_grid.get("colour"):
        colour["declared"] = declared_grid["colour"]
    channels["colour"] = colour
    for name, block in channels.items():
        block["elements"] = len(block["symbols"])
        # A constant channel carries no sequence information: one
        # repeated value is trivially "on grid" (upright bars have
        # angle 0; fixed-height scenes quantize heights). Only
        # channels that actually vary may support a claim.
        distinct = {
            round(v / max(config.residual_tolerance, 1e-9))
            for v in raw_values[name]
        }
        block["applicable"] = len(distinct) >= 2
        if not block["applicable"]:
            block["score"] = 0.0
            block["quantized"] = False
    return channels


def _structure(channel: str, block: dict[str, Any],
               config: GeometricConfig) -> dict[str, Any]:
    declared = DECLARED_CODES.get(channel)
    base = {
        "claimed": False,
        "code": declared["code"] if declared else None,
        "reason": "",
    }
    if block["support_fraction"] < config.min_support_fraction:
        base["reason"] = "sequence is not quantized at the required support"
        return base
    if block["elements"] < config.min_support_elements:
        base["reason"] = "too few supporting elements for a structure claim"
        return base
    if declared is None:
        base["reason"] = "no declared code registered for this channel"
        return base
    symbols = block["symbols"]
    if channel == "lit":
        # Discovered lit symbols are grid indices (e.g. 0 and 2 for a
        # 95-unit discovered step); the bit code consumes level ranks.
        rank = {s: i for i, s in enumerate(sorted(set(symbols)))}
        symbols = [rank[s] for s in symbols]
    mapped = declared["map"](symbols)
    preview = mapped if isinstance(mapped, str) else str(mapped)
    if declared["validate"](mapped):
        return {
            "claimed": True,
            "code": declared["code"],
            "mapped_preview": preview[:32],
            "reason": "quantized sequence maps through the declared "
                      "code to output passing its validator",
        }
    base["reason"] = "mapped output fails the declared code's validator"
    base["mapped_preview"] = preview[:32]
    return base


def analyze_geometric(
    seg: SegmentationResult, config: GeometricConfig | None = None,
    declared_grid: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Quantization + structure report over one segmentation (no finding
    when segmentation itself failed)."""
    active = config or DEFAULT_GEO_CONFIG
    if not seg.ok:
        return {
            "status": seg.status,
            "finding": None,
            "classification": SIGNAL_NONE,
            "detail": "segmentation failed; no geometric finding (not a clean score)",
        }
    channels = _channels(seg, active, declared_grid)
    primary_name = max(channels, key=lambda name: channels[name]["score"])
    primary = channels[primary_name]
    declared_fit = primary.get("declared") or {}
    declared_quantized = bool(
        declared_grid
        and primary_name in declared_grid
        and declared_fit.get("support_fraction", 0.0) >= active.min_support_fraction
    )
    quantized = bool(
        primary["applicable"]
        and primary["elements"] >= active.min_support_elements
        and (primary.get("quantized") or declared_quantized)
    )
    if quantized:
        structure = _structure(primary_name, primary, active)
    else:
        structure = {
            "claimed": False,
            "code": None,
            "reason": "primary channel is not an applicable, "
                      "sufficiently supported quantized channel",
        }
    if structure["claimed"]:
        classification = SIGNAL_STRUCTURE
    elif quantized:
        classification = SIGNAL_QUANTIZED
    elif primary["score"] >= active.weak_floor:
        classification = SIGNAL_WEAK
    else:
        classification = SIGNAL_NONE
    finding = Finding(
        family=GEO_FAMILY,
        detector_name=GEO_DETECTOR_NAME,
        detector_version=GEO_DETECTOR_VERSION,
        score=float(primary["score"]),
        coverage={
            "applicable": True,
            "elements": len(seg.elements),
            "channels_tested": sorted(channels),
            "segmenter": f"{seg.config.name} {seg.config.version}",
            "config_version": active.version,
            "config_status": active.status,
        },
        evidence={
            "label": "evidence_aid_not_decoded_message",
            "primary_channel": primary_name,
            "channels": channels,
            "structure": structure,
            "classification": classification,
        },
        limitations=_LIMITATIONS,
    )
    return {
        "status": "ok",
        "finding": finding,
        "classification": classification,
        "primary_channel": primary_name,
        "channels": channels,
        "structure": structure,
    }


def analyze_geometric_bytes(
    data: bytes, config: GeometricConfig | None = None,
    declared_grid: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Segment original bytes and run both geometric tests."""
    seg = segment_image(data)
    report = analyze_geometric(seg, config, declared_grid)
    report["segmentation"] = seg.to_dict()
    return report


def validate_geometric_report(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a geometric report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    finding = report.get("finding")
    if report.get("status") != "ok":
        need(finding is None, "failed segmentation must not produce a finding")
        return errors
    need(finding is not None, "ok report needs a finding")
    if finding is None:
        return errors
    need(finding.family == GEO_FAMILY, "finding family must be geometric")
    need(0.0 <= finding.score <= 1.0, "score must be in [0, 1]")
    evidence = finding.evidence
    need(evidence.get("label") == "evidence_aid_not_decoded_message",
         "geometric evidence must stay labelled as an aid (C-09)")
    for name, block in (evidence.get("channels") or {}).items():
        for key in ("grid", "symbols", "residuals", "supporting",
                    "support_fraction", "score"):
            need(key in block, f"channels.{name}.{key} is required (no bare verdicts)")
    structure = evidence.get("structure") or {}
    if report.get("classification") == SIGNAL_STRUCTURE:
        need(structure.get("claimed") is True,
             "structure_claimed requires a claimed structure block")
        need(bool(structure.get("code")),
             "structure_claimed requires a declared code")
    if report.get("classification") == SIGNAL_QUANTIZED:
        need(structure.get("claimed") is False,
             "quantized_without_structure must not claim structure")
    return errors
