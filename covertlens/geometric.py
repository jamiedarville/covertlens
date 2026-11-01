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

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .grid import discover_grid
from .parsing import AnalysisResult, AnalysisStatus, Finding
from .segmentation import SegmentationResult, segment_image

GEO_DETECTOR_NAME = "geometric-quantization-structure"
GEO_DETECTOR_VERSION = "2.0.0"
GEO_FAMILY = "geometric"
GEO_CONFIG_VERSION = "2.0.0"
SIGNAL_STRUCTURE = "structure_claimed"
SIGNAL_QUANTIZED = "quantized_without_structure"
SIGNAL_DECLARED = "quantized_declared_channel"
SIGNAL_WEAK = "weak_signal"
SIGNAL_NONE = "no_signal"
GEOMETRIC_CHANNELS = ("height", "gap", "lit", "colour", "angle")

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

# Committed word list (CL-46): trains the character trigram model
# used by every text-producing declared code. The file's hash is
# recorded in the detector config so a model change is a config
# change. Structure is claimed only when a mapped candidate beats
# a symbol-shuffle null at the stated level — never from a lexicon
# lookup alone.
_WORDLIST_PATH = Path(__file__).resolve().parent / "wordlist.txt"


def _load_wordlist() -> tuple[str, ...]:
    return tuple(
        word.strip().upper()
        for word in _WORDLIST_PATH.read_text(encoding="utf-8").split()
        if word.strip()
    )


WORDLIST = _load_wordlist()
WORDLIST_SHA256 = "sha256:" + hashlib.sha256(_WORDLIST_PATH.read_bytes()).hexdigest()


def _build_trigram_model(words: tuple[str, ...]):
    corpus = " ".join(words)
    trigram_counts: dict[str, dict[str, int]] = {}
    context_counts: dict[str, int] = {}
    vocab: set[str] = set(corpus)
    padded = "  " + corpus + " "
    for i in range(len(padded) - 2):
        ctx, ch = padded[i : i + 2], padded[i + 2]
        trigram_counts.setdefault(ctx, {})[ch] = (
            trigram_counts.setdefault(ctx, {}).get(ch, 0) + 1
        )
        context_counts[ctx] = context_counts.get(ctx, 0) + 1
    return trigram_counts, context_counts, vocab


_TRIGRAMS, _CONTEXTS, _VOCAB = _build_trigram_model(WORDLIST)
_TRIGRAM_ALPHA = 0.05


def trigram_score(text: str) -> float:
    """Mean smoothed log P(char | previous two) under the word-list model."""
    if len(text) < 3:
        return float("-inf")
    padded = "  " + text.upper() + " "
    total = 0.0
    count = 0
    vocab_size = max(1, len(_VOCAB))
    for i in range(len(padded) - 2):
        ctx, ch = padded[i : i + 2], padded[i + 2]
        numerator = _TRIGRAMS.get(ctx, {}).get(ch, 0) + _TRIGRAM_ALPHA
        denominator = _CONTEXTS.get(ctx, 0) + _TRIGRAM_ALPHA * vocab_size
        total += math.log(numerator / denominator)
        count += 1
    return total / count if count else float("-inf")


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
    residual_tolerance: float = 1.6  # px (heights/gaps)
    angle_residual_tolerance: float = 3.5  # degrees
    brightness_tolerance: float = 18.0  # grey levels
    colour_distance_tolerance: float = 3.0
    # Structure test v2 (CL-46): a claim needs at least k symbols
    # and must beat the symbol-shuffle null at the stated level.
    structure_min_symbols: int = 8
    structure_alpha: float = 0.01
    structure_replicates: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "enforceable": self.enforceable,
            "min_support_fraction": self.min_support_fraction,
            "min_support_elements": self.min_support_elements,
            "weak_floor": self.weak_floor,
            "operating_points": None,
            "structure": {
                "min_symbols": self.structure_min_symbols,
                "alpha": self.structure_alpha,
                "replicates": self.structure_replicates,
                "wordlist_sha256": WORDLIST_SHA256,
                "wordlist_words": len(WORDLIST),
            },
        }


DEFAULT_GEO_CONFIG = GeometricConfig()


def _map_alphabet(symbols: list[int], base: int = 0) -> str:
    return "".join(
        chr(ord("A") + s - base) if 0 <= s - base < 26 else "?" for s in symbols
    )


def _map_bits(symbols: list[int]) -> str:
    chars = []
    for i in range(0, len(symbols) - 7, 8):
        byte = 0
        for bit in symbols[i : i + 8]:
            byte = (byte << 1) | (bit & 1)
        chars.append(chr(byte) if 32 <= byte < 127 else "�")
    return "".join(chars)


def _map_base_k(symbols: list[int], base: int, digits_per_byte: int) -> str:
    chars = []
    for i in range(0, len(symbols) - digits_per_byte + 1, digits_per_byte):
        value = 0
        for d in symbols[i : i + digits_per_byte]:
            value = value * base + d
        chars.append(chr(value) if 32 <= value < 127 else "�")
    return "".join(chars)


def _periodicity_stat(sequence: list[float]) -> float:
    """Best lag-1..8 motif agreement plus autocorrelation (timing codes)."""
    n = len(sequence)
    if n < 4:
        return 0.0
    best = 0.0
    for lag in range(1, 9):
        if n - lag < 2:
            break
        agree = sum(1 for i in range(lag, n) if sequence[i] == sequence[i - lag]) / (
            n - lag
        )
        best = max(best, agree)
        mean = sum(sequence) / n
        num = sum(
            (sequence[i] - mean) * (sequence[i - lag] - mean) for i in range(lag, n)
        )
        den = sum((v - mean) ** 2 for v in sequence)
        autocorr = (num / den) if den else 0.0
        best = max(best, min(1.0, max(0.0, autocorr)))
    return round(best, 6)


def _ranks(symbols: list[int]) -> list[int]:
    rank = {s: i for i, s in enumerate(sorted(set(symbols)))}
    return [rank[s] for s in symbols]


# Declared codes v2 (GEO-03, CL-46). Every channel has at least one
# applicable code. Text codes are judged by the trigram model
# against a symbol-shuffle null; timing/rank codes by periodicity
# and lag-1..8 autocorrelation against the same kind of null.
CODES_V2: dict[str, list[dict[str, Any]]] = {
    "height": [
        {
            "code": "alphabet_position_a0",
            "kind": "text",
            "description": "symbol -> letter (A=0)",
            "map": lambda s: _map_alphabet(s, 0),
        },
        {
            "code": "alphabet_position_a1",
            "kind": "text",
            "description": "symbol -> letter (A=1)",
            "map": lambda s: _map_alphabet(s, 1),
        },
        {
            "code": "base_k_digits",
            "kind": "text",
            "description": "3 base-8 digits -> byte",
            "map": lambda s: _map_base_k(s, 8, 3),
        },
    ],
    "gap": [
        {
            "code": "timing_ratios",
            "kind": "timing",
            "description": "symbol -> duration ratio (symbol+1); "
            "periodic motif / autocorrelation",
            "map": lambda s: [float(x) + 1.0 for x in s],
        },
    ],
    "lit": [
        {
            "code": "bit_packing",
            "kind": "text",
            "description": "lit states -> bits -> bytes (MSB first)",
            "map": _map_bits,
        },
    ],
    "colour": [
        {
            "code": "base_k_digits",
            "kind": "text",
            "description": "5 base-3 digits -> byte",
            "map": lambda s: _map_base_k(s, 3, 5),
        },
        {
            "code": "ordinal_rank",
            "kind": "rank",
            "description": "rank pattern of the colour sequence",
            "map": lambda s: [float(x) for x in _ranks(s)],
        },
    ],
    "angle": [
        {
            "code": "base_k_digits",
            "kind": "text",
            "description": "4 base-5 digits -> byte",
            "map": lambda s: _map_base_k(s, 5, 4),
        },
        {
            "code": "ordinal_rank",
            "kind": "rank",
            "description": "rank pattern of the tilt sequence",
            "map": lambda s: [float(x) for x in _ranks(s)],
        },
    ],
}

# Backwards-compatible alias for the v1 registry name.
DECLARED_CODES = CODES_V2


_CHANNEL_TOLERANCES = ("height", "gap", "lit", "angle")


def _colour_channel(seg: SegmentationResult, config: GeometricConfig) -> dict[str, Any]:
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
            idx = min(
                range(len(palette)), key=lambda i: _colour_dist(colour, palette[i])
            )
            symbols.append(idx)
            distances.append(round(_colour_dist(colour, palette[idx]), 4))
        else:
            symbols.append(-1)
            distances.append(999.0)
    n = len(colours) or 1
    supporting = sum(1 for d in distances if d <= config.colour_distance_tolerance)
    return {
        "grid": {
            "source": "discovered",
            "step": None,
            "offset": None,
            "levels": [list(c) for c in palette],
            "palette_source": "exact_colour_clusters",
        },
        "step": None,
        "offset": None,
        # Structure codes consume the segmenter's palette-index
        # sequence (the payload digit space); support/residuals use
        # the discovered exact-colour clusters above.
        "symbols": [int(v) for v in seg.sequence("colour_index")],
        "residuals": distances,
        "supporting": supporting,
        "support_fraction": round(supporting / n, 6),
        "mean_abs_residual": round(sum(distances) / n, 4),
        "rms_residual": round((sum(d * d for d in distances) / n) ** 0.5, 4),
        "max_residual": round(max(distances, default=0.0), 4),
        "max_abs_residual": round(max(distances, default=0.0), 4),
        "levels_used": len(set(int(v) for v in seg.sequence("colour_index"))),
        "rayleigh_R": 0.0,
        "null_exceedance": None,
        "quantization_method": "exact_palette_repetition",
        "score": round(supporting / n, 6),
        "elements": len(colours),
    }


def _colour_dist(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _channels(
    seg: SegmentationResult,
    config: GeometricConfig,
    declared_grid: dict[str, dict[str, Any]] | None = None,
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
            raw_values[name],
            tolerance=tolerances[name],
            seed=1723 + 101 * _CHANNEL_TOLERANCES.index(name),
            declared_grid=declared,
        )
        # Pixel channels: encoded residuals are only rendering
        # rounding (<= 0.5px), so a claim also needs support at
        # half tolerance — this stops small discovered steps from
        # "fitting" arbitrary integer sequences. Angle measurement
        # carries a regression bias, so it keeps the rms gate only.
        strict_support = (
            sum(1 for r in block["residuals"] if abs(r) <= tolerances[name] / 2.0)
            / len(block["residuals"])
            if block["residuals"]
            else 0.0
        )
        block["strict_support_fraction"] = round(strict_support, 6)
        strict_ok = name == "angle" or strict_support >= config.min_support_fraction
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
            round(v / max(config.residual_tolerance, 1e-9)) for v in raw_values[name]
        }
        block["applicable"] = len(distinct) >= 2
        if not block["applicable"]:
            block["score"] = 0.0
            block["quantized"] = False
    return channels


def _shuffle_exceedance(observed: float, null_stats: list[float]) -> float:
    hits = sum(1 for s in null_stats if s >= observed)
    return (hits + 1) / (len(null_stats) + 1)


def _symbol_frames(symbols: list[int]) -> list[tuple[str, list[int]]]:
    """Discovered frame plus the min-anchored frame.

    Grid discovery recovers grid *lines* exactly, but absolute
    symbol numbering can sit one step off (the encoder base is not
    observable when the payload never uses level 0). Codes are
    therefore evaluated in both frames, and the shuffle null uses
    the same two frames, so the comparison stays honest.
    """
    frames = [("as_discovered", list(symbols))]
    low = min(symbols) if symbols else 0
    if low != 0:
        frames.append(("min_anchored", [s - low for s in symbols]))
    return frames


def _evaluate_code(
    code: dict[str, Any], symbols: list[int], config: GeometricConfig, seed: int
) -> dict[str, Any]:
    """Score one declared code against its symbol-shuffle null."""
    rng = random.Random(seed)
    mapper = code["map"]
    frames = _symbol_frames(symbols)
    if code["kind"] == "text":

        def _text_stat(frame_symbols: list[int]):
            text = str(mapper(frame_symbols))
            if len(text) < 3:
                return float("-inf"), text
            return trigram_score(text), text

        observed, text, frame_name = max(
            ((_text_stat(fs)[0], _text_stat(fs)[1], name) for name, fs in frames),
            key=lambda row: row[0],
        )
        if observed == float("-inf"):
            return {
                "code": code["code"],
                "claimed": False,
                "reason": "mapped text too short for a trigram claim",
                "_candidate_text": text,
            }
        printable = (
            sum(1 for ch in text if 32 <= ord(ch) < 127) / len(text) if text else 0.0
        )
        null_stats = []
        for _ in range(config.structure_replicates):
            shuffled = list(symbols)
            rng.shuffle(shuffled)
            null_stats.append(
                max(_text_stat(fs)[0] for _n, fs in _symbol_frames(shuffled))
            )
        exceedance = _shuffle_exceedance(observed, null_stats)
        finite_null = [s for s in null_stats if s != float("-inf")]
        llr = observed - (
            sum(finite_null) / len(finite_null) if finite_null else observed
        )
        claimed = bool(
            printable >= 0.9 and exceedance <= config.structure_alpha and llr > 0
        )
        return {
            "code": code["code"],
            "kind": "text",
            "claimed": claimed,
            "symbol_frame": frame_name,
            "trigram_score": round(observed, 6),
            "null_exceedance": round(exceedance, 6),
            "log_likelihood_ratio": round(llr, 6),
            "printable_fraction": round(printable, 6),
            "reason": (
                "trigram likelihood beats the symbol-shuffle null at the stated level"
                if claimed
                else "trigram likelihood does not beat the "
                "symbol-shuffle null at the stated level"
            ),
            "_candidate_text": text,
        }

    # timing / rank codes: periodicity + autocorrelation statistic.
    def _stat(frame_symbols: list[int]) -> float:
        return _periodicity_stat([float(v) for v in mapper(frame_symbols)])  # type: ignore[arg-type]

    observed = max(_stat(fs) for _n, fs in frames)
    null_stats = []
    for _ in range(config.structure_replicates):
        shuffled = list(symbols)
        rng.shuffle(shuffled)
        null_stats.append(max(_stat(fs) for _n, fs in _symbol_frames(shuffled)))
    exceedance = _shuffle_exceedance(observed, null_stats)
    claimed = bool(exceedance <= config.structure_alpha and observed >= 0.8)
    return {
        "code": code["code"],
        "kind": code["kind"],
        "claimed": claimed,
        "periodicity_stat": observed,
        "null_exceedance": round(exceedance, 6),
        "reason": (
            "periodic/autocorrelated structure beats the "
            "symbol-shuffle null at the stated level"
            if claimed
            else "periodicity does not beat the symbol-shuffle null at the stated level"
        ),
        "_candidate_text": None,
    }


def _structure(
    channel: str, block: dict[str, Any], config: GeometricConfig
) -> dict[str, Any]:
    """Structure test v2: declared codes + shuffle-null claims (CL-46).

    The returned block never contains mapped text. A claimed
    candidate is attached as `_candidate_text` for the caller to
    route to the reviewer evidence path; it is stripped before the
    finding is built.
    """
    codes = CODES_V2.get(channel) or []
    base: dict[str, Any] = {
        "claimed": False,
        "code": None,
        "reason": "",
        "codes_evaluated": [],
        "_candidate_text": None,
    }
    if block["support_fraction"] < config.min_support_fraction:
        base["reason"] = "sequence is not quantized at the required support"
        return base
    if block["elements"] < config.min_support_elements:
        base["reason"] = "too few supporting elements for a structure claim"
        return base
    symbols = [int(s) for s in block["symbols"]]
    if channel == "lit":
        # Discovered lit symbols are grid indices (e.g. 0 and 2 for a
        # 95-unit discovered step); the bit code consumes level ranks.
        symbols = _ranks(symbols)
    if len(symbols) < config.structure_min_symbols:
        base["reason"] = (
            f"too few symbols for a structure claim "
            f"({len(symbols)} < {config.structure_min_symbols})"
        )
        base["codes_evaluated"] = [
            {"code": c["code"], "claimed": False, "reason": base["reason"]}
            for c in codes
        ]
        return base
    if not codes:
        base["reason"] = "no declared code registered for this channel"
        return base
    evaluated = []
    for i, code in enumerate(codes):
        result = _evaluate_code(code, symbols, config, seed=4242 + 17 * i)
        evaluated.append(result)
        if result["claimed"]:
            return {
                "claimed": True,
                "code": code["code"],
                "reason": result["reason"],
                "trigram_score": result.get("trigram_score"),
                "null_exceedance": result.get("null_exceedance"),
                "log_likelihood_ratio": result.get("log_likelihood_ratio"),
                "periodicity_stat": result.get("periodicity_stat"),
                "printable_fraction": result.get("printable_fraction"),
                "codes_evaluated": [
                    {k: v for k, v in r.items() if not k.startswith("_")}
                    for r in evaluated
                ],
                "_candidate_text": result.get("_candidate_text"),
            }
    base["codes_evaluated"] = [
        {k: v for k, v in r.items() if not k.startswith("_")} for r in evaluated
    ]
    best = max(evaluated, key=lambda r: -(r.get("null_exceedance") or 1.0))
    base["code"] = best["code"]
    base["null_exceedance"] = best.get("null_exceedance")
    base["reason"] = "no declared code beats the shuffle null at the stated level"
    return base


def _cv(values: list[float]) -> float:
    if not values:
        return 1.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0 if all(v == 0 for v in values) else 1.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return (var**0.5) / abs(mean)


def chart_likeness(seg: SegmentationResult) -> dict[str, Any]:
    """Inferred chart-likeness in [0, 1] from segmentation alone (CL-45).

    Features: a long thin horizontal component spanning most
    elements (axis/baseline), near-equal element widths, near-equal
    gaps, and small text-like components near the axis. Reported as
    evidence and used as a prior on the height channel only — never
    as the sole discriminator (GEO-05).
    """
    elements = list(seg.elements)
    features = {
        "baseline_axis": 0.0,
        "equal_widths": 0.0,
        "equal_gaps": 0.0,
        "axis_text_marks": 0.0,
    }
    if len(elements) < 3:
        return {"score": 0.0, "features": features, "baseline_present": False}
    left = min(e["left"] for e in elements)
    right = max(e["left"] + e["width"] for e in elements)
    span = max(1, right - left)
    baseline = None
    for e in elements:
        if e["width"] >= 0.6 * span and e["height"] <= 4:
            baseline = e
            break
    if baseline is not None:
        features["baseline_axis"] = 0.5
    others = [e for e in elements if e is not baseline]
    if others:
        features["equal_widths"] = round(
            0.20 * max(0.0, 1.0 - _cv([float(e["width"]) for e in others]) / 0.30), 6
        )
        gaps = [
            float(e["gap_to_next"]) for e in others if e.get("gap_to_next") is not None
        ]
        if len(gaps) >= 2:
            features["equal_gaps"] = round(0.15 * max(0.0, 1.0 - _cv(gaps) / 0.50), 6)
    if baseline is not None and others:
        areas = sorted(e["area"] for e in others)
        median_area = areas[len(areas) // 2] or 1
        text_like = sum(
            1
            for e in others
            if e["area"] <= 0.2 * median_area
            and abs((e["top"] + e["height"]) - baseline["top"]) <= 8
        )
        features["axis_text_marks"] = round(0.15 * min(1.0, text_like / 2.0), 6)
    return {
        "score": round(min(1.0, sum(features.values())), 6),
        "features": features,
        "baseline_present": baseline is not None,
    }


def analyze_geometric(
    seg: SegmentationResult,
    config: GeometricConfig | None = None,
    declared_grid: dict[str, dict[str, Any]] | None = None,
    declared_context: dict[str, Any] | None = None,
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
    # Scene context (CL-45, GEO-05): a channel declared for this
    # task before the run is a legitimate data carrier. Declared +
    # quantized logs as quantized_declared_channel; structured +
    # undeclared is the enforceable-grade signal (the family stays
    # log-only until its thresholds freeze); quantized + undeclared
    # + unstructured stays triage.
    declared_channels = set((declared_context or {}).get("declared_channels") or ())
    channel_declared = primary_name in declared_channels
    # A declared channel that is itself quantized marks the scene's
    # quantization as legitimate even when an artefact channel
    # (e.g. baseline brightness) out-scores it.
    declared_quantized_channels = sorted(
        name
        for name in declared_channels
        if name in channels
        and channels[name].get("quantized")
        and channels[name].get("applicable")
    )
    likeness = chart_likeness(seg)
    if quantized and channel_declared:
        # Declared channel: legitimate data carrier, logs only —
        # even when its sequence is structured.
        classification = SIGNAL_DECLARED
        signal_grade = "log_declared_channel"
    elif structure["claimed"]:
        classification = SIGNAL_STRUCTURE
        signal_grade = "enforceable_grade"
    elif quantized and declared_quantized_channels:
        classification = SIGNAL_DECLARED
        signal_grade = "log_declared_channel"
    elif quantized:
        classification = SIGNAL_QUANTIZED
        signal_grade = "triage"
    elif primary["score"] >= active.weak_floor:
        classification = SIGNAL_WEAK
        signal_grade = "triage"
    else:
        classification = SIGNAL_NONE
        signal_grade = "none"
    # The candidate decode never enters the finding (CL-46): it is
    # returned transiently so the caller can write it to the
    # reviewer evidence path (EvidenceGateway, R-08).
    candidate_text = structure.pop("_candidate_text", None)
    candidate_decode = None
    if structure.get("claimed") and candidate_text:
        candidate_decode = {
            "code": structure.get("code"),
            "text": candidate_text,
            "via": "evidence_gateway_reviewer_path",
        }
    height_prior = None
    if primary_name == "height" and likeness["score"] >= 0.7:
        # Chart-likeness is a prior on the height channel only:
        # it annotates triage, it never decides a classification.
        height_prior = (
            "chart-like scene: height quantization is expected for "
            "data visualizations; treat as triage unless structure "
            "is claimed under a declared code"
        )
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
            "signal_grade": signal_grade,
            "chart_likeness": likeness,
            "declared_context": {
                "declared_channels": sorted(declared_channels),
                "context": (declared_context or {}).get("context"),
                "primary_channel_declared": channel_declared,
                "declared_quantized_channels": declared_quantized_channels,
            }
            if declared_context
            else None,
            "height_prior": height_prior,
        },
        limitations=_LIMITATIONS,
    )
    return {
        "status": "ok",
        "finding": finding,
        "classification": classification,
        "signal_grade": signal_grade,
        "primary_channel": primary_name,
        "channels": channels,
        "structure": structure,
        "chart_likeness": likeness,
        "declared_context": declared_context,
        "candidate_decode": candidate_decode,
    }


def detect_geometric(
    data: bytes, result: AnalysisResult, declared_context: dict[str, Any] | None = None
) -> Finding | None:
    """DET-02 finding for one parsed PNG; None when not applicable.

    Attached by `analyze_all_bytes` as the fourth channel family
    (CL-44). JPEG and failed parses get no geometric finding: the
    segmenter supports PNG rasters only and failures are never
    converted into clean scores (C-02).
    """
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind != "png":
        return None
    return analyze_geometric_bytes(data, declared_context=declared_context).get(
        "finding"
    )


def analyze_geometric_bytes(
    data: bytes,
    config: GeometricConfig | None = None,
    declared_grid: dict[str, dict[str, Any]] | None = None,
    declared_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Segment original bytes and run both geometric tests."""
    seg = segment_image(data)
    report = analyze_geometric(seg, config, declared_grid, declared_context)
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
    need(
        evidence.get("label") == "evidence_aid_not_decoded_message",
        "geometric evidence must stay labelled as an aid (C-09)",
    )
    for name, block in (evidence.get("channels") or {}).items():
        for key in (
            "grid",
            "symbols",
            "residuals",
            "supporting",
            "support_fraction",
            "score",
        ):
            need(key in block, f"channels.{name}.{key} is required (no bare verdicts)")
    structure = evidence.get("structure") or {}
    for banned in (
        "mapped_preview",
        "candidate_text",
        "_candidate_text",
        "mapped_text",
    ):
        need(
            banned not in structure,
            f"structure.{banned} must not appear in a finding; "
            "candidate decodes live on the reviewer evidence path (CL-46)",
        )
    if report.get("classification") == SIGNAL_STRUCTURE:
        need(
            structure.get("claimed") is True,
            "structure_claimed requires a claimed structure block",
        )
        need(bool(structure.get("code")), "structure_claimed requires a declared code")
    if report.get("classification") == SIGNAL_QUANTIZED:
        need(
            structure.get("claimed") is False,
            "quantized_without_structure must not claim structure",
        )
    if report.get("classification") == SIGNAL_DECLARED:
        declared = evidence.get("declared_context") or {}
        need(
            declared.get("primary_channel_declared") is True
            or bool(declared.get("declared_quantized_channels")),
            "quantized_declared_channel requires a declared, "
            "quantized channel for the task (CL-45)",
        )
    return errors
