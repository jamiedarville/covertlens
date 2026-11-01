"""Geometric paired fixtures and benign negatives (CL-38, GEO-07/DT-07).

Clean/encoded paired scenes for geometric/semantic encoding,
analogous to the CL-9 LSB/DCT fixtures: the same scene rendered as
a PNG raster (the delivered, scored artifact), with and without an
encoded attribute sequence. Five subfamilies (GEO-06):

- `height_position` — bar heights on an 8-level grid (px);
- `gap_timing` — inter-element gaps on a 4-level grid (px);
- `lit_dark` — binary lit/dark element states;
- `colour_code` — ternary palette colour codes;
- `angle_tilt` — element tilt on a 5-level degree grid.

Encoded scenes place attributes *exactly* on the declared grid;
clean scenes use continuous, off-grid variation of the same scene.
The declared payload unit is the symbol sequence (per subfamily
alphabet); there is no byte payload and nothing here decodes a
message (C-09).

Every fixture is verified by **independent re-measurement**: the
attribute sequence is re-derived from the raster pixels (column
projection segmentation — the renderer parameters are never read
back), and encoded fixtures must recover their exact symbols.
Benign negatives include a legitimate chart whose heights are
grid-snapped *by design* (the GEO-05 trap: quantization alone is
not an encoding claim), unencoded scenes, a benign brightness
edit, and a generator variation. Generator, encoder, seeds,
configs and units are recorded per fixture; scorer ground truth
(symbols/attributes) is a separate, role-gated export (DT-04),
and splits follow the CL-10 lineage-group policy.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import ids
from .fixtures import _load_png, _save_png
from .splits import SPLITS, SplitPolicy, _split_for_group

GEO_GENERATOR_NAME = "geometric-scenes"
GEO_GENERATOR_VERSION = "1.0.0"
GEO_ENCODER_NAME = "geometric-attributes"
GEO_ENCODER_VERSION = "1.0.0"
GEO_FAMILY = "geometric"
SUBFAMILIES = ("height_position", "gap_timing", "lit_dark", "colour_code", "angle_tilt")
DEFAULT_WIDTH = 384
DEFAULT_HEIGHT = 128
BASE_Y = 112  # ground line (pixels above are element space)
BAR_WIDTH = 12
MARGIN_X = 16

# Declared grids: symbol -> attribute value (the payload units).
GRIDS: dict[str, dict[str, Any]] = {
    "height_position": {"unit": "height_level", "base": 16.0, "step": 10.0, "alphabet": 8},
    "gap_timing": {"unit": "gap_level", "base": 6.0, "step": 6.0, "alphabet": 4},
    "lit_dark": {"unit": "lit_state", "levels": (45.0, 235.0), "alphabet": 2},
    "colour_code": {
        "unit": "colour_index",
        "palette": ((200, 60, 50), (60, 170, 70), (60, 90, 200)),
        "alphabet": 3,
    },
    "angle_tilt": {"unit": "tilt_level", "base": -30.0, "step": 15.0, "alphabet": 5},
}
_BACKGROUND = (238, 238, 232)
_BAR_COLOUR = (70, 110, 160)


@dataclass(frozen=True)
class GeoFixture:
    """One rendered geometric scene plus provenance (no byte payload)."""

    fixture_id: str
    pair_id: str
    subfamily: str
    role: str  # clean | encoded | negative
    width: int
    height: int
    data: bytes = field(repr=False)
    symbols: tuple[int, ...] = ()          # scorer-side ground truth (encoded)
    attributes: tuple[float, ...] = ()     # scorer-side ground truth (all roles)
    scene_seed: int = 0
    payload_seed: int = 0
    negative_kind: str | None = None
    context: str = "scene"                 # scene | chart (GEO-05)
    generator: dict[str, Any] = field(default_factory=dict)
    encoder: dict[str, Any] = field(default_factory=dict)

    @property
    def family(self) -> str:
        return GEO_FAMILY

    @property
    def media_kind(self) -> str:
        return "png"

    @property
    def content_hash(self) -> str:
        return ids.content_hash(self.data)


# ---------------------------------------------------------------- scenes ---

def _symbols(payload_seed: int, count: int, alphabet: int) -> tuple[int, ...]:
    rng = random.Random(payload_seed)
    return tuple(rng.randrange(alphabet) for _ in range(count))


def _off_grid(rng: random.Random, low: float, high: float, grid_values: list[float],
              clearance: float) -> float:
    """Continuous value kept at least `clearance` from every grid point."""
    for _ in range(64):
        value = low + rng.random() * (high - low)
        if all(abs(value - g) >= clearance for g in grid_values):
            return round(value, 3)
    raise ValueError("could not place an off-grid value")


def _scene_elements(
    subfamily: str, *, encoded: bool, scene_seed: int, payload_seed: int,
    n_elements: int,
) -> tuple[list[dict[str, Any]], tuple[int, ...], tuple[float, ...]]:
    """Element attribute plan for one scene (renderer-side only)."""
    grid = GRIDS[subfamily]
    rng = random.Random(scene_seed)
    symbols: tuple[int, ...] = ()
    if subfamily == "gap_timing":
        count = n_elements - 1
    else:
        count = n_elements
    if encoded:
        symbols = _symbols(payload_seed, count, int(grid["alphabet"]))
    elements: list[dict[str, Any]] = []
    attributes: list[float] = []
    x = MARGIN_X
    for i in range(n_elements):
        element: dict[str, Any] = {
            "x": x, "width": BAR_WIDTH, "height": 56.0,
            "colour": _BAR_COLOUR, "angle": 0.0, "gap_after": 10.0,
        }
        if subfamily == "height_position":
            if encoded:
                value = grid["base"] + symbols[i] * grid["step"]
            else:
                value = _off_grid(rng, 16, 86,
                                  [grid["base"] + s * grid["step"] for s in range(8)], 2.5)
            element["height"] = value
            attributes.append(value)
        elif subfamily == "gap_timing" and i < n_elements - 1:
            if encoded:
                value = grid["base"] + symbols[i] * grid["step"]
            else:
                value = _off_grid(rng, 6, 24,
                                  [grid["base"] + s * grid["step"] for s in range(4)], 1.8)
            element["gap_after"] = value
            attributes.append(value)
        elif subfamily == "lit_dark":
            if encoded:
                value = grid["levels"][symbols[i]]
            else:
                value = _off_grid(rng, 45, 235, list(grid["levels"]), 18.0)
            grey = int(round(value))
            element["colour"] = (grey, grey, grey)
            attributes.append(value)
        elif subfamily == "colour_code":
            if encoded:
                element["colour"] = grid["palette"][symbols[i]]
                attributes.append(float(symbols[i]))
            else:
                base = grid["palette"][rng.randrange(3)]
                colour = tuple(
                    max(0, min(255, c + rng.randint(-70, 70))) for c in base
                )
                if min(
                    math.dist(colour, p) for p in grid["palette"]
                ) < 30.0:
                    colour = (120, 120, 40)
                element["colour"] = colour
                attributes.append(float(_nearest_colour(colour, grid["palette"])))
        elif subfamily == "angle_tilt":
            if encoded:
                value = grid["base"] + symbols[i] * grid["step"]
            else:
                value = _off_grid(rng, -30, 30,
                                  [grid["base"] + s * grid["step"] for s in range(5)], 3.0)
            element["angle"] = value
            element["height"] = 44.0
            element["width"] = 10
            element["gap_after"] = 46.0
            attributes.append(value)
        elements.append(element)
        x += int(element["width"]) + int(round(element["gap_after"]))
    return elements, symbols, tuple(attributes)


def _render(elements: list[dict[str, Any]], width: int, height: int,
            background: tuple[int, int, int] = _BACKGROUND) -> bytes:
    pixels = bytearray(bytes(background) * (width * height))

    def put(px: int, py: int, colour: tuple[int, int, int]) -> None:
        if 0 <= px < width and 0 <= py < height:
            i = (py * width + px) * 3
            pixels[i:i + 3] = bytes(colour)

    for element in elements:
        colour = element["colour"]
        angle = float(element["angle"])
        length = float(element["height"])
        cx = element["x"] + element["width"] / 2.0
        if abs(angle) < 0.01:
            top = int(round(BASE_Y - length))
            for py in range(top, BASE_Y):
                for px in range(int(element["x"]), int(element["x"] + element["width"])):
                    put(px, py, colour)
        else:
            rad = math.radians(angle)
            dirx, diry = math.sin(rad), -math.cos(rad)
            perpx, perpy = math.cos(rad), math.sin(rad)
            half = element["width"] / 2.0
            for py in range(0, BASE_Y + 1):
                for px in range(int(cx - length), int(cx + length)):
                    rx, ry = px - cx, py - BASE_Y
                    along = rx * dirx + ry * diry
                    perp = rx * perpx + ry * perpy
                    if 0 <= along <= length and abs(perp) <= half:
                        put(px, py, colour)
    return _save_png(bytes(pixels), width, height)


# --------------------------------------------------------- re-measurement ---

def _border_background(pixels: bytes, width: int, height: int) -> tuple[int, int, int]:
    counts: dict[tuple[int, int, int], int] = {}
    for x in range(width):
        for y in (0, height - 1):
            c = tuple(pixels[(y * width + x) * 3:(y * width + x) * 3 + 3])
            counts[c] = counts.get(c, 0) + 1
    return max(counts, key=counts.get)


def segment_elements(pixels: bytes, width: int, height: int) -> list[dict[str, Any]]:
    """Column-projection segmentation (independent of the renderer)."""
    background = _border_background(pixels, width, height)

    def foreground(px: int, py: int) -> bool:
        i = (py * width + px) * 3
        return tuple(pixels[i:i + 3]) != background

    columns = [
        any(foreground(x, y) for y in range(height)) for x in range(width)
    ]
    groups: list[tuple[int, int]] = []
    start: int | None = None
    for x, filled in enumerate(columns):
        if filled and start is None:
            start = x
        elif not filled and start is not None:
            groups.append((start, x - 1))
            start = None
    if start is not None:
        groups.append((start, width - 1))
    elements = []
    for left, right in groups:
        pts = [
            (x, y) for x in range(left, right + 1) for y in range(height)
            if foreground(x, y)
        ]
        if len(pts) < 8:
            continue
        colours: dict[tuple[int, int, int], int] = {}
        for x, y in pts:
            c = tuple(pixels[(y * width + x) * 3:(y * width + x) * 3 + 3])
            colours[c] = colours.get(c, 0) + 1
        colour = max(colours, key=colours.get)
        rows: dict[int, list[int]] = {}
        for x, y in pts:
            rows.setdefault(y, []).append(x)
        ys = sorted(rows)
        slope_num = sum(
            (y - sum(ys) / len(ys)) * (sum(rows[y]) / len(rows[y]))
            for y in ys
        )
        slope_den = sum((y - sum(ys) / len(ys)) ** 2 for y in ys) or 1.0
        slope = slope_num / slope_den
        elements.append({
            "left": left,
            "right": right,
            "top": min(ys),
            "bottom": max(ys),
            "height": max(ys) - min(ys) + 1,
            "colour": colour,
            "brightness": sum(colour) / 3.0,
            "angle_deg": round(math.degrees(math.atan(-slope)), 3),
        })
    return elements


def _nearest_colour(colour: tuple[int, int, int], palette) -> int:
    return min(range(len(palette)), key=lambda i: math.dist(colour, palette[i]))


def measure_attributes(pixels: bytes, width: int, height: int,
                       subfamily: str) -> tuple[list[float], list[int]]:
    """Re-measure (attributes, recovered symbols) from raster pixels only."""
    elements = segment_elements(pixels, width, height)
    grid = GRIDS[subfamily]
    attributes: list[float] = []
    symbols: list[int] = []
    if subfamily == "height_position":
        for e in elements:
            attributes.append(float(e["height"]))
            symbols.append(int(round((e["height"] - grid["base"]) / grid["step"])))
    elif subfamily == "gap_timing":
        for prev, nxt in zip(elements, elements[1:]):
            gap = float(nxt["left"] - prev["right"] - 1)
            attributes.append(gap)
            symbols.append(int(round((gap - grid["base"]) / grid["step"])))
    elif subfamily == "lit_dark":
        low, high = grid["levels"]
        for e in elements:
            attributes.append(float(e["brightness"]))
            symbols.append(0 if abs(e["brightness"] - low) < abs(e["brightness"] - high) else 1)
    elif subfamily == "colour_code":
        for e in elements:
            idx = _nearest_colour(e["colour"], grid["palette"])
            attributes.append(float(idx))
            symbols.append(idx)
    elif subfamily == "angle_tilt":
        for e in elements:
            attributes.append(float(e["angle_deg"]))
            symbols.append(int(round((e["angle_deg"] - grid["base"]) / grid["step"])))
    return attributes, symbols


def verify_geo_fixture(fixture: GeoFixture) -> bool:
    """Independent re-measurement must reproduce the ground truth."""
    pixels, width, height = _load_png(fixture.data)
    attributes, symbols = measure_attributes(pixels, width, height, fixture.subfamily)
    if fixture.role == "encoded":
        return tuple(symbols) == fixture.symbols
    if len(attributes) != len(fixture.attributes):
        return False
    tolerance = {"lit_dark": 6.0, "colour_code": 0.0, "angle_tilt": 3.5}.get(
        fixture.subfamily, 1.6
    )
    return all(abs(a - b) <= tolerance for a, b in zip(attributes, fixture.attributes))


# ---------------------------------------------------------------- builders ---

def _fixture(subfamily: str, role: str, pair_id: str, data: bytes,
             symbols: tuple[int, ...], attributes: tuple[float, ...],
             *, scene_seed: int, payload_seed: int, width: int, height: int,
             context: str = "scene", negative_kind: str | None = None) -> GeoFixture:
    digest = ids.content_hash(data)
    generator = {
        "name": GEO_GENERATOR_NAME, "version": GEO_GENERATOR_VERSION,
        "seed": scene_seed, "pattern": f"bars_{subfamily}",
        "width": width, "height": height, "context": context,
    }
    encoder = {
        "name": GEO_ENCODER_NAME if role == "encoded" else "none",
        "version": GEO_ENCODER_VERSION,
        "seed": payload_seed,
        "config": {
            "subfamily": subfamily,
            "unit": GRIDS[subfamily]["unit"],
            "alphabet": GRIDS[subfamily]["alphabet"],
            "grid": {k: v for k, v in GRIDS[subfamily].items()
                     if k in ("base", "step", "levels")},
        },
    }
    return GeoFixture(
        fixture_id=f"geometric-{subfamily}-{role}-{digest.split(':', 1)[1][:12]}",
        pair_id=pair_id, subfamily=subfamily, role=role,
        width=width, height=height, data=data,
        symbols=symbols, attributes=attributes,
        scene_seed=scene_seed, payload_seed=payload_seed,
        negative_kind=negative_kind, context=context,
        generator=generator, encoder=encoder,
    )


def build_geo_pair(
    subfamily: str,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    scene_seed: int = 101,
    payload_seed: int = 202,
    n_elements: int = 12,
) -> tuple[GeoFixture, GeoFixture]:
    """One clean/encoded pair: same scene plan, grid vs off-grid attributes."""
    if subfamily not in SUBFAMILIES:
        raise ValueError(f"subfamily must be one of {SUBFAMILIES}")
    if subfamily == "gap_timing":
        n_elements = min(n_elements, 10)
    if subfamily == "angle_tilt":
        n_elements = min(n_elements, 7)
    pair_id = f"pair-geometric-{subfamily}-{scene_seed}"
    built = []
    for role, encoded in (("clean", False), ("encoded", True)):
        elements, symbols, attributes = _scene_elements(
            subfamily, encoded=encoded, scene_seed=scene_seed + (0 if not encoded else 500_000),
            payload_seed=payload_seed, n_elements=n_elements,
        )
        # Clean and encoded share the scene seed family but must not
        # share jitter: encoded uses grid values; clean was sampled
        # with its own seed stream in _scene_elements via scene_seed.
        data = _render(elements, width, height)
        built.append(_fixture(
            subfamily, role, pair_id, data,
            symbols if encoded else (), attributes,
            scene_seed=scene_seed, payload_seed=payload_seed,
            width=width, height=height,
        ))
    clean, encoded_fx = built
    if not verify_geo_fixture(encoded_fx):
        raise ValueError(f"encoded {subfamily} fixture failed re-measurement")
    if not verify_geo_fixture(clean):
        raise ValueError(f"clean {subfamily} fixture failed re-measurement")
    return clean, encoded_fx


def _negative(subfamily: str, *, kind: str, scene_seed: int,
              width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> GeoFixture:
    n_elements = 9 if kind == "generator_variation" else 12
    elements, _s, attributes = _scene_elements(
        subfamily, encoded=(kind == "legitimate_chart"),
        scene_seed=scene_seed, payload_seed=1, n_elements=n_elements,
    )
    if kind == "legitimate_chart":
        # A legitimate chart's bar heights carry data by design and
        # are grid-snapped: geometrically it can look exactly like
        # an encoded height scene. The recorded chart context is
        # the discriminator (GEO-05) — geometry alone must not
        # trigger enforcement.
        data = _render(elements, width, height)
        context = "chart"
    elif kind == "benign_edit":
        data = _render(elements, width, height)
        pixels, w, h = _load_png(data)
        edited = bytes(min(255, v + 20) for v in pixels)
        data = _save_png(edited, w, h)
        context = "scene"
    elif kind == "generator_variation":
        data = _render(elements, width, height, background=(225, 232, 240))
        context = "scene"
    else:  # unencoded_scene
        data = _render(elements, width, height)
        context = "scene"
    return _fixture(
        subfamily, "negative", f"neg-geometric-{kind}-{scene_seed}", data,
        (), attributes, scene_seed=scene_seed, payload_seed=0,
        width=width, height=height, context=context, negative_kind=kind,
    )


def build_geo_dataset() -> list[GeoFixture]:
    """The default CL-38 suite: 5 subfamilies × 2 pairs + 4 negatives."""
    fixtures: list[GeoFixture] = []
    for i, subfamily in enumerate(SUBFAMILIES):
        for j, scene_seed in enumerate((101 + i * 31, 733 + i * 47)):
            fixtures.extend(build_geo_pair(
                subfamily, scene_seed=scene_seed,
                payload_seed=202 + i * 13 + j * 7,
            ))
    fixtures.append(_negative("height_position", kind="legitimate_chart", scene_seed=4242))
    fixtures.append(_negative("height_position", kind="unencoded_scene", scene_seed=4343))
    fixtures.append(_negative("height_position", kind="benign_edit", scene_seed=4444))
    fixtures.append(_negative("colour_code", kind="generator_variation", scene_seed=4545))
    return fixtures


# ------------------------------------------------------------- exports ---

def geo_manifest(fixtures: Iterable[GeoFixture]) -> dict[str, Any]:
    """Detector-facing manifest: provenance and hashes, never ground truth."""
    rows = list(fixtures)
    return {
        "schema": "covertlens.geometric-fixtures",
        "schema_version": 1,
        "generator": {"name": GEO_GENERATOR_NAME, "version": GEO_GENERATOR_VERSION},
        "encoder": {"name": GEO_ENCODER_NAME, "version": GEO_ENCODER_VERSION},
        "family": GEO_FAMILY,
        "subfamilies": list(SUBFAMILIES),
        "fixtures": [
            {
                "fixture_id": f.fixture_id,
                "pair_id": f.pair_id,
                "subfamily": f.subfamily,
                "role": f.role,
                "media_kind": f.media_kind,
                "width": f.width,
                "height": f.height,
                "content_hash": f.content_hash,
                "context": f.context,
                "negative_kind": f.negative_kind,
                "generator": f.generator,
                "encoder": {
                    "name": f.encoder["name"],
                    "version": f.encoder["version"],
                    "config": f.encoder["config"],
                },
            }
            for f in rows
        ],
    }


def geo_ground_truth(fixtures: Iterable[GeoFixture], *, role: str) -> dict[str, Any]:
    """Scorer-side ground truth; the explicit scorer role is required (DT-04)."""
    if role != "scorer":
        raise PermissionError("geometric ground truth is scorer-only (DT-04)")
    return {
        f.fixture_id: {
            "role": f.role,
            "subfamily": f.subfamily,
            "symbols": list(f.symbols),
            "attributes": list(f.attributes),
            "negative_kind": f.negative_kind,
            "context": f.context,
        }
        for f in fixtures
    }


def geo_group_key(fixture: GeoFixture) -> str:
    """Scene-lineage group: a pair and its derivatives stay together."""
    return f"scene:{fixture.subfamily}:{fixture.scene_seed}:{fixture.width}x{fixture.height}"


def assign_geo_splits(
    fixtures: Iterable[GeoFixture], policy: SplitPolicy | None = None
) -> dict[str, str]:
    """CL-10 lineage-group split assignment for geometric fixtures."""
    active = policy or SplitPolicy()
    return {
        f.fixture_id: _split_for_group(geo_group_key(f), active) for f in fixtures
    }


def validate_geo_splits(
    fixtures: Iterable[GeoFixture], assignments: dict[str, str]
) -> list[str]:
    """Leakage checks mirroring CL-10: groups and pairs never span splits."""
    errors: list[str] = []
    by_group: dict[str, set[str]] = {}
    by_pair: dict[str, set[str]] = {}
    for fixture in fixtures:
        split = assignments.get(fixture.fixture_id)
        if split not in SPLITS:
            errors.append(f"{fixture.fixture_id}: no valid split assigned")
            continue
        by_group.setdefault(geo_group_key(fixture), set()).add(split)
        by_pair.setdefault(fixture.pair_id, set()).add(split)
    for group, found in sorted(by_group.items()):
        if len(found) > 1:
            errors.append(f"group {group} spans splits {sorted(found)}")
    for pair_id, found in sorted(by_pair.items()):
        if len(found) > 1:
            errors.append(f"pair {pair_id} spans splits {sorted(found)}")
    return errors
