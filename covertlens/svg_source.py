"""SVG vector-source parser (CL-69, GEO-04/C-10).

CL-41 parses only the project's own `covertlens.vector-source` JSON
object list. In an agent harness the vector source of a generated
image is usually an SVG (or plotting code, see `mpl_source`). This
parser reads an SVG document with `xml.etree` and produces the CL-39
record shape, measured on the rendered raster's pixel grid, so the
CL-40 tests consume SVG, JSON and raster evidence identically.

Supported, with bounding boxes and fills:

- `rect` (incl. `rx`/`ry`), `circle`, `ellipse`, `line`, `polyline`,
  `polygon` and `path` (M/L/H/V/C/S/Q/T/A/Z, absolute and relative;
  curves and arcs are flattened);
- `fill`, `stroke`, `stroke-width`, `stroke-linecap`, `fill-rule`,
  `opacity`, `fill-opacity`, `stroke-opacity`, `display`,
  `visibility`, as attributes, inline `style` or inherited from
  groups; colours as `#rgb`, `#rrggbb`, `rgb()` or CSS named colours;
- `transform` (`matrix`, `translate`, `scale`, `rotate` with centre,
  `skewX`, `skewY`) composed through nested groups, plus the root
  `viewBox` mapped onto the rendered raster size;
- `<use>` references (depth-limited) and `clip-path` references to
  `<clipPath>` elements (clipped to the clip region's bounding box);
- `<style>` rules whose declarations cannot change geometry or colour
  (matplotlib's `stroke-linejoin`/`stroke-linecap` defaults).

Fail-closed rules (C-10, never a silent clean parse):

- Visible content the parser cannot measure — `text`, `image`,
  `foreignObject`, pattern fills, filters, masks, stylesheet rules
  that could restyle elements, unknown drawing elements — is listed
  in `unparsed`. The combined vector-binding report refuses
  clearance for a partially parsed source
  (`refused_partially_parsed_vector_source`).
- Documents with entity declarations or a DOCTYPE internal subset
  (XML-bomb shapes; a bare public DOCTYPE is fine), over the byte or
  element caps, or that do not parse, return `corrupt_source` or
  `limit_exceeded`, which refuse clearance like CL-41's corrupt
  source.

The rendered raster stays the delivered, scored artifact: this
parser is evidence about that raster, bound by content hash in the
CL-41 binding report. Output carries numeric attributes only, never a
decoded message (C-09).
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from ._shapes import (
    IDENTITY,
    Colour,
    MeasureLimitExceeded,
    Polygon,
    Shape,
    ShapePart,
    VectorParse,
    build_vector_result,
    composite,
    ellipse_points,
    measure_shapes,
    multiply,
    stroke_parts,
    transform_points,
)
from .segmentation import SegmentationResult, SegmenterConfig

SVG_PARSER_NAME = "geometric-svg-parser"
SVG_PARSER_VERSION = "1.0.0"
SVG_SOURCE_KIND = "svg"
MAX_SVG_BYTES = 10 * 1024 * 1024
MAX_SVG_ELEMENTS = 20_000
MAX_PATH_POINTS = 400_000
MAX_USE_DEPTH = 8
MAX_CANVAS_SIDE = 16_384
CURVE_SEGMENTS = 16
SVG_LIMITATIONS = (
    "svg source: attributes measured from vector geometry on the rendered "
    "raster's pixel grid (pixel-centre coverage); anti-aliased edges in "
    "the raster can differ by a pixel",
    "vector objects are measured one by one: touching or overlapping "
    "objects that the raster segmenter fuses into one component stay "
    "separate records",
    "clip paths are applied as their bounding box; curves and arcs are "
    "flattened to line segments",
)

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_DRAWABLE = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"}
_CONTAINERS = {"svg", "g", "a", "switch"}
_NON_RENDERED = {
    "defs",
    "clipPath",
    "mask",
    "pattern",
    "marker",
    "linearGradient",
    "radialGradient",
    "stop",
    "symbol",
    "title",
    "desc",
    "metadata",
    "style",
    "filter",
    "script",
}
_UNMEASURABLE = {"text", "image", "foreignObject", "video", "audio", "iframe", "canvas"}
# CSS properties that cannot move, hide or recolour an element.
_IGNORABLE_CSS = {
    "stroke-linejoin",
    "stroke-linecap",
    "stroke-miterlimit",
    "stroke-dasharray",
    "stroke-dashoffset",
    "shape-rendering",
    "text-rendering",
    "image-rendering",
    "color-interpolation",
    "color-interpolation-filters",
    "vector-effect",
    "white-space",
}
_INHERITED = (
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "fill-rule",
    "fill-opacity",
    "stroke-opacity",
    "visibility",
    "color",
)
_UNITS_PX = {
    "": 1.0,
    "px": 1.0,
    "pt": 96.0 / 72.0,
    "pc": 16.0,
    "in": 96.0,
    "cm": 96.0 / 2.54,
    "mm": 96.0 / 25.4,
}
_NAMED: dict[str, Colour] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "fuchsia": (255, 0, 255),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "lime": (0, 255, 0),
    "teal": (0, 128, 128),
    "navy": (0, 0, 128),
    "purple": (128, 0, 128),
    "orange": (255, 165, 0),
    "brown": (165, 42, 42),
    "pink": (255, 192, 203),
    "gold": (255, 215, 0),
    "darkgray": (169, 169, 169),
    "darkgrey": (169, 169, 169),
    "lightgray": (211, 211, 211),
    "lightgrey": (211, 211, 211),
    "dimgray": (105, 105, 105),
    "dimgrey": (105, 105, 105),
    "whitesmoke": (245, 245, 245),
    "steelblue": (70, 130, 180),
    "darkblue": (0, 0, 139),
    "darkred": (139, 0, 0),
    "darkgreen": (0, 100, 0),
    "skyblue": (135, 206, 235),
    "tomato": (255, 99, 71),
    "crimson": (220, 20, 60),
    "indigo": (75, 0, 130),
    "violet": (238, 130, 238),
    "salmon": (250, 128, 114),
    "coral": (255, 127, 80),
    "khaki": (240, 230, 140),
    "beige": (245, 245, 220),
    "ivory": (255, 255, 240),
    "tan": (210, 180, 140),
    "chocolate": (210, 105, 30),
}
Point_ = tuple[float, float]
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class SvgSourceError(ValueError):
    """The document is not a parseable SVG source within limits."""

    def __init__(self, status: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status


@dataclass
class _Style:
    fill: Any = (0, 0, 0)  # Colour | None | ("url", id)
    stroke: Any = None
    stroke_width: float = 1.0
    linecap: str = "butt"
    fill_rule: str = "nonzero"
    fill_opacity: float = 1.0
    stroke_opacity: float = 1.0
    opacity: float = 1.0
    visible: bool = True
    displayed: bool = True
    color: Colour = (0, 0, 0)
    filter: bool = False
    mask: bool = False
    clip_id: str | None = None


@dataclass
class _State:
    root: ET.Element
    by_id: dict[str, ET.Element]
    canvas: tuple[int, int]
    shapes: list[Shape] = field(default_factory=list)
    unparsed: list[dict[str, Any]] = field(default_factory=list)
    approximations: list[str] = field(default_factory=list)
    points: int = 0
    elements: int = 0
    css: dict[str, dict[str, str]] = field(default_factory=dict)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _length(
    value: str | None, default: float = 0.0, *, reference: float = 0.0
) -> float:
    if value is None or not str(value).strip():
        return default
    text = str(value).strip()
    match = re.fullmatch(
        r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-z%]*)", text
    )
    if not match:
        raise SvgSourceError("corrupt_source", f"bad length {text[:40]!r}")
    number, unit = float(match.group(1)), match.group(2)
    if unit == "%":
        return number / 100.0 * reference
    if unit not in _UNITS_PX:
        raise SvgSourceError("corrupt_source", f"unsupported unit {unit!r}")
    return number * _UNITS_PX[unit]


def parse_colour(value: str | None, current: Colour = (0, 0, 0)) -> Any:
    """Colour | None (no paint) | ("url", id). Raises on garbage."""
    if value is None:
        return None
    text = value.strip()
    low = text.lower()
    if low in ("none", "transparent"):
        return None
    if low == "currentcolor":
        return current
    if low.startswith("url("):
        match = re.match(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)", text)
        if not match:
            raise SvgSourceError("corrupt_source", f"bad paint {text[:40]!r}")
        return ("url", match.group(1))
    if low.startswith("#"):
        digits = low[1:]
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits[:3])
        elif len(digits) in (6, 8):
            digits = digits[:6]
        else:
            raise SvgSourceError("corrupt_source", f"bad colour {text[:20]!r}")
        try:
            return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
        except ValueError:
            raise SvgSourceError(
                "corrupt_source", f"bad colour {text[:20]!r}"
            ) from None
    if low.startswith("rgb"):
        values = re.findall(r"[-+]?\d*\.?\d+%?", low)
        if len(values) < 3:
            raise SvgSourceError("corrupt_source", f"bad colour {text[:30]!r}")
        out = []
        for raw in values[:3]:
            channel = (
                float(raw[:-1]) * 255.0 / 100.0 if raw.endswith("%") else float(raw)
            )
            out.append(int(round(min(255.0, max(0.0, channel)))))
        return (out[0], out[1], out[2])
    if low in _NAMED:
        return _NAMED[low]
    raise SvgSourceError("corrupt_source", f"unknown colour {text[:20]!r}")


def _declarations(style: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in (style or "").split(";"):
        if ":" in item:
            key, value = item.split(":", 1)
            out[key.strip().lower()] = value.strip()
    return out


def _parse_css(state: _State, text: str) -> None:
    """Apply-or-refuse for <style>: only harmless declarations pass."""
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    for selectors, block in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
        props = _declarations(block)
        harmful = sorted(k for k in props if k not in _IGNORABLE_CSS)
        if harmful:
            state.unparsed.append(
                {
                    "element": "style",
                    "reason": "stylesheet rule could restyle elements",
                    "selector": selectors.strip()[:80],
                    "properties": harmful[:8],
                }
            )


def _transform(text: str | None) -> tuple[float, ...]:
    matrix = IDENTITY
    if not text:
        return matrix
    for name, args in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", text):
        nums = [float(n) for n in _NUMBER.findall(args)]
        name = name.strip()
        if name == "matrix" and len(nums) == 6:
            step = tuple(nums)
        elif name == "translate" and nums:
            step = (1.0, 0.0, 0.0, 1.0, nums[0], nums[1] if len(nums) > 1 else 0.0)
        elif name == "scale" and nums:
            sy = nums[1] if len(nums) > 1 else nums[0]
            step = (nums[0], 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate" and nums:
            rad = math.radians(nums[0])
            cos, sin = math.cos(rad), math.sin(rad)
            step = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                step = multiply(
                    multiply((1.0, 0.0, 0.0, 1.0, cx, cy), step),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
        elif name == "skewX" and nums:
            step = (1.0, 0.0, math.tan(math.radians(nums[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and nums:
            step = (1.0, math.tan(math.radians(nums[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            raise SvgSourceError("corrupt_source", f"bad transform {name}({args[:30]})")
        matrix = multiply(matrix, step)
    return matrix


def _attr(element: ET.Element, name: str, state: _State) -> str | None:
    """Presentation value: inline style > attribute (CSS refused upstream)."""
    decl = _declarations(element.get("style"))
    if name in decl:
        return decl[name]
    return element.get(name)


def _style(element: ET.Element, parent: _Style, state: _State) -> _Style:
    style = _Style(**parent.__dict__)
    style.opacity = parent.opacity  # multiplied below
    style.filter = parent.filter
    style.mask = parent.mask
    style.clip_id = None
    colour_value = _attr(element, "color", state)
    if colour_value and colour_value.lower() not in ("inherit", "currentcolor"):
        parsed = parse_colour(colour_value, parent.color)
        if isinstance(parsed, tuple) and len(parsed) == 3 and parsed[0] != "url":
            style.color = parsed
    for name in _INHERITED:
        value = _attr(element, name, state)
        if value is None or value.strip().lower() == "inherit":
            continue
        if name == "fill":
            style.fill = parse_colour(value, style.color)
        elif name == "stroke":
            style.stroke = parse_colour(value, style.color)
        elif name == "stroke-width":
            style.stroke_width = max(0.0, _length(value, 1.0))
        elif name == "stroke-linecap":
            style.linecap = value.strip().lower()
        elif name == "fill-rule":
            style.fill_rule = (
                "evenodd" if value.strip().lower() == "evenodd" else "nonzero"
            )
        elif name == "fill-opacity":
            style.fill_opacity = _opacity(value)
        elif name == "stroke-opacity":
            style.stroke_opacity = _opacity(value)
        elif name == "visibility":
            style.visible = value.strip().lower() not in ("hidden", "collapse")
    opacity = _attr(element, "opacity", state)
    if opacity is not None:
        style.opacity = parent.opacity * _opacity(opacity)
    display = _attr(element, "display", state)
    if display is not None and display.strip().lower() == "none":
        style.displayed = False
    if _attr(element, "filter", state) not in (None, "none", ""):
        style.filter = True
    if _attr(element, "mask", state) not in (None, "none", ""):
        style.mask = True
    clip = _attr(element, "clip-path", state)
    if clip and clip.strip().lower() != "none":
        match = re.match(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)", clip.strip())
        if not match:
            raise SvgSourceError("corrupt_source", f"bad clip-path {clip[:40]!r}")
        style.clip_id = match.group(1)
    return style


def _opacity(value: str) -> float:
    text = value.strip()
    number = float(text[:-1]) / 100.0 if text.endswith("%") else float(text)
    return min(1.0, max(0.0, number))


# -- path data ----------------------------------------------------------------


class _PathScanner:
    """Cursor over SVG path data (arc flags may be packed: 'a1 1 0 00 1 1')."""

    def __init__(self, d: str) -> None:
        self.d = d
        self.i = 0

    def _skip(self) -> None:
        while self.i < len(self.d) and self.d[self.i] in " \t\r\n,":
            self.i += 1

    def done(self) -> bool:
        self._skip()
        return self.i >= len(self.d)

    def command(self) -> str | None:
        """Next command letter, or None when a number follows (repeat)."""
        self._skip()
        ch = self.d[self.i]
        if ch.isalpha():
            if ch not in "MmLlHhVvCcSsQqTtAaZz":
                raise SvgSourceError("corrupt_source", f"bad path command {ch!r}")
            self.i += 1
            return ch
        return None

    def number(self) -> float:
        self._skip()
        match = _NUMBER.match(self.d, self.i)
        if not match:
            raise SvgSourceError("corrupt_source", "path command is missing numbers")
        self.i = match.end()
        return float(match.group(0))

    def flag(self) -> int:
        self._skip()
        if self.i < len(self.d) and self.d[self.i] in "01":
            self.i += 1
            return int(self.d[self.i - 1])
        raise SvgSourceError("corrupt_source", "bad arc flag")


def _cubic(p0: Point_, p1: Point_, p2: Point_, p3: Point_) -> list[Point_]:
    pts = []
    for i in range(1, CURVE_SEGMENTS + 1):
        t = i / CURVE_SEGMENTS
        mt = 1 - t
        pts.append(
            (
                mt**3 * p0[0]
                + 3 * mt * mt * t * p1[0]
                + 3 * mt * t * t * p2[0]
                + t**3 * p3[0],
                mt**3 * p0[1]
                + 3 * mt * mt * t * p1[1]
                + 3 * mt * t * t * p2[1]
                + t**3 * p3[1],
            )
        )
    return pts


def _quadratic(p0: Point_, p1: Point_, p2: Point_) -> list[Point_]:
    pts = []
    for i in range(1, CURVE_SEGMENTS + 1):
        t = i / CURVE_SEGMENTS
        mt = 1 - t
        pts.append(
            (
                mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1],
            )
        )
    return pts


def _arc(
    p0: Point_, rx: float, ry: float, phi_deg: float, large: int, sweep: int, p1: Point_
) -> list[Point_]:
    """SVG endpoint arc -> points (SVG 1.1 F.6.5 centre conversion)."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [p1]
    phi = math.radians(phi_deg % 360.0)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (p0[1] + p1[1]) / 2.0

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        value = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return value

    theta1 = angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle(
        (x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry
    )
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    steps = max(4, int(math.ceil(abs(delta) / (math.pi / 16))))
    pts = []
    for i in range(1, steps + 1):
        t = theta1 + delta * i / steps
        x = rx * math.cos(t)
        y = ry * math.sin(t)
        pts.append((cos_p * x - sin_p * y + cx, sin_p * x + cos_p * y + cy))
    return pts


def parse_path_data(d: str) -> list[tuple[Polygon, bool]]:
    """Flatten SVG path data to (points, closed) subpaths in user units."""
    scan = _PathScanner(d)
    subpaths: list[tuple[Polygon, bool]] = []
    current: Polygon = []
    x = y = 0.0
    start = (0.0, 0.0)
    last_control: Point_ | None = None
    previous = ""
    command = ""

    def flush(closed: bool) -> None:
        nonlocal current
        if len(current) >= 2:
            subpaths.append((current, closed))
        current = []

    def begin() -> None:
        nonlocal current
        if not current:
            current = [(x, y)]

    while not scan.done():
        letter = scan.command()
        if letter is not None:
            if not command and letter not in "Mm":
                # SVG: path data must begin with a moveto.
                raise SvgSourceError("corrupt_source", "path data must start with M")
            command = letter
        elif not command or command in "Zz":
            raise SvgSourceError(
                "corrupt_source", "path data must start with a command"
            )
        rel = command.islower()
        op = command.upper()
        if op == "Z":
            flush(True)
            x, y = start
            last_control = None
        elif op == "M":
            nx, ny = scan.number(), scan.number()
            flush(False)
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            start = (x, y)
            current = [(x, y)]
            command = "l" if rel else "L"  # implicit lineto after moveto
            last_control = None
        elif op == "L":
            nx, ny = scan.number(), scan.number()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            begin()
            current.append((x, y))
            last_control = None
        elif op == "H":
            nx = scan.number()
            x = x + nx if rel else nx
            begin()
            current.append((x, y))
            last_control = None
        elif op == "V":
            ny = scan.number()
            y = y + ny if rel else ny
            begin()
            current.append((x, y))
            last_control = None
        elif op in ("C", "S"):
            if op == "C":
                x1, y1 = scan.number(), scan.number()
                if rel:
                    x1, y1 = x1 + x, y1 + y
            elif previous in ("C", "S") and last_control is not None:
                x1, y1 = 2 * x - last_control[0], 2 * y - last_control[1]
            else:
                x1, y1 = x, y
            x2, y2, ex, ey = scan.number(), scan.number(), scan.number(), scan.number()
            if rel:
                x2, y2, ex, ey = x2 + x, y2 + y, ex + x, ey + y
            begin()
            current.extend(_cubic((x, y), (x1, y1), (x2, y2), (ex, ey)))
            last_control = (x2, y2)
            x, y = ex, ey
        elif op in ("Q", "T"):
            if op == "Q":
                x1, y1 = scan.number(), scan.number()
                if rel:
                    x1, y1 = x1 + x, y1 + y
            elif previous in ("Q", "T") and last_control is not None:
                x1, y1 = 2 * x - last_control[0], 2 * y - last_control[1]
            else:
                x1, y1 = x, y
            ex, ey = scan.number(), scan.number()
            if rel:
                ex, ey = ex + x, ey + y
            begin()
            current.extend(_quadratic((x, y), (x1, y1), (ex, ey)))
            last_control = (x1, y1)
            x, y = ex, ey
        elif op == "A":
            rx, ry, rot = scan.number(), scan.number(), scan.number()
            large, sweep = scan.flag(), scan.flag()
            ex, ey = scan.number(), scan.number()
            if rel:
                ex, ey = ex + x, ey + y
            begin()
            current.extend(_arc((x, y), rx, ry, rot, large, sweep, (ex, ey)))
            last_control = None
            x, y = ex, ey
        previous = op
    flush(False)
    return subpaths


# -- element geometry ---------------------------------------------------------


def _geometry(element: ET.Element, name: str) -> list[tuple[Polygon, bool]]:
    """Untransformed outline(s) of one drawable, in user units."""
    if name == "rect":
        x, y = _length(element.get("x")), _length(element.get("y"))
        w, h = _length(element.get("width")), _length(element.get("height"))
        if w <= 0 or h <= 0:
            return []
        rx_raw, ry_raw = element.get("rx"), element.get("ry")
        rx = _length(rx_raw) if rx_raw is not None else None
        ry = _length(ry_raw) if ry_raw is not None else None
        if rx is None and ry is not None:
            rx = ry
        if ry is None and rx is not None:
            ry = rx
        rx = min(max(rx or 0.0, 0.0), w / 2)
        ry = min(max(ry or 0.0, 0.0), h / 2)
        if rx == 0 or ry == 0:
            return [([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
        pts: Polygon = []
        corners = (
            (x + w - rx, y + ry, -90),
            (x + w - rx, y + h - ry, 0),
            (x + rx, y + h - ry, 90),
            (x + rx, y + ry, 180),
        )
        for cx, cy, a0 in corners:
            for k in range(9):
                t = math.radians(a0 + 90 * k / 8)
                pts.append((cx + rx * math.cos(t), cy + ry * math.sin(t)))
        return [(pts, True)]
    if name == "circle":
        r = _length(element.get("r"))
        if r <= 0:
            return []
        return [
            (
                ellipse_points(
                    _length(element.get("cx")), _length(element.get("cy")), r, r
                ),
                True,
            )
        ]
    if name == "ellipse":
        rx, ry = _length(element.get("rx")), _length(element.get("ry"))
        if rx <= 0 or ry <= 0:
            return []
        return [
            (
                ellipse_points(
                    _length(element.get("cx")), _length(element.get("cy")), rx, ry
                ),
                True,
            )
        ]
    if name == "line":
        return [
            (
                [
                    (_length(element.get("x1")), _length(element.get("y1"))),
                    (_length(element.get("x2")), _length(element.get("y2"))),
                ],
                False,
            )
        ]
    if name in ("polyline", "polygon"):
        nums = [float(n) for n in _NUMBER.findall(element.get("points") or "")]
        if len(nums) % 2:
            raise SvgSourceError("corrupt_source", f"{name} points must be pairs")
        pts = [(nums[k], nums[k + 1]) for k in range(0, len(nums), 2)]
        return [(pts, name == "polygon")] if len(pts) >= 2 else []
    if name == "path":
        return parse_path_data(element.get("d") or "")
    return []


def _clip_bbox(
    state: _State, clip_id: str, ctm: tuple[float, ...]
) -> tuple[float, float, float, float] | None:
    clip = state.by_id.get(clip_id)
    if clip is None or _local(clip.tag) != "clipPath":
        raise SvgSourceError("corrupt_source", f"clip-path #{clip_id} not found")
    if (clip.get("clipPathUnits") or "userSpaceOnUse") != "userSpaceOnUse":
        state.unparsed.append(
            {
                "element": "clipPath",
                "reason": "objectBoundingBox clip units",
                "id": clip_id,
            }
        )
        return None
    xs: list[float] = []
    ys: list[float] = []
    clip_ctm = multiply(ctm, _transform(clip.get("transform")))
    for child in clip.iter():
        name = _local(child.tag)
        if name not in _DRAWABLE:
            continue
        child_ctm = multiply(clip_ctm, _transform(child.get("transform")))
        for points, _closed in _geometry(child, name):
            for px, py in transform_points(child_ctm, points):
                xs.append(px)
                ys.append(py)
        if name != "rect":
            state.approximations.append(
                "non-rect clip path applied as its bounding box"
            )
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return min(xs), min(ys), max(xs), max(ys)


def _paint_colour(
    state: _State, paint: Any, style_alpha: float, background: Colour
) -> Colour | None:
    if paint is None:
        return None
    if isinstance(paint, tuple) and paint and paint[0] == "url":
        target = state.by_id.get(paint[1])
        kind = _local(target.tag) if target is not None else ""
        if kind in ("linearGradient", "radialGradient"):
            stops = []
            for stop in target.iter():  # type: ignore[union-attr]
                if _local(stop.tag) == "stop":
                    decl = _declarations(stop.get("style"))
                    value = decl.get("stop-color", stop.get("stop-color", "black"))
                    colour = parse_colour(value)
                    if (
                        isinstance(colour, tuple)
                        and len(colour) == 3
                        and colour[0] != "url"
                    ):
                        stops.append(colour)
            if not stops:
                return None
            state.approximations.append(
                "gradient fill measured as the mean stop colour"
            )
            mean = tuple(
                int(round(sum(c[i] for c in stops) / len(stops))) for i in range(3)
            )
            return composite(mean, style_alpha, background)  # type: ignore[arg-type]
        raise SvgSourceError("unparsed", f"{kind or 'unknown'} paint server")
    return composite(paint, style_alpha, background)


def _walk(
    state: _State,
    element: ET.Element,
    parent_style: _Style,
    ctm: tuple[float, ...],
    clip: tuple[float, float, float, float] | None,
    depth: int,
    shapes: list[tuple[Shape, _Style]],
) -> None:
    state.elements += 1
    if state.elements > MAX_SVG_ELEMENTS:
        raise SvgSourceError("limit_exceeded", "svg element count over limit")
    name = _local(element.tag)
    if name in _NON_RENDERED:
        return
    style = _style(element, parent_style, state)
    if not style.displayed:
        return
    local_ctm = multiply(ctm, _transform(element.get("transform")))
    local_clip = clip
    if style.clip_id:
        box = _clip_bbox(state, style.clip_id, local_ctm)
        if box is not None:
            local_clip = (
                box
                if local_clip is None
                else (
                    max(local_clip[0], box[0]),
                    max(local_clip[1], box[1]),
                    min(local_clip[2], box[2]),
                    min(local_clip[3], box[3]),
                )
            )
    if name in _CONTAINERS:
        if name == "svg" and element is not state.root:
            state.unparsed.append({"element": "svg", "reason": "nested svg viewport"})
            return
        for child in element:
            _walk(state, child, style, local_ctm, local_clip, depth, shapes)
        return
    if name == "use":
        href = element.get(f"{{{_XLINK_NS}}}href") or element.get("href") or ""
        target = state.by_id.get(href.lstrip("#")) if href.startswith("#") else None
        if target is None:
            state.unparsed.append({"element": "use", "reason": "unresolved reference"})
            return
        if depth >= MAX_USE_DEPTH:
            raise SvgSourceError("limit_exceeded", "use nesting over limit")
        offset = (
            1.0,
            0.0,
            0.0,
            1.0,
            _length(element.get("x")),
            _length(element.get("y")),
        )
        use_ctm = multiply(local_ctm, offset)
        target_name = _local(target.tag)
        if target_name == "symbol":
            if target.get("viewBox"):
                state.unparsed.append({"element": "symbol", "reason": "symbol viewBox"})
                return
            for child in target:
                _walk(state, child, style, use_ctm, local_clip, depth + 1, shapes)
            return
        _walk(state, target, style, use_ctm, local_clip, depth + 1, shapes)
        return
    if name in _UNMEASURABLE:
        if style.visible:
            state.unparsed.append({"element": name, "reason": "content not measurable"})
        return
    if name not in _DRAWABLE:
        if len(element) or (element.text or "").strip():
            state.unparsed.append(
                {"element": name or "unknown", "reason": "unknown element"}
            )
        return
    if not style.visible:
        return
    if style.filter or style.mask:
        state.unparsed.append(
            {"element": name, "reason": "filter or mask changes its appearance"}
        )
        return
    outline = _geometry(element, name)
    if not outline:
        return
    transformed = [
        (transform_points(local_ctm, pts), closed) for pts, closed in outline
    ]
    state.points += sum(len(pts) for pts, _ in transformed)
    if state.points > MAX_PATH_POINTS:
        raise SvgSourceError("limit_exceeded", "svg path complexity over limit")
    parts: list[ShapePart] = []
    has_fill = style.fill is not None and name not in ("line",)
    fillable = [pts for pts, _closed in transformed if len(pts) >= 3]
    if has_fill and fillable:
        parts.append(ShapePart(fillable, rule=style.fill_rule))
    stroke_scale = math.sqrt(
        abs(local_ctm[0] * local_ctm[3] - local_ctm[1] * local_ctm[2])
    )
    if style.stroke is not None and style.stroke_width > 0:
        parts.extend(
            stroke_parts(
                transformed,
                style.stroke_width * stroke_scale / 2.0,
                square_caps=style.linecap in ("square", "round"),
            )
        )
    if not parts:
        return
    shape = Shape(
        parts=parts,
        colour=(0, 0, 0),
        kind=name,
        source_index=len(shapes),
        clip=local_clip,
        detail={"id": element.get("id")},
    )
    shapes.append((shape, style))


def _canvas(
    root: ET.Element, raster_size: tuple[int, int] | None
) -> tuple[tuple[int, int], tuple[float, ...]]:
    """Canvas size in raster pixels and the root user-space -> pixel matrix."""
    view_box = [float(n) for n in _NUMBER.findall(root.get("viewBox") or "")]
    width_attr, height_attr = root.get("width"), root.get("height")
    if len(view_box) == 4 and (view_box[2] <= 0 or view_box[3] <= 0):
        raise SvgSourceError("corrupt_source", "viewBox must have positive size")
    vb_w = view_box[2] if len(view_box) == 4 else None
    vb_h = view_box[3] if len(view_box) == 4 else None
    css_w = (
        _length(width_attr, vb_w or 0.0)
        if width_attr and "%" not in width_attr
        else (vb_w or 0.0)
    )
    css_h = (
        _length(height_attr, vb_h or 0.0)
        if height_attr and "%" not in height_attr
        else (vb_h or 0.0)
    )
    if raster_size is not None:
        canvas_w, canvas_h = int(raster_size[0]), int(raster_size[1])
    else:
        canvas_w, canvas_h = int(round(css_w)), int(round(css_h))
    if canvas_w <= 0 or canvas_h <= 0:
        raise SvgSourceError(
            "corrupt_source", "svg has no usable width/height or viewBox"
        )
    if canvas_w > MAX_CANVAS_SIDE or canvas_h > MAX_CANVAS_SIDE:
        raise SvgSourceError("limit_exceeded", "svg canvas over limit")
    if len(view_box) == 4:
        min_x, min_y, vw, vh = view_box
        aspect = (root.get("preserveAspectRatio") or "xMidYMid meet").split()
        if aspect and aspect[0] == "none":
            sx, sy = canvas_w / vw, canvas_h / vh
            tx, ty = -min_x * sx, -min_y * sy
        else:
            slice_ = len(aspect) > 1 and aspect[1] == "slice"
            scale = (
                max(canvas_w / vw, canvas_h / vh)
                if slice_
                else min(canvas_w / vw, canvas_h / vh)
            )
            sx = sy = scale
            align = aspect[0] if aspect else "xMidYMid"
            extra_x = canvas_w - vw * scale
            extra_y = canvas_h - vh * scale
            fx = 0.0 if "xMin" in align else 1.0 if "xMax" in align else 0.5
            fy = 0.0 if "YMin" in align else 1.0 if "YMax" in align else 0.5
            tx = -min_x * scale + extra_x * fx
            ty = -min_y * scale + extra_y * fy
        return (canvas_w, canvas_h), (sx, 0.0, 0.0, sy, tx, ty)
    if css_w <= 0 or css_h <= 0:
        raise SvgSourceError(
            "corrupt_source", "svg has no usable width/height or viewBox"
        )
    return (canvas_w, canvas_h), (
        canvas_w / css_w,
        0.0,
        0.0,
        canvas_h / css_h,
        0.0,
        0.0,
    )


_DOCTYPE = re.compile(rb"<!doctype\b[^>\[]*(\[)?", re.IGNORECASE)


def _load(data: bytes) -> ET.Element:
    if len(data) > MAX_SVG_BYTES:
        raise SvgSourceError("limit_exceeded", "svg bytes over limit")
    # Entity expansion is the classic XML bomb: refuse any entity
    # declaration and any DOCTYPE internal subset. A bare public
    # DOCTYPE (matplotlib writes one) is allowed; ElementTree never
    # fetches external DTDs.
    if re.search(rb"<!entity", data, re.IGNORECASE):
        raise SvgSourceError("corrupt_source", "ENTITY declarations are refused")
    doctypes = list(_DOCTYPE.finditer(data))
    if len(doctypes) > 1 or any(match.group(1) for match in doctypes):
        raise SvgSourceError("corrupt_source", "DOCTYPE internal subsets are refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SvgSourceError("corrupt_source", f"xml parse error: {exc}") from None
    if _local(root.tag) != "svg":
        raise SvgSourceError("corrupt_source", "root element is not <svg>")
    return root


def parse_svg_source(
    data: bytes,
    *,
    raster_size: tuple[int, int] | None = None,
    config: SegmenterConfig | None = None,
) -> VectorParse:
    """Parse an SVG vector source into CL-39 records on the raster grid.

    `raster_size` is the rendered raster's (width, height); the root
    viewBox (or width/height) maps onto it. Without it the canvas is
    the SVG's CSS pixel size.
    """
    base = config or SegmenterConfig()
    active = SegmenterConfig(
        **{
            **base.__dict__,
            "name": SVG_PARSER_NAME,
            "version": SVG_PARSER_VERSION,
        }
    )
    background: Colour = (255, 255, 255)
    try:
        root = _load(data)
        by_id = {el.get("id"): el for el in root.iter() if el.get("id")}
        canvas, root_ctm = _canvas(root, raster_size)
        state = _State(root=root, by_id=by_id, canvas=canvas)  # type: ignore[arg-type]
        for style_el in root.iter():
            if _local(style_el.tag) == "style":
                _parse_css(state, "".join(style_el.itertext()))
        shapes: list[tuple[Shape, _Style]] = []
        _walk(state, root, _Style(), root_ctm, None, 0, shapes)

        def colour_of(shape: Shape, style: _Style, bg: Colour) -> Colour | None:
            fill_part = shape.parts and style.fill is not None and shape.kind != "line"
            paint = style.fill if fill_part else style.stroke
            alpha = style.opacity * (
                style.fill_opacity if fill_part else style.stroke_opacity
            )
            if alpha <= 0:
                return None
            try:
                return _paint_colour(state, paint, alpha, bg)
            except SvgSourceError as exc:
                state.unparsed.append({"element": shape.kind, "reason": str(exc)})
                return None

        raw, background, panels = measure_shapes(
            shapes, canvas, background, active, colour_of=colour_of
        )
    except MeasureLimitExceeded as exc:
        return VectorParse(
            SegmentationResult("limit_exceeded", detail=str(exc), config=active),
            limitations=SVG_LIMITATIONS,
        )
    except SvgSourceError as exc:
        status = exc.status if exc.status in ("limit_exceeded",) else "corrupt_source"
        return VectorParse(
            SegmentationResult(status, detail=str(exc), config=active),
            limitations=SVG_LIMITATIONS,
        )
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        return VectorParse(
            SegmentationResult(
                "corrupt_source", detail=f"bad svg value: {exc}", config=active
            ),
            limitations=SVG_LIMITATIONS,
        )
    return build_vector_result(
        raw,
        canvas,
        active,
        media_kind="svg",
        unparsed=state.unparsed,
        approximations=state.approximations,
        background=background,
        panels=panels,
        shapes=len(shapes),
        limitations=SVG_LIMITATIONS,
    )


def svg_from_fixture(fixture: Any) -> bytes:
    """Emit the SVG a CL-38 fixture's raster corresponds to (generator side).

    Harness-side helper for tests and demos, like CL-41's
    `build_vector_source`: detector code never builds a source from a
    delivered artifact. Tilted elements rotate about the element's
    base centre exactly as the CL-38 renderer draws them.
    """
    from .vector_source import build_vector_source

    doc = build_vector_source(fixture)
    width, height = doc["canvas"]["width"], doc["canvas"]["height"]
    from .geometric_fixtures import BASE_Y, SCENE_BACKGROUND

    bg = "#{:02x}{:02x}{:02x}".format(*SCENE_BACKGROUND)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{bg}"/>',
    ]
    for obj in doc["objects"]:
        colour = "#{:02x}{:02x}{:02x}".format(*obj["colour"])
        x, w, length = obj["x"], obj["width"], obj["height"]
        angle = obj["angle_deg"]
        if abs(angle) < 0.01:
            top = int(round(BASE_Y - length))
            lines.append(
                f'<rect x="{x}" y="{top}" width="{w}" height="{BASE_Y - top}" fill="{colour}"/>'
            )
        else:
            cx = x + w / 2.0
            lines.append(
                f'<rect x="{cx - w / 2.0}" y="{BASE_Y - length}" width="{w}" '
                f'height="{length}" fill="{colour}" '
                f'transform="rotate({angle} {cx} {BASE_Y})"/>'
            )
    lines.append("</svg>")
    return "\n".join(lines).encode()
