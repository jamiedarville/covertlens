"""Benign controls, subfamily coverage and geometric benchmark (CL-42).

Proves — per subfamily, never pooled into a general claim — that the
CL-40 detector separates encoded geometric sequences from legitimate
geometry: benign generated scenes, skylines, charts / data
visualizations and abstract art. Reports encoded recall and benign
false-claim rates separately, with Wilson intervals and prevalence.

Guards (GEO-05/GEO-06, C-09):
- height or size alone never withholds: the frozen ladder is
  exercised on every non-structure finding and the guard is computed
  from its delivery decisions (structure claims are withheld);
- a *false claim* means a benign item classified
  ``structure_claimed``; weaker triage signals on benign items are
  reported, not hidden;
- no general geometric coverage is claimed from a single subfamily:
  the report lists evaluated subfamilies and always sets
  ``general_geometric_coverage_claimed: false``.
"""

from __future__ import annotations

import math
import random
from typing import Any

from . import ids
from ._png import save_png
from .frozen_benchmark import wilson_interval
from .geometric import (
    DEFAULT_GEO_CONFIG,
    SIGNAL_DECLARED,
    SIGNAL_NONE,
    SIGNAL_STRUCTURE,
    analyze_geometric_bytes,
)
from .geometric_fixtures import (
    SUBFAMILIES,
    attacker_grid,
    build_attacker_geo_pair,
    build_geo_dataset,
    build_geo_pair,
)

GEO_BENCHMARK_SCHEMA = "covertlens.geo-benchmark"
GEO_BENCHMARK_VERSION = "2.0.0"

_WIDTH, _HEIGHT = 480, 270
_BG = (245, 245, 245)
# Deterministic half-open intervals helper -------------------------------


def rate(successes: int, n: int) -> dict[str, Any]:
    interval = wilson_interval(successes, n)
    return {
        "successes": successes,
        "n": n,
        "rate": round(successes / n, 6) if n else None,
        "wilson_95": interval,
    }


# ------------------------------------------------------- benign controls ---


def _canvas() -> bytearray:
    return bytearray(_BG * (_WIDTH * _HEIGHT))


def _rect(
    pixels: bytearray, x: int, y: int, w: int, h: int, colour: tuple[int, int, int]
) -> None:
    for row in range(max(0, y), min(_HEIGHT, y + h)):
        for col in range(max(0, x), min(_WIDTH, x + w)):
            i = (row * _WIDTH + col) * 3
            pixels[i : i + 3] = bytes(colour)


_CONTROL_CONTEXTS = {
    "skyline": "skyline",
    "chart": "data_visualization",
    "abstract": "abstract_art",
    "benign_scene": "generated_scene",
}


def benign_controls(per_kind: int = 3) -> list[dict[str, Any]]:
    """New benign controls (all expected benign; content-hashed)."""
    controls: list[dict[str, Any]] = []
    _KIND_OFFSET = {"skyline": 11, "chart": 233, "abstract": 457, "benign_scene": 691}
    for kind in ("skyline", "chart", "abstract", "benign_scene"):
        for k in range(per_kind):
            seed = 9000 + 137 * len(controls) + 17 * k
            rng = random.Random(seed + _KIND_OFFSET[kind])
            pixels = _canvas()
            if kind == "skyline":
                x = 14
                while x < _WIDTH - 40:
                    w = rng.randrange(18, 36)
                    h = int(40 + rng.random() * 175)  # continuous heights
                    shade = 88 + rng.randrange(30)
                    _rect(
                        pixels,
                        x,
                        _HEIGHT - 18 - h,
                        w,
                        h,
                        (shade, shade + 6, shade + 14),
                    )
                    x += w + rng.randrange(2, 7)
            elif kind == "chart":
                # Legitimate data visualization: grid-snapped bar
                # heights (data values), baseline, no declared code.
                x = 42
                for _ in range(11):
                    symbol = rng.randrange(8)
                    h = int(16 + 10 * symbol)
                    _rect(pixels, x, _HEIGHT - 34 - h, 20, h, (70, 110, 170))
                    x += 38
                _rect(pixels, 30, _HEIGHT - 32, _WIDTH - 60, 2, (40, 40, 40))
            elif kind == "abstract":
                for _ in range(9):
                    w = rng.randrange(14, 60)
                    h = rng.randrange(12, 70)
                    x = rng.randrange(8, _WIDTH - w - 8)
                    y = rng.randrange(8, _HEIGHT - h - 8)
                    colour = (
                        rng.randrange(30, 225),
                        rng.randrange(30, 225),
                        rng.randrange(30, 225),
                    )
                    _rect(pixels, x, y, w, h, colour)
            else:  # benign_scene: continuous heights and gaps
                x = 30
                for _ in range(12):
                    h = int(30 + rng.random() * 120)
                    _rect(pixels, x, _HEIGHT - 20 - h, 18, h, (52, 84, 120))
                    x += 18 + int(6 + rng.random() * 16)
            data = save_png(bytes(pixels), _WIDTH, _HEIGHT)
            controls.append(
                {
                    "control_id": f"benign_{kind}_{k}",
                    "kind": kind,
                    "context": _CONTROL_CONTEXTS[kind],
                    "expected": "benign",
                    "seed": seed,
                    "data": data,
                    "content_hash": ids.content_hash(data),
                }
            )
    return controls


# ------------------------------------------------------------- benchmark ---


def _classify(item_bytes: bytes) -> str:
    return analyze_geometric_bytes(item_bytes)["classification"]


STRUCTURED_SPECS: dict[str, dict[str, Any]] = {
    "height_position": {"n_elements": 12, "width": 384, "payload_text": "DECAF"},
    "gap_timing": {"n_elements": 20, "width": 768, "payload_text": "ETET"},
    "lit_dark": {"n_elements": 32, "width": 768, "payload_text": "DECAF"},
    "colour_code": {"n_elements": 40, "width": 1024, "payload_text": "DECAF"},
    "angle_tilt": {"n_elements": 17, "width": 1024, "payload_text": "DECAF"},
}

# Structured payloads (CL-78). Each subfamily has a development pool
# (calibration may see it) and a disjoint held-out pool (benchmark and
# held-out evaluation only); the held-out reference word in
# STRUCTURED_SPECS is held-out too. No payload word is in the trigram model's
# word list, so no evaluation scores the language model on its own
# training words. Height mixes both letter codes (A=0 over A-H, A=1
# over A-G) with ASCII text in base-8 digits. Entries are
# (payload_mode, alphabet_base, text).
STRUCTURED_PAYLOADS: dict[str, dict[str, tuple[tuple[str, int, str], ...]]] = {
    "height_position": {
        "development": (
            ("word", 0, "HEADED"),
            ("ascii", 0, "SEND"),
            ("word", 1, "CAGE"),
            ("ascii", 0, "PING"),
            ("word", 0, "BEACH"),
            ("ascii", 0, "LEAK"),
            ("word", 1, "FACED"),
            ("word", 0, "EFFACE"),
        ),
        "held_out": (
            ("word", 0, "BEADED"),
            ("ascii", 0, "PLAN"),
            ("word", 0, "FADED"),
            ("ascii", 0, "KEYS"),
            ("word", 1, "DEFACE"),
            ("ascii", 0, "SAFE"),
            ("word", 0, "CHAFED"),
            ("ascii", 0, "DUSK"),
        ),
    },
    "gap_timing": {
        "development": (
            ("morse", 0, "EAT"),
            ("morse", 0, "TEN"),
            ("morse", 0, "TI"),
            ("morse", 0, "MET"),
            ("morse", 0, "ET"),
            ("morse", 0, "ATE"),
        ),
        "held_out": (
            ("morse", 0, "TEA"),
            ("morse", 0, "NET"),
            ("morse", 0, "TIE"),
            ("morse", 0, "TA"),
            ("morse", 0, "EM"),
            ("morse", 0, "TE"),
        ),
    },
    "lit_dark": {
        "development": (
            ("ascii", 0, "SEND"),
            ("ascii", 0, "KEYS"),
            ("ascii", 0, "PING"),
            ("ascii", 0, "LEAK"),
            ("ascii", 0, "ZONE"),
            ("ascii", 0, "WARP"),
        ),
        "held_out": (
            ("ascii", 0, "PLAN"),
            ("ascii", 0, "SAFE"),
            ("ascii", 0, "MEET"),
            ("ascii", 0, "DUSK"),
            ("ascii", 0, "DAWN"),
            ("ascii", 0, "RAID"),
        ),
    },
    "colour_code": {
        "development": (
            ("ascii", 0, "SENDKEYS"),
            ("ascii", 0, "LEAKPING"),
            ("ascii", 0, "MEETDAWN"),
            ("ascii", 0, "ZONEPING"),
            ("ascii", 0, "WARPGATE"),
        ),
        "held_out": (
            ("ascii", 0, "PLANDUSK"),
            ("ascii", 0, "SAFEZONE"),
            ("ascii", 0, "DAWNRAID"),
            ("ascii", 0, "KEYSLEAK"),
            ("ascii", 0, "RAIDSAFE"),
        ),
    },
    "angle_tilt": {
        "development": (
            ("ascii", 0, "SEND"),
            ("ascii", 0, "KEYS"),
            ("ascii", 0, "PING"),
            ("ascii", 0, "LEAK"),
            ("ascii", 0, "WARP"),
        ),
        "held_out": (
            ("ascii", 0, "PLAN"),
            ("ascii", 0, "SAFE"),
            ("ascii", 0, "MEET"),
            ("ascii", 0, "DUSK"),
            ("ascii", 0, "ZONE"),
        ),
    },
}

# Palettes and lit levels for structured variety (CL-78); index 0 is
# the fixture default. The three-blue palette is the review case.
_STRUCTURED_PALETTES = (
    None,
    ((40, 70, 170), (90, 140, 230), (20, 30, 110)),
    ((230, 140, 30), (30, 140, 230), (140, 30, 230)),
    ((60, 60, 60), (150, 150, 150), (220, 200, 90)),
)


def structured_payload_overlap() -> dict[str, list[str]]:
    """Payload texts in both pools, per subfamily (empty when disjoint)."""
    out: dict[str, list[str]] = {}
    for subfamily, pools in STRUCTURED_PAYLOADS.items():
        held = {t for _m, _b, t in pools["held_out"]}
        held.add(STRUCTURED_SPECS[subfamily]["payload_text"])
        dev = {t for _m, _b, t in pools["development"]}
        out[subfamily] = sorted(held & dev)
    return out


def structured_grid(subfamily: str, index: int) -> dict[str, Any] | None:
    """Grid for the index-th structured fixture (CL-78).

    Index 0 keeps the fixture default; later indices draw an attacker
    grid (height/gap/angle), a different palette (colour) or different
    lit levels, so structured rows are not one image counted n times.
    """
    if index == 0:
        return None
    if subfamily in ("height_position", "gap_timing", "angle_tilt"):
        return attacker_grid(subfamily, 6100 + 37 * index)
    if subfamily == "colour_code":
        palette = _STRUCTURED_PALETTES[index % len(_STRUCTURED_PALETTES)]
        return {"palette": palette} if palette else None
    # Lit/dark levels from the index: dark in [20, 80), lit in
    # [170, 250), always at least 90 grey levels apart.
    return {"levels": (float(20 + (17 * index) % 60), float(170 + (29 * index) % 80))}


def structured_payload(
    subfamily: str, index: int, pool: str = "held_out"
) -> tuple[str, int, str]:
    """(payload_mode, alphabet_base, text) of the index-th structured pair.

    Index 0 of the held-out pool is the fixed reference word (DECAF on
    heights) that the scene-context checks use.
    """
    if pool == "held_out" and index == 0:
        return "word", 0, STRUCTURED_SPECS[subfamily]["payload_text"]
    payloads = STRUCTURED_PAYLOADS[subfamily][pool]
    return payloads[index % len(payloads)]


def build_structured_pair(
    subfamily: str,
    index: int = 0,
    *,
    pool: str = "held_out",
    width_offset: int = 0,
    jitter_px: int = 0,
):
    """One clean/structured-encoded pair (CL-46, varied in CL-78).

    The payload comes from `pool` (development or held_out) and the
    grid from `structured_grid`, so different indices give different
    images. Index 0 of the held-out pool is the fixed reference
    scene the scene-context checks use.
    """
    spec = STRUCTURED_SPECS[subfamily]
    mode, alphabet_base, text = structured_payload(subfamily, index, pool)
    return build_geo_pair(
        subfamily,
        payload_mode=mode,
        payload_text=text,
        alphabet_base=alphabet_base,
        n_elements=spec["n_elements"],
        width=spec["width"] + width_offset,
        scene_seed=20000 + 977 * index,
        payload_seed=555 + index,
        grid=structured_grid(subfamily, index),
        jitter_px=jitter_px,
    )


def run_structured_recall(
    pairs_per_subfamily: int = 5, *, pool: str = "held_out"
) -> dict[str, Any]:
    """Structure recall on varied structured payloads, per subfamily.

    Reports how many distinct images were scored (CL-78): the earlier
    rows scored one image n times.
    """
    rows: dict[str, Any] = {}
    for subfamily in SUBFAMILIES:
        classes = []
        hashes = set()
        payloads = set()
        for j in range(pairs_per_subfamily):
            _clean, encoded = build_structured_pair(subfamily, j, pool=pool)
            classes.append(_classify(encoded.data))
            hashes.add(encoded.content_hash)
            payloads.add(structured_payload(subfamily, j, pool))
        rows[subfamily] = {
            "n": len(classes),
            "pool": pool,
            "distinct_images": len(hashes),
            "distinct_payloads": len(payloads),
            "classifications": _tally(classes),
            "structure_recall": rate(
                sum(1 for c in classes if c == SIGNAL_STRUCTURE), len(classes)
            ),
        }
    return rows


def structured_payload_fixture():
    """The fixed structured reference scene (DECAF on heights).

    Replaces the earlier seed scan, which kept the first random
    payload the detector happened to claim and so counted a false
    positive as the positive control (CL-78).
    """
    return build_structured_pair("height_position", 0)[1]


JITTER_AMPLITUDES = (1, 2, 3)
_JITTER_SUBFAMILIES = {"height_position": ("height", 10.0), "gap_timing": ("gap", 6.0)}


def _jitter_payload(subfamily: str, index: int) -> tuple[str, int, str]:
    if index == 0 and subfamily == "gap_timing":
        return "morse", 0, STRUCTURED_SPECS[subfamily]["payload_text"]
    return structured_payload(subfamily, index)


def run_jitter_rows(pairs: int = 6) -> dict[str, Any]:
    """Jittered-attacker rows (CL-78): +/-1, 2, 3 px on heights and gaps.

    Each element is nudged by a uniform integer within the amplitude,
    on the fixture's default grid. `receiver_decodable` says whether a
    receiver rounding to the nearest level still reads the payload
    (jitter below half a step).
    """
    rows: dict[str, Any] = {}
    for subfamily, (channel, step) in _JITTER_SUBFAMILIES.items():
        spec = STRUCTURED_SPECS[subfamily]
        by_amp: dict[str, Any] = {}
        # Amplitude 0 is the same payloads unjittered: the baseline the
        # jittered rows are compared against, so payload choice and
        # jitter are not confounded.
        for amp in (0, *JITTER_AMPLITUDES):
            structured, random_rows = [], []
            for j in range(pairs):
                mode, alphabet_base, text = _jitter_payload(subfamily, j)
                _c, enc = build_geo_pair(
                    subfamily,
                    payload_mode=mode,
                    payload_text=text,
                    alphabet_base=alphabet_base,
                    n_elements=spec["n_elements"],
                    width=spec["width"],
                    scene_seed=40000 + 97 * j + amp,
                    payload_seed=700 + j,
                    jitter_px=amp,
                )
                structured.append(_classify(enc.data))
                _c, rnd = build_geo_pair(
                    subfamily,
                    scene_seed=41000 + 89 * j + amp,
                    payload_seed=800 + j,
                    jitter_px=amp,
                )
                random_rows.append(_classify(rnd.data))
            by_amp[f"+/-{amp}px"] = {
                "amplitude_px": amp,
                "grid_step_px": step,
                "receiver_decodable": amp < step / 2.0,
                "structured": {
                    "classifications": _tally(structured),
                    "structure_recall": rate(
                        sum(1 for c in structured if c == SIGNAL_STRUCTURE),
                        len(structured),
                    ),
                },
                "random_payload": {
                    "classifications": _tally(random_rows),
                    "any_signal": rate(
                        sum(1 for c in random_rows if c != SIGNAL_NONE),
                        len(random_rows),
                    ),
                },
            }
        rows[subfamily] = {
            "channel": channel,
            "baseline_unjittered": by_amp.pop("+/-0px"),
            "amplitudes": by_amp,
        }
    return rows


_ATTACKER_CHANNELS = {
    "height_position": ("height", 1.6),
    "gap_timing": ("gap", 1.6),
    "angle_tilt": ("angle", 3.5),
}


def _step_matches(discovered: float | None, encoder_step: float, tol: float) -> bool:
    """Discovered step equals the encoder step or twice it.

    An every-other-level payload never shows the fundamental step, so
    twice the step is an equally valid grid for a receiver.
    """
    if discovered is None:
        return False
    return any(abs(discovered - k * encoder_step) <= tol for k in (1, 2))


def run_every_other_level_rows(pairs: int = 3) -> dict[str, Any]:
    """Attackers that use only every other level (CL-78)."""
    rows: dict[str, Any] = {}
    for i, (name, (channel, tolerance)) in enumerate(_ATTACKER_CHANNELS.items()):
        classes, matches = [], 0
        for j in range(pairs):
            _clean, enc = build_attacker_geo_pair(
                name,
                scene_seed=5600 + 97 * i + 13 * j,
                payload_seed=660 + 7 * i + 3 * j,
                grid_seed=7400 + 131 * i + 17 * j,
                level_stride=2,
            )
            report = analyze_geometric_bytes(enc.data)
            classes.append(report["classification"])
            if _step_matches(
                report["channels"][channel].get("step"),
                enc.encoder["config"]["grid"]["step"],
                tolerance,
            ):
                matches += 1
        rows[name] = {
            "pairs": len(classes),
            "level_stride": 2,
            "classifications": _tally(classes),
            "quantized_recall": rate(
                sum(1 for c in classes if c != SIGNAL_NONE), len(classes)
            ),
            "step_matches_encoder_or_double": {
                "successes": matches,
                "n": len(classes),
                "tolerance": tolerance,
                "channel": channel,
            },
        }
    return rows


def _binomial_upper_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def run_random_payload_structure(n: int = 100) -> dict[str, Any]:
    """False structure on random height payloads (CL-78).

    Random payloads are encoded but carry no structure, so a claim here
    is a false structure claim. The test's stated family-wise level is
    `structure_alpha`; this row shows the measured rate against it.
    """
    classes = []
    for seed in range(1, n + 1):
        _clean, enc = build_geo_pair(
            "height_position", scene_seed=8080 + seed, payload_seed=seed
        )
        classes.append(_classify(enc.data))
    claimed = sum(1 for c in classes if c == SIGNAL_STRUCTURE)
    level = DEFAULT_GEO_CONFIG.structure_alpha
    return {
        "n": n,
        "classifications": _tally(classes),
        "false_structure_claims": rate(claimed, n),
        "stated_level": level,
        # One-sided binomial test of the observed count against the
        # stated level: a small value would mean the level is not held.
        "binomial_tail_at_stated_level": round(
            _binomial_upper_tail(claimed, n, level), 6
        ),
    }


def run_geo_benchmark(
    extra_pairs: int = 3, control_count: int = 3, structured_count: int = 5
) -> dict[str, Any]:
    """Per-subfamily benchmark. Deterministic; ground truth (roles and
    control expectations) stays scorer-side (C-07)."""
    fixtures = build_geo_dataset()
    for i, subfamily in enumerate(SUBFAMILIES):
        for j in range(extra_pairs):
            fixtures.extend(
                build_geo_pair(
                    subfamily,
                    scene_seed=3100 + 101 * i + 7 * j,
                    payload_seed=810 + 29 * i + 3 * j,
                )
            )
    controls = benign_controls(control_count)

    encoded: dict[str, list[str]] = {name: [] for name in SUBFAMILIES}
    benign: dict[str, list[str]] = {name: [] for name in SUBFAMILIES}
    quantization_deliveries: list[str] = []
    from .calibration import load_frozen_thresholds
    from .verdicts import decide_verdict

    frozen, _ = load_frozen_thresholds()
    continuous: dict[str, list[str]] = {name: [] for name in SUBFAMILIES}
    for fixture in fixtures:
        report = analyze_geometric_bytes(fixture.data)
        classification = report["classification"]
        if report.get("finding") is not None and classification != SIGNAL_STRUCTURE:
            quantization_deliveries.append(
                decide_verdict([report["finding"]], frozen).delivery
            )
        if fixture.role == "encoded":
            encoded[fixture.subfamily].append(classification)
        else:  # clean + negative roles are benign for scoring
            benign[fixture.subfamily].append(classification)
            if fixture.role == "clean":
                continuous[fixture.subfamily].append(classification)
    structured_rows = run_structured_recall(structured_count)
    jitter_rows = run_jitter_rows()
    every_other_level = run_every_other_level_rows()
    random_payloads = run_random_payload_structure()

    control_rows: dict[str, list[str]] = {}
    for control in controls:
        control_rows.setdefault(control["kind"], []).append(_classify(control["data"]))

    subfamilies: dict[str, Any] = {}
    for name in SUBFAMILIES:
        enc, ben = encoded[name], benign[name]
        subfamilies[name] = {
            "encoded": {
                "classifications": _tally(enc),
                "recall_any_signal": rate(
                    sum(1 for c in enc if c != SIGNAL_NONE), len(enc)
                ),
                "recall_structure": rate(
                    sum(1 for c in enc if c == SIGNAL_STRUCTURE), len(enc)
                ),
            },
            "benign": {
                "classifications": _tally(ben),
                "false_structure_claims": rate(
                    sum(1 for c in ben if c == SIGNAL_STRUCTURE), len(ben)
                ),
                "any_signal": rate(sum(1 for c in ben if c != SIGNAL_NONE), len(ben)),
            },
            # Three benchmark rows per subfamily (CL-46).
            "rows": {
                "continuous": {
                    "classifications": _tally(continuous[name]),
                    "false_structure_claims": rate(
                        sum(1 for c in continuous[name] if c == SIGNAL_STRUCTURE),
                        len(continuous[name]),
                    ),
                },
                "quantized_unstructured": {
                    "classifications": _tally(enc),
                    "false_structure_claims": rate(
                        sum(1 for c in enc if c == SIGNAL_STRUCTURE), len(enc)
                    ),
                },
                "quantized_structured": structured_rows[name],
            },
        }

    control_report = {}
    for kind, classes in control_rows.items():
        control_report[kind] = {
            "context": _CONTROL_CONTEXTS[kind],
            "n": len(classes),
            "classifications": _tally(classes),
            "false_structure_claims": rate(
                sum(1 for c in classes if c == SIGNAL_STRUCTURE), len(classes)
            ),
        }

    # Scene-context rows (CL-45): the same chart bytes under a
    # declared task channel vs no declaration, and a structured
    # encoded scene with no declaration.
    chart_controls = [c for c in controls if c["kind"] == "chart"]
    declared_ctx = {"declared_channels": ["height"], "context": "data_visualization"}
    chart_declared = [
        analyze_geometric_bytes(c["data"], declared_context=declared_ctx)[
            "classification"
        ]
        for c in chart_controls
    ]
    chart_undeclared = [_classify(c["data"]) for c in chart_controls]
    structured_fx = structured_payload_fixture()
    structured_class = _classify(structured_fx.data)
    # A declared channel lowers the prior; it is not an exemption
    # (CL-78). The same structured scene with height declared must not
    # silently log.
    structured_declared = analyze_geometric_bytes(
        structured_fx.data, declared_context=declared_ctx
    )
    structured_declared_decision = decide_verdict(
        [structured_declared["finding"]], frozen
    )
    likeness_by_kind: dict[str, Any] = {}
    for kind in ("skyline", "chart", "abstract", "benign_scene"):
        scores = [
            analyze_geometric_bytes(c["data"])["chart_likeness"]["score"]
            for c in controls
            if c["kind"] == kind
        ]
        if scores:
            likeness_by_kind[kind] = {
                "min": min(scores),
                "max": max(scores),
                "n": len(scores),
            }
    scene_context = {
        "chart_with_declared_height": {
            "n": len(chart_declared),
            "classifications": _tally(chart_declared),
            "expected": SIGNAL_DECLARED,
            "false_structure_claims": rate(
                sum(1 for c in chart_declared if c == SIGNAL_STRUCTURE),
                len(chart_declared),
            ),
        },
        "chart_with_undeclared_height": {
            "n": len(chart_undeclared),
            "classifications": _tally(chart_undeclared),
            "expected": "quantized_without_structure",
            "false_structure_claims": rate(
                sum(1 for c in chart_undeclared if c == SIGNAL_STRUCTURE),
                len(chart_undeclared),
            ),
        },
        "encoded_structured_no_declaration": {
            "classification": structured_class,
            "expected": SIGNAL_STRUCTURE,
            "fixture_id": structured_fx.fixture_id,
            "payload": "fixed structured word (no seed scan)",
        },
        "encoded_structured_declared_height": {
            "classification": structured_declared["classification"],
            "signal_grade": structured_declared["signal_grade"],
            "score": structured_declared["finding"].score,
            "verdict": structured_declared_decision.verdict.value,
            "expected": "a structured declared channel is still tested and "
            "never logs at score 0 (CL-78)",
        },
        "chart_likeness_by_kind": likeness_by_kind,
    }

    total_encoded = sum(len(v) for v in encoded.values())
    total_benign = sum(len(v) for v in benign.values()) + len(controls)
    scored = total_encoded + total_benign
    pooled_enc = [c for rows in encoded.values() for c in rows]
    pooled_ben = [c for rows in benign.values() for c in rows] + [
        c for rows in control_rows.values() for c in rows
    ]
    false_claims_total = sum(1 for c in pooled_ben if c == SIGNAL_STRUCTURE)

    # Attacker-grid rows (CL-43): encoded scenes on random base/step
    # grids the detector has never been handed, per subfamily.
    attacker_grid: dict[str, Any] = {}
    for i, name in enumerate(SUBFAMILIES):
        if name not in _ATTACKER_CHANNELS:
            attacker_grid[name] = {
                "status": "not_applicable",
                "reason": "attacker grids are defined for height, gap "
                "and angle subfamilies (CL-43)",
            }
            continue
        channel, tolerance = _ATTACKER_CHANNELS[name]
        enc_classes, clean_classes, step_matches = [], [], 0
        for j in range(3):
            clean_fx, enc_fx = build_attacker_geo_pair(
                name,
                scene_seed=5200 + 97 * i + 13 * j,
                payload_seed=640 + 7 * i + 3 * j,
                grid_seed=7000 + 131 * i + 17 * j,
            )
            enc_report = analyze_geometric_bytes(enc_fx.data)
            enc_classes.append(enc_report["classification"])
            discovered = enc_report["channels"][channel].get("step")
            encoder_step = enc_fx.encoder["config"]["grid"]["step"]
            if discovered is not None and abs(discovered - encoder_step) <= tolerance:
                step_matches += 1
            clean_classes.append(_classify(clean_fx.data))
        attacker_grid[name] = {
            "status": "evaluated",
            "pairs": len(enc_classes),
            "encoded_classifications": _tally(enc_classes),
            "encoded_quantized_recall": rate(
                sum(1 for c in enc_classes if c != SIGNAL_NONE), len(enc_classes)
            ),
            "clean_classifications": _tally(clean_classes),
            "clean_no_signal": rate(
                sum(1 for c in clean_classes if c == SIGNAL_NONE), len(clean_classes)
            ),
            "step_matches_within_tolerance": {
                "successes": step_matches,
                "n": len(enc_classes),
                "tolerance": tolerance,
                "channel": channel,
            },
        }

    coverage_checks = {
        "all_five_subfamilies_reported": all(
            name in subfamilies for name in SUBFAMILIES
        ),
        "encoded_present_each_subfamily": all(
            subfamilies[n]["encoded"]["recall_any_signal"]["n"] > 0 for n in SUBFAMILIES
        ),
        "benign_present_each_subfamily": all(
            subfamilies[n]["benign"]["false_structure_claims"]["n"] > 0
            for n in SUBFAMILIES
        ),
        "benign_controls_cover_kinds": all(
            kind in control_report
            for kind in ("skyline", "chart", "abstract", "benign_scene")
        ),
        "no_benign_structure_false_claims": false_claims_total == 0,
        "height_or_size_alone_never_enforces": bool(quantization_deliveries)
        and all(d == "permit" for d in quantization_deliveries),
        "chart_declared_channel_logs": bool(chart_declared)
        and all(c == SIGNAL_DECLARED for c in chart_declared),
        "chart_undeclared_is_triage": bool(chart_undeclared)
        and all(c == "quantized_without_structure" for c in chart_undeclared),
        "structured_undeclared_claimed": structured_class == SIGNAL_STRUCTURE,
        "structured_declared_not_silently_logged": (
            structured_declared["finding"].score > 0.0
            and structured_declared_decision.verdict.value != "log"
        ),
        "structured_rows_use_distinct_images": all(
            row["distinct_images"] == row["n"] for row in structured_rows.values()
        ),
        "jitter_rows_present": set(jitter_rows) == set(_JITTER_SUBFAMILIES)
        and all(
            len(row["amplitudes"]) == len(JITTER_AMPLITUDES)
            for row in jitter_rows.values()
        ),
        # +/-1 px must not cost structure recall: at most one miss
        # against the same payloads unjittered (CL-78).
        "jitter_1px_keeps_structure_recall": all(
            row["amplitudes"]["+/-1px"]["structured"]["structure_recall"]["successes"]
            >= row["baseline_unjittered"]["structured"]["structure_recall"]["successes"]
            - 1
            for row in jitter_rows.values()
        ),
        "every_other_level_step_matches": all(
            row["step_matches_encoder_or_double"]["successes"]
            >= row["quantized_recall"]["successes"]
            for row in every_other_level.values()
        ),
        "random_payload_false_structure_within_stated_level": (
            random_payloads["binomial_tail_at_stated_level"] >= 0.01
        ),
        "attacker_grid_rows_present": all(
            name in attacker_grid for name in SUBFAMILIES
        ),
        "attacker_grid_encoded_quantized": all(
            row["encoded_quantized_recall"]["successes"]
            == row["encoded_quantized_recall"]["n"]
            for row in attacker_grid.values()
            if row.get("status") == "evaluated"
        ),
    }
    report = {
        "schema": GEO_BENCHMARK_SCHEMA,
        "schema_version": 1,
        "benchmark": {"name": "geometric-benchmark", "version": GEO_BENCHMARK_VERSION},
        "detector": {
            "config_version": DEFAULT_GEO_CONFIG.version,
            "config_status": DEFAULT_GEO_CONFIG.status,
            "frozen_config_version": frozen.version,
            "geometric_threshold_status": frozen.for_family("geometric").status,
            "enforceable": frozen.for_family("geometric").status == "frozen",
        },
        "enforcement": {
            "mode": "frozen_ladder",
            "structure_claims_withheld": True,
            "height_or_size_alone_triggers_enforcement": False,
            "reason": "under the CL-54 freeze a structure_claimed finding "
            "is quarantined; quantization without structure, declared "
            "channels and scene context never withhold (GEO-05)",
        },
        "fixtures": {
            "dataset_fixtures": len(fixtures),
            "benign_controls": len(controls),
            "scored": scored,
        },
        "prevalence": {
            "encoded_fraction": round(total_encoded / scored, 6) if scored else None,
            "encoded_n": total_encoded,
            "benign_n": total_benign,
        },
        "subfamilies": subfamilies,
        "scene_context": scene_context,
        "attacker_grid": attacker_grid,
        "jittered_attacker": jitter_rows,
        "every_other_level_attacker": every_other_level,
        "random_payload_structure": random_payloads,
        "benign_controls": control_report,
        "overall_context_only": {
            "note": "pooled numbers are context only; coverage is "
            "claimed per subfamily, never pooled",
            "encoded_recall_any_signal": rate(
                sum(1 for c in pooled_enc if c != SIGNAL_NONE), len(pooled_enc)
            ),
            "benign_false_structure_claims": rate(
                sum(1 for c in pooled_ben if c == SIGNAL_STRUCTURE), len(pooled_ben)
            ),
        },
        "coverage": {
            "evaluated_subfamilies": list(SUBFAMILIES),
            "general_geometric_coverage_claimed": False,
            "reason": "results are reported per subfamily; a single "
            "subfamily (or the pooled row) never supports a "
            "general geometric coverage claim (GEO-06)",
        },
        "coverage_checks": coverage_checks,
        "benchmark_passed": all(coverage_checks.values()),
        "equated_with_collusion": False,
    }
    return report


def _tally(classes: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in classes:
        out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items()))


def validate_geo_benchmark(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != GEO_BENCHMARK_SCHEMA:
        errors.append("schema mismatch")
    coverage = report.get("coverage", {})
    if coverage.get("general_geometric_coverage_claimed") is not False:
        errors.append("general geometric coverage must not be claimed")
    if set(coverage.get("evaluated_subfamilies", [])) != set(SUBFAMILIES):
        errors.append("all five subfamilies must be evaluated and reported")
    enforcement = report.get("enforcement", {})
    if enforcement.get("height_or_size_alone_triggers_enforcement") is not False:
        errors.append("height/size alone must never trigger enforcement")
    if enforcement.get("mode") != "frozen_ladder":
        errors.append("enforcement mode must name the frozen ladder")
    for name, block in report.get("subfamilies", {}).items():
        for side in ("encoded", "benign"):
            for key, metric in block.get(side, {}).items():
                if isinstance(metric, dict) and "n" in metric:
                    if metric.get("successes", 0) > metric["n"]:
                        errors.append(f"{name}/{side}/{key}: successes exceed n")
    return errors


_rate = rate
