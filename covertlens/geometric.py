"""Quantization and structure tests for attribute sequences (CL-40, GEO-02/03).

Two deliberately separate tests over CL-39 segmentations:

**Quantization (GEO-02).** Each extracted channel (heights, gaps,
brightness, colour distances, tilt angles) is fitted against its
declared grid from the CL-38 encoder configs. The report is a
measurement, not a verdict: grid base/step, per-element residuals,
supporting element count/fraction, and the sequence's own
continuous spread for contrast. A bare “pattern detected” output
does not exist in this module.

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

from .geometric_fixtures import GRIDS
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


def _grid_fit(values: list[float], base: float, step: float,
              tolerance: float) -> dict[str, Any]:
    symbols = [int(round((v - base) / step)) for v in values]
    residuals = [round(v - (base + s * step), 4) for v, s in zip(values, symbols)]
    supporting = sum(1 for r in residuals if abs(r) <= tolerance)
    mean_abs = sum(abs(r) for r in residuals) / len(residuals) if residuals else 0.0
    return {
        "grid": {"base": base, "step": step, "source": "declared (CL-38 encoder config)"},
        "symbols": symbols,
        "residuals": residuals,
        "supporting": supporting,
        "support_fraction": round(supporting / len(values), 6) if values else 0.0,
        "mean_abs_residual": round(mean_abs, 4),
        "max_abs_residual": round(max((abs(r) for r in residuals), default=0.0), 4),
        "score": round(
            (supporting / len(values)) * max(0.0, 1.0 - mean_abs / tolerance), 6
        ) if values and tolerance else 0.0,
    }


def _levels_fit(values: list[float], levels: tuple[float, ...],
                tolerance: float) -> dict[str, Any]:
    symbols, residuals = [], []
    for v in values:
        idx = min(range(len(levels)), key=lambda i: abs(v - levels[i]))
        symbols.append(idx)
        residuals.append(round(v - levels[idx], 4))
    supporting = sum(1 for r in residuals if abs(r) <= tolerance)
    mean_abs = sum(abs(r) for r in residuals) / len(residuals) if residuals else 0.0
    return {
        "grid": {"levels": list(levels), "source": "declared (CL-38 encoder config)"},
        "symbols": symbols,
        "residuals": residuals,
        "supporting": supporting,
        "support_fraction": round(supporting / len(values), 6) if values else 0.0,
        "mean_abs_residual": round(mean_abs, 4),
        "max_abs_residual": round(max((abs(r) for r in residuals), default=0.0), 4),
        "score": round(
            (supporting / len(values)) * max(0.0, 1.0 - mean_abs / tolerance), 6
        ) if values and tolerance else 0.0,
    }


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


def _channels(seg: SegmentationResult, config: GeometricConfig) -> dict[str, Any]:
    heights = [float(v) for v in seg.sequence("height")]
    gaps = [float(v) for v in seg.sequence("gap_to_next") if v is not None]
    brightness = [float(v) for v in seg.sequence("brightness")]
    colour_distances = [float(v) for v in seg.sequence("colour_distance")]
    angles = [float(v) for v in seg.sequence("angle_deg")]
    channels = {
        "height": _grid_fit(heights, GRIDS["height_position"]["base"],
                            GRIDS["height_position"]["step"], config.residual_tolerance),
        "gap": _grid_fit(gaps, GRIDS["gap_timing"]["base"],
                         GRIDS["gap_timing"]["step"], config.residual_tolerance),
        "lit": _levels_fit(brightness, tuple(GRIDS["lit_dark"]["levels"]),
                           config.brightness_tolerance),
        "angle": _grid_fit(angles, GRIDS["angle_tilt"]["base"],
                           GRIDS["angle_tilt"]["step"], config.angle_residual_tolerance),
    }
    colour = _levels_fit(colour_distances, (0.0,), config.colour_distance_tolerance)
    colour["grid"] = {"target_distance": 0.0, "source": "declared palette (CL-38)"}
    channels["colour"] = colour
    raw_values = {
        "height": heights, "gap": gaps, "lit": brightness,
        "angle": angles,
        # Colour varies by palette index, not by distance-to-palette
        # (an all-palette-exact scene has constant distance 0 but a
        # varying, information-carrying index sequence).
        "colour": [float(v) for v in seg.sequence("colour_index")],
    }
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
    mapped = declared["map"](block["symbols"])
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
    seg: SegmentationResult, config: GeometricConfig | None = None
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
    channels = _channels(seg, active)
    primary_name = max(channels, key=lambda name: channels[name]["score"])
    primary = channels[primary_name]
    quantized = (
        primary["applicable"]
        and primary["support_fraction"] >= active.min_support_fraction
        and primary["elements"] >= active.min_support_elements
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
    data: bytes, config: GeometricConfig | None = None
) -> dict[str, Any]:
    """Segment original bytes and run both geometric tests."""
    seg = segment_image(data)
    report = analyze_geometric(seg, config)
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
