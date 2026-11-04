"""Quantization and structure tests for attribute sequences (CL-40, GEO-02/03).

Two deliberately separate tests over CL-39 segmentations:

**Quantization (GEO-02).** Each extracted channel (heights, gaps,
brightness, tilt angles) has its grid *discovered* from the sequence
itself (CL-43: Rayleigh step sweep with a seeded permutation null in
`covertlens/grid.py`); colour levels are discovered as well-separated
colour clusters, never read from a fixture palette (CL-78). Support
is measured at a *decode margin*: an element supports the grid when
its residual is within `decode_margin_fraction` of the discovered
step (never tighter than the channel's measurement tolerance), which
is what a receiver rounding to the nearest level can still read. A
channel whose support holds is *decodable*; it is *quantized* when,
in addition, its Rayleigh concentration beats the permutation null
(CL-78: a pixel of jitter must not hide a grid). A declared grid may
be supplied as a prior and is fitted alongside, never as the
headline. The report is a measurement, not a verdict.

**Structure (GEO-03).** Every decodable channel is tested (CL-78),
not only the top-scoring one. A sequence that maps through a
*simple, declared code* (`CODES_V2`) and beats a symbol-shuffle null
may be labelled `structure_claimed`. The level is family-wise:
`structure_alpha` is split (Bonferroni) over every test in the image,
where a test is one statistic (trigram or periodicity) maximised over a
channel's codes and symbol frames, with the shuffle null taking the same
maximum. A channel the task declared before the run is still tested, at
a level stricter by `declared_prior_factor`: a declaration lowers the
prior, it is not an exemption. Quantized sequences without a claim
are `quantized_without_structure`: a **weak triage signal only**
(GEO-05: a legitimate chart is grid-snapped by design).

The finding follows DET-02, is labelled
`evidence_aid_not_decoded_message`, and never carries a symbol
sequence: channels report a digest, count and range instead (CL-78).
A claimed candidate decode is returned transiently so the caller can
route it to the reviewer evidence path (C-09/C-02). This module holds
measurement parameters only. The ladder operating points that turn a
finding into a verdict are the CL-54 freeze in
`config/frozen-thresholds.json`, under which a structure-grade
finding is withheld.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._validation import make_need
from .grid import discover_grid
from .parsing import AnalysisResult, AnalysisStatus, Finding
from .segmentation import SegmentationResult, discover_palette, segment_image

GEO_DETECTOR_NAME = "geometric-quantization-structure"
# CL-78: decode-margin quantization, structure on every decodable
# channel, declared channels tested at a stricter level, discovered
# colour palette and digested symbols. Replay pins must distinguish
# these findings from the 2.x detector.
GEO_DETECTOR_VERSION = "3.0.0"
GEO_FAMILY = "geometric"
GEO_CONFIG_VERSION = "3.0.0"
SIGNAL_STRUCTURE = "structure_claimed"
SIGNAL_QUANTIZED = "quantized_without_structure"
SIGNAL_DECLARED = "quantized_declared_channel"
SIGNAL_WEAK = "weak_signal"
SIGNAL_NONE = "no_signal"
# Score bands (CL-78). A finding without a structure claim never
# scores above the ceiling; a structure claim never scores below the
# floor. The frozen enforcement point is calibrated above the ceiling,
# so quantization alone can never withhold.
NON_STRUCTURE_SCORE_CEILING = 0.5
STRUCTURE_SCORE_FLOOR = 0.75
GEOMETRIC_CHANNELS = ("height", "gap", "lit", "colour", "angle")

_LIMITATIONS = (
    "quantization alone is not encoding: legitimate charts and "
    "layouts are grid-snapped by design (GEO-05)",
    "detector calibration uses procedural synthetic scenes; five real-image "
    "segmentation checks do not establish general natural-image detection coverage",
    "structure is claimed only under a declared code in "
    "DECLARED_CODES; unregistered mappings are never inferred",
    "structure needs at least 8 symbols: shorter sequences cannot beat "
    "the shuffle null at the stated level and top out at triage",
    "enforcement requires the frozen geometric ladder points; "
    "synthetic calibration does not establish natural-image coverage",
)

_JPEG_LIMITATION = (
    "jpeg input: elements were segmented from a lossy pixel "
    "reconstruction, so measured attributes are approximate "
    "(CL-52 fidelity limitation)"
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
    """Measurement parameters only.

    The ladder operating points are not here: they are the CL-54
    freeze (`config/frozen-thresholds.json`), which withholds
    structure-grade findings.
    """

    version: str = GEO_CONFIG_VERSION
    status: str = "measurement_parameters"
    min_support_fraction: float = 0.9
    min_support_elements: int = 4
    null_alpha: float = 0.05  # stated level for a quantization claim (CL-43)
    weak_floor: float = 0.5
    residual_tolerance: float = 1.6  # px (heights/gaps)
    angle_residual_tolerance: float = 3.5  # degrees
    brightness_tolerance: float = 18.0  # grey levels
    # CL-78: an element supports a grid when its residual is within
    # this fraction of the discovered step (never below the channel
    # tolerance). A receiver rounding to the nearest level reads
    # anything under half a step; a quarter step keeps a margin.
    decode_margin_fraction: float = 0.25
    # CL-78: minimum phase concentration for a quantization claim.
    # Significance comes from the permutation null, not from R.
    min_rayleigh_R: float = 0.6
    # CL-78: colour levels are discovered clusters of this radius
    # (Euclidean RGB). Levels closer than `colour_min_separation`
    # are one continuous colour range, not a palette.
    colour_cluster_radius: float = 12.0
    colour_min_separation: float = 24.0
    # Structure test (CL-46, CL-78): a claim needs at least k
    # symbols and must beat the symbol-shuffle null at the stated
    # family-wise level, split over every test in the image (one test
    # per channel and statistic kind, maximised over its codes).
    # Below 8 symbols the shuffle null cannot reach that level for a
    # five-letter word (5! = 120 orderings), so shorter sequences
    # top out at quantization (triage).
    structure_min_symbols: int = 8
    structure_alpha: float = 0.01
    structure_replicates: int = 1999
    # A declared channel is tested at structure level x this factor.
    declared_prior_factor: float = 0.1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "operating_points": "config/frozen-thresholds.json",
            "min_support_fraction": self.min_support_fraction,
            "min_support_elements": self.min_support_elements,
            "weak_floor": self.weak_floor,
            "quantization": {
                "null_alpha": self.null_alpha,
                "decode_margin_fraction": self.decode_margin_fraction,
                "min_rayleigh_R": self.min_rayleigh_R,
                "colour_cluster_radius": self.colour_cluster_radius,
                "colour_min_separation": self.colour_min_separation,
            },
            "structure": {
                "min_symbols": self.structure_min_symbols,
                "alpha": self.structure_alpha,
                "alpha_scope": "family_wise_bonferroni_over_tests",
                "test_unit": "max statistic over a channel's codes of one kind",
                "replicates": self.structure_replicates,
                "declared_prior_factor": self.declared_prior_factor,
                "wordlist_sha256": WORDLIST_SHA256,
                "wordlist_words": len(WORDLIST),
            },
            "score_bands": {
                "non_structure_ceiling": NON_STRUCTURE_SCORE_CEILING,
                "structure_floor": STRUCTURE_SCORE_FLOOR,
            },
        }


DEFAULT_GEO_CONFIG = GeometricConfig()

# Mapped symbols outside a code's alphabet. Not printable, so a run
# of invalid symbols can never pass the printable check (CL-78; the
# old "?" marker counted as printable).
_INVALID = "�"


def _map_alphabet(symbols: list[int], base: int = 0) -> str:
    return "".join(
        chr(ord("A") + s - base) if 0 <= s - base < 26 else _INVALID for s in symbols
    )


def _map_bits(symbols: list[int]) -> str:
    chars = []
    for i in range(0, len(symbols) - 7, 8):
        byte = 0
        for bit in symbols[i : i + 8]:
            byte = (byte << 1) | (bit & 1)
        chars.append(chr(byte) if 32 <= byte < 127 else _INVALID)
    return "".join(chars)


def _map_base_k(symbols: list[int], base: int, digits_per_byte: int) -> str:
    chars = []
    for i in range(0, len(symbols) - digits_per_byte + 1, digits_per_byte):
        value = 0
        for d in symbols[i : i + digits_per_byte]:
            value = value * base + d
        chars.append(chr(value) if 32 <= value < 127 else _INVALID)
    return "".join(chars)


def _digits_per_byte(base: int) -> int:
    """Digits a base-k code spends per ASCII character (k=3 -> 5)."""
    if base <= 2:
        return 8
    return math.ceil(math.log(128) / math.log(base))


def _map_palette_digits(symbols: list[int]) -> str:
    """Base-k digits over a discovered palette of k levels (CL-78)."""
    base = max(2, max(symbols, default=0) + 1)
    return _map_base_k(symbols, base, _digits_per_byte(base))


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
            "description": "ceil(log_k 128) base-k digits -> byte "
            "(k = discovered palette size; k=3 -> 5 digits)",
            "map": _map_palette_digits,
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


_GRID_CHANNELS = ("height", "gap", "lit", "angle")


def _colour_channel(seg: SegmentationResult, config: GeometricConfig) -> dict[str, Any]:
    """Colour levels discovered from the image (CL-78).

    Element colours are clustered (`colour_cluster_radius`); clusters
    used by at least two elements are the palette. A palette is a
    grid only when its levels are well separated
    (`colour_min_separation`): a continuous run of shades clusters
    into near-touching levels and is not a code. Symbols are palette
    indices in canonical hue-then-value order; the structure test
    tries every relabelling, so the order carries no assumption.
    """
    colours = [tuple(int(v) for v in c) for c in seg.sequence("colour")]
    n = len(colours)
    radius = config.colour_cluster_radius
    seeds = discover_palette(colours, radius)
    nearest_seed = [
        min(range(len(seeds)), key=lambda i: math.dist(c, seeds[i])) for c in colours
    ]
    uses: dict[int, int] = {}
    for index in nearest_seed:
        uses[index] = uses.get(index, 0) + 1
    palette = [seed for i, seed in enumerate(seeds) if uses.get(i, 0) >= 2][:8]
    symbols: list[int] = []
    distances: list[float] = []
    for colour in colours:
        if palette:
            idx = min(range(len(palette)), key=lambda i: math.dist(colour, palette[i]))
            symbols.append(idx)
            distances.append(round(math.dist(colour, palette[idx]), 4))
        else:
            symbols.append(0)
            distances.append(round(2.0 * radius, 4))
    separation = (
        min(
            math.dist(palette[i], palette[j])
            for i in range(len(palette))
            for j in range(i + 1, len(palette))
        )
        if len(palette) >= 2
        else None
    )
    separated = separation is not None and separation >= config.colour_min_separation
    # Decode margin for colour: an element supports a level when it sits
    # within a quarter of the palette separation (and the cluster
    # radius). A continuous run of shades split into two clusters has
    # members far from either seed and fails; a jittered palette with
    # distant levels passes.
    support_tolerance = (
        min(radius, config.decode_margin_fraction * separation)
        if separation is not None
        else radius
    )
    supporting = sum(1 for d in distances if d <= support_tolerance)
    support = supporting / n if n else 0.0
    rms = (sum(d * d for d in distances) / n) ** 0.5 if n else 0.0
    levels_used = len(set(symbols))
    decodable = bool(
        separated and support >= config.min_support_fraction and levels_used >= 2
    )
    return {
        "grid": {
            "source": "discovered",
            "step": None,
            "offset": None,
            "levels": [list(c) for c in palette],
            "palette_source": "discovered_colour_clusters",
            "min_level_separation": (
                round(separation, 4) if separation is not None else None
            ),
        },
        "step": None,
        "offset": None,
        "symbols": symbols,
        "residuals": distances,
        "supporting": supporting,
        "support_fraction": round(support, 6),
        "decode_tolerance": round(support_tolerance, 4),
        "decode_support_fraction": round(support, 6),
        "mean_abs_residual": round(sum(distances) / n, 4) if n else 0.0,
        "rms_residual": round(rms, 4),
        "max_residual": round(max(distances, default=0.0), 4),
        "max_abs_residual": round(max(distances, default=0.0), 4),
        "levels_used": levels_used,
        "rayleigh_R": 0.0,
        "null_exceedance": None,
        "quantization_method": "separated_palette_clusters",
        "decodable": decodable,
        # Colour has no Rayleigh null: a well-separated palette whose
        # levels repeat is its quantization test.
        "quantized": decodable,
        "score": (
            round(support * max(0.0, 1.0 - rms / support_tolerance), 6)
            if separated
            else 0.0
        ),
        "elements": n,
    }


def _apply_decode_margin(
    block: dict[str, Any],
    tolerance: float,
    config: GeometricConfig,
    *,
    name_is_angle: bool = False,
) -> None:
    """Support, decodability, quantization and score at the decode margin."""
    step = block.get("step")
    residuals = block["residuals"]
    n = len(residuals)
    decode_tolerance = (
        max(tolerance, config.decode_margin_fraction * float(step))
        if step
        else tolerance
    )
    support = sum(1 for r in residuals if abs(r) <= decode_tolerance) / n if n else 0.0
    # Quantization (the triage signal) also needs most residuals inside
    # half the decode tolerance. At small steps that is the measurement
    # rounding band, which stops a few-level integer sequence (or a
    # "clean" scene whose values bunch between grid lines) from passing
    # as a grid; at large steps it still admits receiver-tolerable
    # jitter. Angle keeps the rms gate only: tilt measurement carries a
    # regression bias.
    strict = (
        sum(1 for r in residuals if abs(r) <= decode_tolerance / 2.0) / n if n else 0.0
    )
    strict_ok = name_is_angle or strict >= config.min_support_fraction
    block["decode_tolerance"] = round(decode_tolerance, 4)
    block["decode_support_fraction"] = round(support, 6)
    block["strict_support_fraction"] = round(strict, 6)
    block["decodable"] = bool(
        step and support >= config.min_support_fraction and block["levels_used"] >= 2
    )
    block["quantized"] = bool(
        block["decodable"]
        and strict_ok
        and block["null_exceedance"] <= config.null_alpha
        and block["rayleigh_R"] >= config.min_rayleigh_R
        and block["rms_residual"] <= decode_tolerance
    )
    fit = max(0.0, 1.0 - block["rms_residual"] / decode_tolerance)
    significance = max(0.0, 1.0 - block["null_exceedance"] / config.null_alpha)
    # Phase concentration is part of the evidence: a fit with
    # mediocre R is weaker than the residuals alone suggest.
    block["score"] = round(support * fit * significance * block["rayleigh_R"], 6)


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
    }
    tolerances = {
        "height": config.residual_tolerance,
        "gap": config.residual_tolerance,
        "lit": config.brightness_tolerance,
        "angle": config.angle_residual_tolerance,
    }
    channels: dict[str, Any] = {}
    for name in _GRID_CHANNELS:
        declared = (declared_grid or {}).get(name)
        block = discover_grid(
            raw_values[name],
            tolerance=tolerances[name],
            seed=1723 + 101 * _GRID_CHANNELS.index(name),
            declared_grid=declared,
        )
        _apply_decode_margin(
            block, tolerances[name], config, name_is_angle=name == "angle"
        )
        declared_fit = block.get("declared") or {}
        if declared_fit.get("support_fraction", 0.0) >= config.min_support_fraction:
            # A declared prior grid that fits is quantization evidence
            # in its own right (CL-43).
            block["quantized"] = True
            block["decodable"] = True
        channels[name] = block
    colour = _colour_channel(seg, config)
    if declared_grid and declared_grid.get("colour"):
        colour["declared"] = declared_grid["colour"]
    channels["colour"] = colour
    for name, block in channels.items():
        block["elements"] = len(block["symbols"])
        # A constant channel carries no sequence information: one
        # repeated value is trivially "on grid" (upright bars have
        # angle 0; fixed-height scenes quantize heights). Only
        # channels that actually vary may support a claim.
        if name == "colour":
            block["applicable"] = block["levels_used"] >= 2
        else:
            distinct = {
                round(v / max(config.residual_tolerance, 1e-9))
                for v in raw_values[name]
            }
            block["applicable"] = len(distinct) >= 2
        if not block["applicable"] or block["elements"] < config.min_support_elements:
            block["decodable"] = False
            block["quantized"] = False
        if not block["applicable"]:
            block["score"] = 0.0
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


def _relabel_frames(symbols: list[int]) -> list[tuple[str, list[int]]]:
    """Every relabelling of a small discovered palette (CL-78).

    Colour levels have no natural order, so for up to four levels
    each permutation is a frame; the shuffle null takes the same
    maximum, so trying them all costs nothing in honesty.
    """
    labels = sorted(set(symbols))
    if not 2 <= len(labels) <= 4:
        return _symbol_frames(symbols)
    frames = []
    for perm in itertools.permutations(range(len(labels))):
        mapping = dict(zip(labels, perm))
        frames.append(
            ("relabel_" + "".join(str(p) for p in perm), [mapping[s] for s in symbols])
        )
    return frames


def _text_value(text: str) -> float:
    """Trigram score of a mapped text, or -inf when it cannot be a message.

    Fewer than three characters, or under 90% printable, scores -inf in
    the observed sequence and in every shuffle alike (CL-78), so invalid
    mappings can neither make a claim nor inflate the null.
    """
    if len(text) < 3:
        return float("-inf")
    printable = sum(1 for ch in text if 32 <= ord(ch) < 127) / len(text)
    if printable < 0.9:
        return float("-inf")
    return trigram_score(text)


def _evaluate_group(
    kind: str,
    codes: list[dict[str, Any]],
    symbols: list[int],
    config: GeometricConfig,
    seed: int,
    *,
    claim_alpha: float,
    stop_alpha: float,
    frames: Any = _symbol_frames,
) -> dict[str, Any]:
    """One max-statistic test over a channel's codes of one kind (CL-78).

    Text codes share the trigram statistic; timing and rank codes share
    the periodicity statistic. The statistic is the maximum over the
    group's codes and symbol frames, and each shuffle takes the same
    maximum, so testing several related codes (A=0 and A=1 are one text
    shifted by a letter) costs one test, not several.

    Replicates stop early once the hit count rules out `stop_alpha`
    (sequential Monte Carlo): more replicates could not change either
    decision.
    """
    claim = claim_alpha
    stop = max(stop_alpha, claim)
    replicates = max(config.structure_replicates, math.ceil(3.0 / claim) - 1)
    max_hits = math.floor(stop * (replicates + 1)) - 1
    rng = random.Random(seed)
    text_kind = kind == "text"

    def _value(code: dict[str, Any], frame_symbols: list[int]) -> float:
        mapped = code["map"](frame_symbols)
        if text_kind:
            return _text_value(str(mapped))
        return _periodicity_stat([float(v) for v in mapped])

    def _stat(sequence: list[int]) -> float:
        return max(_value(code, fs) for code in codes for _name, fs in frames(sequence))

    rows = [
        (_value(code, fs), code, name, fs)
        for code in codes
        for name, fs in frames(symbols)
    ]
    observed, best_code, frame_name, frame_symbols = max(rows, key=lambda r: r[0])
    base: dict[str, Any] = {
        "kind": kind,
        "codes": [c["code"] for c in codes],
        "code": best_code["code"],
        "symbol_frame": frame_name,
        "level": round(claim, 8),
    }
    if observed == float("-inf"):
        return {
            **base,
            "claimed": False,
            "passes_undeclared_level": False,
            "null_exceedance": 1.0,
            "null_replicates_run": 0,
            "reason": "no code maps to a printable text long enough for a claim",
            "_candidate_text": None,
        }
    hits = 0
    stats: list[float] = []
    for _ in range(replicates):
        shuffled = list(symbols)
        rng.shuffle(shuffled)
        value = _stat(shuffled)
        stats.append(value)
        if value >= observed:
            hits += 1
            if hits > max_hits:
                break
    run = len(stats)
    exceedance = (hits + 1) / (run + 1)
    if text_kind:
        finite = [v for v in stats if v != float("-inf")]
        llr = observed - (sum(finite) / len(finite) if finite else observed)
        valid = llr > 0
        text = str(best_code["map"](frame_symbols))
        extra = {
            "trigram_score": round(observed, 6),
            "log_likelihood_ratio": round(llr, 6),
            "printable_fraction": round(
                sum(1 for ch in text if 32 <= ord(ch) < 127) / len(text), 6
            ),
        }
        what = "trigram likelihood"
    else:
        valid = observed >= 0.8
        text = None
        extra = {"periodicity_stat": observed}
        what = "periodic/autocorrelated structure"
    claimed = bool(valid and exceedance <= claim)
    return {
        **base,
        **extra,
        "claimed": claimed,
        "passes_undeclared_level": bool(valid and exceedance <= stop),
        "null_exceedance": round(exceedance, 6),
        "null_replicates_run": run,
        "reason": (
            f"{what} beats the symbol-shuffle null at the stated level"
            if claimed
            else f"{what} does not beat the symbol-shuffle null at the stated level"
        ),
        "_candidate_text": text if claimed or valid else None,
    }


def _evaluate_code(
    code: dict[str, Any],
    symbols: list[int],
    config: GeometricConfig,
    seed: int,
    *,
    claim_alpha: float | None = None,
    stop_alpha: float | None = None,
    frames: Any = _symbol_frames,
) -> dict[str, Any]:
    """Score one declared code on its own (a one-code group)."""
    claim = claim_alpha if claim_alpha is not None else config.structure_alpha
    kind = "text" if code["kind"] == "text" else "periodic"
    return _evaluate_group(
        kind,
        [code],
        symbols,
        config,
        seed,
        claim_alpha=claim,
        stop_alpha=stop_alpha if stop_alpha is not None else claim,
        frames=frames,
    )


def code_groups(channel: str) -> list[tuple[str, list[dict[str, Any]]]]:
    """A channel's declared codes grouped by test statistic (CL-78)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for code in CODES_V2.get(channel) or []:
        kind = "text" if code["kind"] == "text" else "periodic"
        groups.setdefault(kind, []).append(code)
    return list(groups.items())


def _structure_symbols(channel: str, block: dict[str, Any]) -> list[int]:
    symbols = [int(s) for s in block["symbols"]]
    if channel == "lit":
        # Discovered lit symbols are grid indices (e.g. 0 and 2 for a
        # 95-unit discovered step); the bit code consumes level ranks.
        symbols = _ranks(symbols)
    return symbols


def _structure_eligible(
    channel: str, block: dict[str, Any], config: GeometricConfig
) -> bool:
    return bool(
        block.get("applicable")
        and block.get("decodable")
        and block["elements"] >= config.min_support_elements
        and len(block["symbols"]) >= config.structure_min_symbols
        and CODES_V2.get(channel)
    )


def _structure(
    channel: str,
    block: dict[str, Any],
    config: GeometricConfig,
    *,
    alpha: float | None = None,
    declared: bool = False,
) -> dict[str, Any]:
    """Structure test v2: declared codes + shuffle-null claims (CL-46).

    `alpha` is this channel's per-test level (the caller splits the
    family-wise level over every test in the image, CL-78; a test is
    one statistic kind, maximised over the channel's codes). A declared
    channel must reach `alpha * declared_prior_factor`; whether it
    would have passed at `alpha` is reported as
    `passes_undeclared_level`.

    The returned block never contains mapped text. A claimed
    candidate is attached as `_candidate_text` for the caller to
    route to the reviewer evidence path; it is stripped before the
    finding is built.
    """
    codes = CODES_V2.get(channel) or []
    level = alpha if alpha is not None else config.structure_alpha
    claim_level = level * (config.declared_prior_factor if declared else 1.0)
    base: dict[str, Any] = {
        "channel": channel,
        "claimed": False,
        "code": None,
        "reason": "",
        "level": round(claim_level, 8),
        "undeclared_level": round(level, 8),
        "declared_channel": declared,
        "passes_undeclared_level": False,
        "codes_evaluated": [],
        "_candidate_text": None,
    }
    if not block.get("decodable"):
        base["reason"] = "sequence is not decodable at the required support"
        return base
    if block["elements"] < config.min_support_elements:
        base["reason"] = "too few supporting elements for a structure claim"
        return base
    symbols = _structure_symbols(channel, block)
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
    frames = _relabel_frames if channel == "colour" else _symbol_frames
    evaluated = [
        _evaluate_group(
            kind,
            group,
            symbols,
            config,
            seed=4242 + 17 * i,
            claim_alpha=claim_level,
            stop_alpha=level,
            frames=frames,
        )
        for i, (kind, group) in enumerate(code_groups(channel))
    ]
    public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in evaluated]
    base["codes_evaluated"] = public
    base["passes_undeclared_level"] = any(
        r["passes_undeclared_level"] for r in evaluated
    )
    claimed = [r for r in evaluated if r["claimed"]]
    best = min(claimed or evaluated, key=lambda r: r.get("null_exceedance") or 1.0)
    base.update(
        {
            "code": best["code"],
            "null_exceedance": best.get("null_exceedance"),
            "trigram_score": best.get("trigram_score"),
            "log_likelihood_ratio": best.get("log_likelihood_ratio"),
            "periodicity_stat": best.get("periodicity_stat"),
            "printable_fraction": best.get("printable_fraction"),
        }
    )
    if claimed:
        base["claimed"] = True
        base["reason"] = best["reason"]
        base["_candidate_text"] = best.get("_candidate_text")
    elif base["passes_undeclared_level"]:
        base["reason"] = (
            "structure beats the shuffle null at the undeclared level but not "
            "at the stricter level for a declared channel"
        )
    else:
        base["reason"] = "no declared code beats the shuffle null at the stated level"
    return base


def _symbols_digest(symbols: list[int]) -> str:
    joined = ",".join(str(int(s)) for s in symbols)
    return "sha256:" + hashlib.sha256(joined.encode("ascii")).hexdigest()


def _public_channel(block: dict[str, Any]) -> dict[str, Any]:
    """Channel block without its symbol sequence (CL-78).

    The symbols plus the code name would let anyone reading a finding
    recover the candidate text, so findings and API output carry a
    digest, a count and the symbol range instead.
    """
    out = {k: v for k, v in block.items() if k != "symbols"}
    symbols = [int(s) for s in block.get("symbols") or []]
    out["symbols_digest"] = _symbols_digest(symbols)
    out["symbol_count"] = len(symbols)
    out["symbol_range"] = [min(symbols), max(symbols)] if symbols else None
    declared = out.get("declared")
    if isinstance(declared, dict) and "symbols" in declared:
        out["declared"] = {k: v for k, v in declared.items() if k != "symbols"}
    return out


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
    # Scene context (CL-45, GEO-05): a channel declared for this task
    # before the run is a legitimate data carrier. Its quantization
    # logs; its structure is still tested, at a stricter level
    # (CL-78: declaration lowers the prior, it is not an exemption).
    declared_channels = set((declared_context or {}).get("declared_channels") or ())

    # Structure on every decodable channel (CL-78), family-wise level
    # split over every code tested in this image.
    eligible = [
        name for name in channels if _structure_eligible(name, channels[name], active)
    ]
    tests = sum(len(code_groups(name)) for name in eligible)
    per_test_alpha = active.structure_alpha / max(1, tests)
    structures: dict[str, dict[str, Any]] = {
        name: _structure(
            name,
            channels[name],
            active,
            alpha=per_test_alpha,
            declared=name in declared_channels,
        )
        for name in eligible
    }

    def _best(names: list[str]) -> str:
        return min(
            names,
            key=lambda n: (
                structures[n].get("null_exceedance") or 1.0,
                -channels[n]["score"],
            ),
        )

    claimed = [n for n, block in structures.items() if block["claimed"]]
    declared_evidence = [
        n
        for n, block in structures.items()
        if n in declared_channels and block["passes_undeclared_level"]
    ]
    quantized = [n for n in channels if channels[n].get("quantized")]
    declared_quantized_channels = sorted(n for n in quantized if n in declared_channels)
    if claimed:
        primary_name = _best(claimed)
        classification = SIGNAL_STRUCTURE
        signal_grade = "enforceable_grade"
    elif declared_evidence:
        # Structure that would be claimed on an undeclared channel:
        # not enough to withhold a declared carrier, too much to log.
        primary_name = _best(declared_evidence)
        classification = SIGNAL_DECLARED
        signal_grade = "triage_declared_structure"
    elif quantized:
        primary_name = max(quantized, key=lambda n: channels[n]["score"])
        if declared_quantized_channels:
            # A declared channel that is itself quantized marks the
            # scene's quantization as legitimate even when an artefact
            # channel (e.g. baseline brightness) out-scores it.
            # Structure on any undeclared channel is still claimed above.
            classification = SIGNAL_DECLARED
            signal_grade = "log_declared_channel"
        else:
            classification = SIGNAL_QUANTIZED
            signal_grade = "triage"
    else:
        primary_name = max(channels, key=lambda n: channels[n]["score"])
        if channels[primary_name]["score"] >= active.weak_floor:
            classification = SIGNAL_WEAK
            signal_grade = "triage"
        else:
            classification = SIGNAL_NONE
            signal_grade = "none"
    primary = channels[primary_name]
    channel_declared = primary_name in declared_channels

    if primary_name in structures:
        structure = dict(structures[primary_name])
    elif channels[primary_name].get("applicable"):
        # Not eligible: returns at once with the specific reason (not
        # decodable, or too few symbols for the shuffle null).
        structure = _structure(
            primary_name,
            channels[primary_name],
            active,
            alpha=per_test_alpha,
            declared=channel_declared,
        )
    else:
        structure = {
            "channel": primary_name,
            "claimed": False,
            "code": None,
            "reason": "primary channel does not vary; nothing to test",
        }
    # The candidate decode never enters the finding (CL-46): it is
    # returned transiently so the caller can write it to the
    # reviewer evidence path (EvidenceGateway, R-08).
    candidate_text = structure.pop("_candidate_text", None)
    structure_by_channel = {
        name: {
            k: block.get(k)
            for k in (
                "claimed",
                "code",
                "null_exceedance",
                "level",
                "undeclared_level",
                "declared_channel",
                "passes_undeclared_level",
            )
        }
        for name, block in structures.items()
    }
    candidate_decode = None
    if structure.get("claimed") and candidate_text:
        candidate_decode = {
            "code": structure.get("code"),
            "channel": primary_name,
            "text": candidate_text,
            "via": "evidence_gateway_reviewer_path",
        }
    likeness = chart_likeness(seg)
    height_prior = None
    if primary_name == "height" and likeness["score"] >= 0.7:
        # Chart-likeness is a prior on the height channel only:
        # it annotates triage, it never decides a classification.
        height_prior = (
            "chart-like scene: height quantization is expected for "
            "data visualizations; treat as triage unless structure "
            "is claimed under a declared code"
        )
    if classification == SIGNAL_STRUCTURE:
        # Reserve the upper band for structure (CL-78 score bands).
        score = STRUCTURE_SCORE_FLOOR + 0.2 * float(primary["score"])
    elif classification == SIGNAL_NONE or signal_grade == "log_declared_channel":
        score = 0.0
    else:
        score = NON_STRUCTURE_SCORE_CEILING * float(primary["score"])
    public_channels = {name: _public_channel(block) for name, block in channels.items()}
    finding = Finding(
        family=GEO_FAMILY,
        detector_name=GEO_DETECTOR_NAME,
        detector_version=GEO_DETECTOR_VERSION,
        score=round(score, 6),
        coverage={
            "applicable": True,
            "elements": len(seg.elements),
            "channels_tested": sorted(channels),
            "structure_channels_tested": sorted(structures),
            "structure_tests": tests,
            "segmenter": f"{seg.config.name} {seg.config.version}",
            "media_kind": seg.media_kind,
            "config_version": active.version,
            "config_status": active.status,
        },
        evidence={
            "label": "evidence_aid_not_decoded_message",
            "primary_channel": primary_name,
            "channels": public_channels,
            "structure": structure,
            "structure_by_channel": structure_by_channel,
            "classification": classification,
            "signal_grade": signal_grade,
            "chart_likeness": likeness,
            "declared_context": {
                "declared_channels": sorted(declared_channels),
                "context": (declared_context or {}).get("context"),
                "primary_channel_declared": channel_declared,
                "declared_quantized_channels": declared_quantized_channels,
                "declared_prior_factor": active.declared_prior_factor,
            }
            if declared_context
            else None,
            "height_prior": height_prior,
        },
        limitations=_LIMITATIONS
        + ((_JPEG_LIMITATION,) if seg.media_kind == "jpeg" else ()),
    )
    return {
        "status": "ok",
        "finding": finding,
        "classification": classification,
        "signal_grade": signal_grade,
        "primary_channel": primary_name,
        "channels": public_channels,
        "structure": structure,
        "structure_by_channel": structure_by_channel,
        "chart_likeness": likeness,
        "declared_context": declared_context,
        "candidate_decode": candidate_decode,
    }


def detect_geometric(
    data: bytes, result: AnalysisResult, declared_context: dict[str, Any] | None = None
) -> Finding | None:
    """DET-02 finding for one parsed raster; None when not applicable.

    Attached by `analyze_all_bytes` as the fourth channel family
    (CL-44). PNG is segmented losslessly; baseline JPEG is
    segmented from a lossy reconstruction with a recorded fidelity
    limitation (CL-52). Failed parses get no geometric finding:
    failures are never converted into clean scores (C-02).
    """
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind not in ("png", "jpeg"):
        return None
    return analyze_geometric_bytes(
        data, declared_context=declared_context, parsed=result
    ).get("finding")


def analyze_geometric_bytes(
    data: bytes,
    config: GeometricConfig | None = None,
    declared_grid: dict[str, dict[str, Any]] | None = None,
    declared_context: dict[str, Any] | None = None,
    *,
    parsed: AnalysisResult | None = None,
) -> dict[str, Any]:
    """Segment original bytes and run both geometric tests."""
    seg = segment_image(data, parsed=parsed)
    report = analyze_geometric(seg, config, declared_grid, declared_context)
    report["segmentation"] = seg.to_dict()
    return report


def validate_geometric_report(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a geometric report; empty is valid."""
    errors: list[str] = []

    need = make_need(errors)

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
            "symbols_digest",
            "residuals",
            "supporting",
            "support_fraction",
            "score",
        ):
            need(key in block, f"channels.{name}.{key} is required (no bare verdicts)")
        need(
            "symbols" not in block and "symbols" not in (block.get("declared") or {}),
            f"channels.{name}.symbols must not appear in a finding: with the "
            "code name they recover the candidate text (CL-78)",
        )
    structure = evidence.get("structure") or {}
    blocks = [structure, *(evidence.get("structure_by_channel") or {}).values()]
    for banned in (
        "mapped_preview",
        "candidate_text",
        "_candidate_text",
        "mapped_text",
    ):
        need(
            all(banned not in block for block in blocks),
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
    if report.get("classification") == SIGNAL_STRUCTURE:
        need(
            finding.score >= STRUCTURE_SCORE_FLOOR,
            "structure_claimed must score in the structure band (CL-78)",
        )
    else:
        need(
            finding.score <= NON_STRUCTURE_SCORE_CEILING,
            "a finding without a structure claim must stay at or below the "
            "non-structure ceiling (CL-78)",
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
