"""Shared vector-shape geometry for the CL-69 source parsers.

Vector parsers (SVG, matplotlib) reduce every drawable to *parts*:
closed polygons in the rendered raster's pixel coordinates (x right,
y down, origin at the top-left pixel corner). This module measures
those parts on the raster's own pixel grid so a parsed source yields
the CL-39 record shape with the CL-39 definitions:

- a pixel is covered when its centre lies inside the shape (fill
  rule per part; parts of one shape are unioned, so stroke segments
  never cancel each other);
- bbox, area and gap are pixel counts, exactly as segmentation
  counts them;
- tilt is the CL-39 row-centroid regression over covered pixels.

Nothing is rasterised to an image and no colours are mixed between
shapes: each shape is measured on its own, so touching objects stay
separate records (the raster segmenter would fuse them; the
difference is recorded by the parsers as a limitation).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .segmentation import SegmentationResult, SegmenterConfig

Point = tuple[float, float]
Polygon = list[Point]
Colour = tuple[int, int, int]


@dataclass
class ShapePart:
    """Polygons filled together under one fill rule."""

    polygons: list[Polygon]
    rule: str = "nonzero"  # nonzero | evenodd


@dataclass
class Shape:
    """One drawable: its parts, painted colour and provenance."""

    parts: list[ShapePart]
    colour: Colour
    kind: str
    source_index: int
    clip: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1
    detail: dict[str, Any] = field(default_factory=dict)

    def bounds(self) -> tuple[float, float, float, float] | None:
        xs = [x for part in self.parts for poly in part.polygons for x, _ in poly]
        ys = [y for part in self.parts for poly in part.polygons for _, y in poly]
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


def composite(colour: Colour, alpha: float, background: Colour) -> Colour:
    """Paint `colour` at `alpha` over `background` (straight alpha)."""
    a = min(1.0, max(0.0, alpha))
    return (
        int(round(background[0] + (colour[0] - background[0]) * a)),
        int(round(background[1] + (colour[1] - background[1]) * a)),
        int(round(background[2] + (colour[2] - background[2]) * a)),
    )


def _intervals(part: ShapePart, y: float) -> list[tuple[float, float]]:
    """Inside intervals of one part on the horizontal line at `y`."""
    crossings: list[tuple[float, int]] = []
    for poly in part.polygons:
        n = len(poly)
        if n < 3:
            continue
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if y0 == y1:
                continue
            # Half-open rule: an edge spans [min_y, max_y).
            if (y0 <= y < y1) or (y1 <= y < y0):
                x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                crossings.append((x, 1 if y1 > y0 else -1))
    if not crossings:
        return []
    crossings.sort()
    out: list[tuple[float, float]] = []
    winding = 0
    start = 0.0
    for x, direction in crossings:
        before = winding % 2 != 0 if part.rule == "evenodd" else winding != 0
        winding += direction
        after = winding % 2 != 0 if part.rule == "evenodd" else winding != 0
        if not before and after:
            start = x
        elif before and not after and x > start:
            out.append((start, x))
    return out


def _union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    return merged


def coverage(
    shape: Shape, width: int, height: int
) -> dict[int, tuple[int, int, int]] | None:
    """Covered pixels per row: {row: (count, sum_x, (min_x << 16 | max_x))}.

    Returns None when the shape covers no pixel centre on the canvas.
    """
    bounds = shape.bounds()
    if bounds is None:
        return None
    x_lo, y_lo, x_hi, y_hi = bounds
    clip = (0.0, 0.0, float(width), float(height))
    if shape.clip is not None:
        clip = (
            max(clip[0], shape.clip[0]),
            max(clip[1], shape.clip[1]),
            min(clip[2], shape.clip[2]),
            min(clip[3], shape.clip[3]),
        )
    first_row = max(0, math.ceil(max(y_lo, clip[1]) - 0.5))
    last_row = min(height - 1, math.ceil(min(y_hi, clip[3]) - 0.5) - 1)
    rows: dict[int, tuple[int, int, int]] = {}
    for py in range(first_row, last_row + 1):
        y = py + 0.5
        spans: list[tuple[float, float]] = []
        for part in shape.parts:
            spans.extend(_intervals(part, y))
        count = 0
        sum_x = 0
        min_x = None
        max_x = None
        for low, high in _union(spans):
            low = max(low, clip[0])
            high = min(high, clip[2])
            # Pixel px is covered when low <= px + 0.5 < high.
            first = max(0, math.ceil(low - 0.5))
            last = min(width - 1, math.ceil(high - 0.5) - 1)
            if last < first:
                continue
            n = last - first + 1
            count += n
            # Exact integer sum of the run first..last.
            sum_x += (first + last) * n // 2
            min_x = first if min_x is None else min(min_x, first)
            max_x = last if max_x is None else max(max_x, last)
        if count and min_x is not None and max_x is not None:
            rows[py] = (count, sum_x, (min_x << 16) | max_x)
    if not rows and x_hi > clip[0] and x_lo < clip[2]:
        # Thinner than the pixel-centre grid (hairlines): fall back to
        # the pixels the bbox touches, like an anti-aliased render.
        left = max(0, int(math.floor(max(x_lo, clip[0]))))
        right = min(width - 1, int(math.ceil(min(x_hi, clip[2]))) - 1)
        top = max(0, int(math.floor(max(y_lo, clip[1]))))
        bottom = min(height - 1, int(math.ceil(min(y_hi, clip[3]))) - 1)
        right = max(right, left)
        bottom = max(bottom, top)
        if left > width - 1 or top > height - 1:
            return None
        n = right - left + 1
        for py in range(top, bottom + 1):
            rows[py] = (n, (left + right) * n // 2, (left << 16) | right)
    return rows or None


def shape_record(
    shape: Shape,
    width: int,
    height: int,
    palette: tuple[Colour, ...],
) -> dict[str, Any] | None:
    """CL-39 raw component record for one shape, or None if it covers nothing."""
    rows = coverage(shape, width, height)
    if not rows:
        return None
    ordered_y = sorted(rows)
    area = sum(rows[y][0] for y in ordered_y)
    left = min(rows[y][2] >> 16 for y in ordered_y)
    right = max(rows[y][2] & 0xFFFF for y in ordered_y)
    centres = {y: rows[y][1] / rows[y][0] for y in ordered_y}
    mean_y = sum(ordered_y) / len(ordered_y)
    num = sum((y - mean_y) * centres[y] for y in ordered_y)
    den = sum((y - mean_y) ** 2 for y in ordered_y) or 1.0
    colour = shape.colour
    # With no fixed palette (the default since CL-78) the index is set
    # later from the palette discovered over every element, exactly as
    # on the raster path (`build_vector_result`).
    palette_index = (
        min(range(len(palette)), key=lambda i: math.dist(colour, palette[i]))
        if palette
        else 0
    )
    return {
        "left": left,
        "top": ordered_y[0],
        "width": right - left + 1,
        "height": ordered_y[-1] - ordered_y[0] + 1,
        "bottom": ordered_y[-1],
        "area": area,
        "colour": list(colour),
        "colour_index": palette_index,
        "colour_distance": (
            round(math.dist(colour, palette[palette_index]), 3) if palette else 0.0
        ),
        "brightness": round(sum(colour) / 3.0, 3),
        "angle_deg": round(math.degrees(math.atan(-(num / den))), 3),
        "_kind": shape.kind,
        "_source_index": shape.source_index,
    }


def element_records(raw: list[dict[str, Any]], overlap: float) -> list[dict[str, Any]]:
    """Reading order plus gaps, with the CL-39 same-row gap rule."""
    from .segmentation import reading_order

    ordered = reading_order(raw, overlap)
    elements: list[dict[str, Any]] = []
    for i, comp in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        gap = None
        if nxt is not None:
            shared = min(comp["bottom"], nxt["bottom"]) - max(comp["top"], nxt["top"])
            if shared >= 0.5 * min(comp["height"], nxt["height"]):
                gap = nxt["left"] - (comp["left"] + comp["width"])
        elements.append(
            {
                "index": i,
                "left": comp["left"],
                "top": comp["top"],
                "width": comp["width"],
                "height": comp["height"],
                "area": comp["area"],
                "gap_to_next": gap,
                "angle_deg": comp["angle_deg"],
                "colour": comp["colour"],
                "colour_index": comp["colour_index"],
                "colour_distance": comp["colour_distance"],
                "brightness": comp["brightness"],
                "source_kind": comp["_kind"],
                "source_index": comp["_source_index"],
            }
        )
    return elements


# -- polygon builders -------------------------------------------------------


def transform_points(matrix: tuple[float, ...], points: Polygon) -> Polygon:
    a, b, c, d, e, f = matrix
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in points]


def multiply(m1: tuple[float, ...], m2: tuple[float, ...]) -> tuple[float, ...]:
    """m1 then m2 applied as m1 x m2 (SVG matrix order: m1 * m2 * point)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


IDENTITY: tuple[float, ...] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def ellipse_points(
    cx: float, cy: float, rx: float, ry: float, segments: int = 64
) -> Polygon:
    return [
        (
            cx + rx * math.cos(2 * math.pi * i / segments),
            cy + ry * math.sin(2 * math.pi * i / segments),
        )
        for i in range(segments)
    ]


def stroke_parts(
    polylines: list[tuple[Polygon, bool]], half_width: float, *, square_caps: bool
) -> list[ShapePart]:
    """Stroke outline as one quad per segment (unioned, never cancelled)."""
    parts: list[ShapePart] = []
    if half_width <= 0:
        return parts
    for points, closed in polylines:
        segments = list(zip(points, points[1:]))
        if closed and len(points) > 2:
            segments.append((points[-1], points[0]))
        for (x0, y0), (x1, y1) in segments:
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            ux, uy = dx / length, dy / length
            nx, ny = -uy * half_width, ux * half_width
            if square_caps:
                x0, y0 = x0 - ux * half_width, y0 - uy * half_width
                x1, y1 = x1 + ux * half_width, y1 + uy * half_width
            parts.append(
                ShapePart(
                    [
                        [
                            (x0 + nx, y0 + ny),
                            (x1 + nx, y1 + ny),
                            (x1 - nx, y1 - ny),
                            (x0 - nx, y0 - ny),
                        ]
                    ]
                )
            )
    return parts


# -- shared parse result ------------------------------------------------------

# A filled shape covering at least this fraction of the canvas is a
# background panel (figure/axes background), not a repeated element.
BACKGROUND_PANEL_FRACTION = 0.5
# Total scanline work (rows x polygon edges) one source may cost, so a
# hostile document cannot make measurement unbounded.
MAX_MEASURE_WORK = 20_000_000


class MeasureLimitExceeded(ValueError):
    """The canvas or the measurement work is over its limit."""


def check_canvas(canvas: tuple[int, int], config: SegmenterConfig) -> None:
    width, height = canvas
    if width > 0xFFFF or width * height > config.max_pixels:
        raise MeasureLimitExceeded("canvas pixel count over limit")


@dataclass
class VectorParse:
    """A vector-source parse: CL-39 records plus fail-closed coverage notes.

    `unparsed` lists visible content the parser could not measure; a
    source with any entry there is only partially parsed and never
    clears a delivery (C-10).
    """

    result: SegmentationResult
    unparsed: list[dict[str, Any]] = field(default_factory=list)
    approximations: list[str] = field(default_factory=list)
    background: Colour = (255, 255, 255)
    panels: int = 0
    shapes: int = 0
    limitations: tuple[str, ...] = ()

    @property
    def fully_parsed(self) -> bool:
        return self.result.status in ("ok", "too_few_elements") and not self.unparsed

    def to_dict(self) -> dict[str, Any]:
        return {
            "parser": {
                "name": self.result.config.name,
                "version": self.result.config.version,
            },
            "status": self.result.status,
            "detail": self.result.detail,
            "fully_parsed": self.fully_parsed,
            "unparsed": [dict(item) for item in self.unparsed],
            "approximations": sorted(set(self.approximations)),
            "background": list(self.background),
            "background_panels": self.panels,
            "drawn_shapes": self.shapes,
            "element_count": len(self.result.elements),
            "limitations": list(self.limitations),
        }


def measure_shapes(
    shapes: list[tuple[Shape, Any]],
    canvas: tuple[int, int],
    background: Colour,
    config: SegmenterConfig,
    *,
    colour_of: Callable[[Shape, Any, Colour], Colour | None],
) -> tuple[list[dict[str, Any]], Colour, int]:
    """Background panels, visibility and CL-39 raw records for drawn shapes.

    `colour_of(shape, style, background)` returns the painted colour,
    or None when the shape paints nothing visible. A panel covering
    almost the whole canvas becomes the background colour; elements
    painted in the background colour are invisible in the raster too,
    and so are components below the segmenter's minimum size.
    """
    check_canvas(canvas, config)
    width, height = canvas
    canvas_area = float(width * height)
    raw: list[dict[str, Any]] = []
    panels = 0
    work = 0
    for shape, style in shapes:
        bounds = shape.bounds()
        if bounds is not None:
            rows = max(0, min(height, math.ceil(bounds[3])) - max(0, int(bounds[1])))
            edges = sum(len(poly) for part in shape.parts for poly in part.polygons)
            work += rows * edges
            if work > MAX_MEASURE_WORK:
                raise MeasureLimitExceeded("vector measurement work over limit")
        colour = colour_of(shape, style, background)
        if colour is None:
            continue
        record = shape_record(
            Shape(
                shape.parts,
                colour,
                shape.kind,
                shape.source_index,
                shape.clip,
                shape.detail,
            ),
            width,
            height,
            config.colour_palette,
        )
        if record is None:
            continue
        if record["area"] >= BACKGROUND_PANEL_FRACTION * canvas_area:
            panels += 1
            if record["area"] >= 0.98 * canvas_area:
                background = colour
            continue
        if math.dist(colour, background) <= config.background_distance_floor:
            continue  # painted in the background colour: invisible
        if record["area"] < config.min_component_pixels:
            continue
        raw.append(record)
    return raw, background, panels


def build_vector_result(
    raw: list[dict[str, Any]],
    canvas: tuple[int, int],
    config: SegmenterConfig,
    *,
    media_kind: str,
    unparsed: list[dict[str, Any]],
    approximations: list[str],
    background: Colour,
    panels: int,
    shapes: int,
    limitations: tuple[str, ...],
) -> VectorParse:
    """Reading-ordered records wrapped in a SegmentationResult + notes."""
    from .segmentation import SegmentationResult, assign_colour_indices

    # Same discovered palette as the raster path (CL-78).
    assign_colour_indices(raw, config)
    elements = element_records(raw, config.row_overlap_fraction)
    detail_bits = []
    if unparsed:
        detail_bits.append(f"{len(unparsed)} unparsed construct(s)")
    status = "ok" if len(elements) >= config.min_elements else "too_few_elements"
    if status == "too_few_elements":
        detail_bits.append(f"{media_kind} source has too few visible elements")
    width, height = canvas
    return VectorParse(
        SegmentationResult(
            status,
            width=width,
            height=height,
            elements=elements,
            detail="; ".join(detail_bits),
            media_kind=media_kind,
            config=config,
        ),
        unparsed=list(unparsed),
        approximations=list(approximations),
        background=background,
        panels=panels,
        shapes=shapes,
        limitations=limitations,
    )
