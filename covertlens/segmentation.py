"""Segment repeated elements and extract attribute sequences (CL-39, GEO-01).

The detector-facing segmentation layer for the geometric family.
It consumes **original raster bytes**: PNG is decoded losslessly
and analysed at native resolution — never resized, recompressed
or resampled before analysis. JPEG input is rejected with an
explicit `unsupported_media` status (JPEG rasterization would
blur the exact attribute values this layer must measure; a JPEG
path needs its own fidelity study, it is not silently degraded).

Method (versioned in `SegmenterConfig`):

1. Background is the modal border colour; everything else is
   foreground.
2. Repeated elements are 4-connected foreground components of at
   least `min_component_pixels` pixels.
3. Components are ordered in **reading order**: grouped into rows
   by vertical overlap, rows top-to-bottom, elements left-to-right
   within a row.
4. Per element, a numeric attribute record is extracted: bounding
   box (left/top/width/height), area, gap to the next element in
   the row, tilt angle (row-centroid regression), dominant colour
   with nearest declared-palette index + distance, and mean
   brightness.

Failure modes are explicit statuses, never silent empty results:
`no_foreground`, `too_few_elements`, `unsupported_media`,
`limit_exceeded`, `corrupt_input`. Tolerances and failure modes
are recorded in the result so CL-40 scoring can cite exactly what
was measured. This layer extracts sequences; whether a sequence
is *encoded* is CL-40's question, and no output here is a decoded
message (C-09).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .fixtures import _load_png
from .geometric_fixtures import GRIDS

SEGMENTER_NAME = "geometric-segmenter"
SEGMENTER_VERSION = "1.0.0"
SEGMENTATION_SCHEMA = "covertlens.segmentation"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

FAILURE_MODES: tuple[dict[str, str], ...] = (
    {"status": "no_foreground",
     "meaning": "no pixel differs from the border background"},
    {"status": "too_few_elements",
     "meaning": "fewer than min_elements repeated components found"},
    {"status": "unsupported_media",
     "meaning": "not a PNG raster (JPEG would blur measured attributes)"},
    {"status": "limit_exceeded",
     "meaning": "input exceeds byte or pixel limits for this segmenter"},
    {"status": "corrupt_input",
     "meaning": "bytes claim to be PNG but do not decode"},
    {"status": "corrupt_source",
     "meaning": "a vector source was intercepted but could not be parsed "
                "(CL-41); clearance is refused, never inferred from the raster"},
)


@dataclass(frozen=True)
class SegmenterConfig:
    """Versioned segmentation method, tolerances and limits."""

    name: str = SEGMENTER_NAME
    version: str = SEGMENTER_VERSION
    min_component_pixels: int = 8
    min_elements: int = 3
    row_overlap_fraction: float = 0.5
    max_input_bytes: int = 10 * 1024 * 1024
    max_pixels: int = 2_000_000
    colour_palette: tuple[tuple[int, int, int], ...] = tuple(
        GRIDS["colour_code"]["palette"]
    )
    angle_tolerance_deg: float = 3.5
    attribute_tolerance_px: float = 1.6

    def to_dict(self) -> dict[str, Any]:
        doc = asdict(self)
        doc["colour_palette"] = [list(c) for c in self.colour_palette]
        return doc


@dataclass
class SegmentationResult:
    """Per-element attribute records in reading order."""

    status: str
    width: int = 0
    height: int = 0
    elements: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""
    config: SegmenterConfig = field(default_factory=SegmenterConfig)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def sequence(self, attribute: str) -> list[Any]:
        """One attribute across elements, in reading order."""
        return [e[attribute] for e in self.elements]

    def sequences(self) -> dict[str, list[Any]]:
        keys = ("height", "top", "width", "gap_to_next", "angle_deg",
                "colour_index", "brightness")
        return {k: self.sequence(k) for k in keys}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SEGMENTATION_SCHEMA,
            "schema_version": 1,
            "segmenter": {"name": self.config.name, "version": self.config.version},
            "status": self.status,
            "detail": self.detail,
            "width": self.width,
            "height": self.height,
            "element_count": len(self.elements),
            "elements": self.elements,
            "sequences": self.sequences() if self.elements else {},
            "tolerances": {
                "angle_tolerance_deg": self.config.angle_tolerance_deg,
                "attribute_tolerance_px": self.config.attribute_tolerance_px,
                "min_component_pixels": self.config.min_component_pixels,
            },
            "failure_modes": list(FAILURE_MODES),
            "decoded_message": None,
        }


def _components(mask: list[bool], width: int, height: int,
                min_pixels: int) -> list[list[int]]:
    """4-connected foreground components (iterative flood fill)."""
    seen = bytearray(len(mask))
    components: list[list[int]] = []
    for start, filled in enumerate(mask):
        if not filled or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        points: list[int] = []
        while stack:
            idx = stack.pop()
            points.append(idx)
            x, y = idx % width, idx // width
            for nidx in (idx - 1 if x else -1, idx + 1 if x < width - 1 else -1,
                         idx - width if y else -1,
                         idx + width if y < height - 1 else -1):
                if nidx >= 0 and mask[nidx] and not seen[nidx]:
                    seen[nidx] = 1
                    stack.append(nidx)
        if len(points) >= min_pixels:
            components.append(points)
    return components


def _reading_order(components: list[dict[str, Any]],
                   overlap: float) -> list[dict[str, Any]]:
    """Group into rows by vertical overlap; rows top-down, items L-to-R."""
    rows: list[dict[str, Any]] = []
    for comp in sorted(components, key=lambda c: (c["top"], c["left"])):
        placed = False
        for row in rows:
            shared = min(row["bottom"], comp["bottom"]) - max(row["top"], comp["top"])
            if shared >= overlap * comp["height"]:
                row["items"].append(comp)
                row["top"] = min(row["top"], comp["top"])
                row["bottom"] = max(row["bottom"], comp["bottom"])
                placed = True
                break
        if not placed:
            rows.append({"top": comp["top"], "bottom": comp["bottom"], "items": [comp]})
    ordered: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: r["top"]):
        ordered.extend(sorted(row["items"], key=lambda c: c["left"]))
    return ordered


def segment_image(data: bytes, config: SegmenterConfig | None = None) -> SegmentationResult:
    """Segment repeated elements in original PNG bytes (reading order)."""
    active = config or SegmenterConfig()
    if len(data) > active.max_input_bytes:
        return SegmentationResult("limit_exceeded", detail="input bytes over limit",
                                  config=active)
    if data.startswith(_JPEG_MAGIC):
        return SegmentationResult(
            "unsupported_media",
            detail="JPEG raster would blur measured attributes; PNG required",
            config=active,
        )
    if not data.startswith(_PNG_MAGIC):
        return SegmentationResult("unsupported_media", detail="not a PNG raster",
                                  config=active)
    try:
        pixels, width, height = _load_png(data)
    except Exception as exc:  # corrupt or non-RGB PNG
        return SegmentationResult("corrupt_input", detail=str(exc), config=active)
    if width * height > active.max_pixels:
        return SegmentationResult("limit_exceeded", detail="pixel count over limit",
                                  width=width, height=height, config=active)

    border: dict[tuple[int, int, int], int] = {}
    for x in range(width):
        for y in (0, height - 1):
            c = tuple(pixels[(y * width + x) * 3:(y * width + x) * 3 + 3])
            border[c] = border.get(c, 0) + 1
    background = max(border, key=border.get)
    mask = [
        tuple(pixels[i:i + 3]) != background
        for i in range(0, width * height * 3, 3)
    ]
    if not any(mask):
        return SegmentationResult("no_foreground", width=width, height=height,
                                  config=active)

    raw = []
    for points in _components(mask, width, height, active.min_component_pixels):
        xs = [p % width for p in points]
        ys = [p // width for p in points]
        colours: dict[tuple[int, int, int], int] = {}
        for p in points:
            c = tuple(pixels[p * 3:p * 3 + 3])
            colours[c] = colours.get(c, 0) + 1
        colour = max(colours, key=colours.get)
        rows: dict[int, list[int]] = {}
        for p in points:
            rows.setdefault(p // width, []).append(p % width)
        ordered_y = sorted(rows)
        mean_y = sum(ordered_y) / len(ordered_y)
        num = sum((y - mean_y) * (sum(rows[y]) / len(rows[y])) for y in ordered_y)
        den = sum((y - mean_y) ** 2 for y in ordered_y) or 1.0
        palette_index = min(
            range(len(active.colour_palette)),
            key=lambda i: math.dist(colour, active.colour_palette[i]),
        )
        raw.append({
            "left": min(xs), "top": min(ys),
            "width": max(xs) - min(xs) + 1,
            "height": max(ys) - min(ys) + 1,
            "bottom": max(ys),
            "area": len(points),
            "colour": list(colour),
            "colour_index": palette_index,
            "colour_distance": round(math.dist(colour, active.colour_palette[palette_index]), 3),
            "brightness": round(sum(colour) / 3.0, 3),
            "angle_deg": round(math.degrees(math.atan(-(num / den))), 3),
        })
    ordered = _reading_order(raw, active.row_overlap_fraction)
    elements: list[dict[str, Any]] = []
    for i, comp in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        gap = None
        if nxt is not None:
            shared = min(comp["bottom"], nxt["bottom"]) - max(comp["top"], nxt["top"])
            if shared >= 0.5 * min(comp["height"], nxt["height"]):
                gap = nxt["left"] - (comp["left"] + comp["width"])
        elements.append({
            "index": i,
            "left": comp["left"], "top": comp["top"],
            "width": comp["width"], "height": comp["height"],
            "area": comp["area"],
            "gap_to_next": gap,
            "angle_deg": comp["angle_deg"],
            "colour": comp["colour"],
            "colour_index": comp["colour_index"],
            "colour_distance": comp["colour_distance"],
            "brightness": comp["brightness"],
        })
    if len(elements) < active.min_elements:
        return SegmentationResult(
            "too_few_elements",
            detail=f"{len(elements)} element(s) below min_elements={active.min_elements}",
            width=width, height=height, elements=elements, config=active,
        )
    return SegmentationResult("ok", width=width, height=height,
                              elements=elements, config=active)


def validate_segmentation(doc: dict[str, Any]) -> list[str]:
    """Return validation errors for a segmentation result doc."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(doc.get("schema") == SEGMENTATION_SCHEMA, f"schema must be {SEGMENTATION_SCHEMA}")
    need(doc.get("decoded_message") is None,
         "segmentation must not claim a decoded message (C-09)")
    segmenter = doc.get("segmenter") or {}
    need(segmenter.get("name") == SEGMENTER_NAME, "segmenter name is required")
    need(bool(segmenter.get("version")), "segmenter version is required")
    statuses = {m["status"] for m in FAILURE_MODES} | {"ok"}
    need(doc.get("status") in statuses, "status must be a recorded status/failure mode")
    if doc.get("status") == "ok":
        need(doc.get("element_count", 0) >= 3, "ok results need >= min_elements elements")
        elements = doc.get("elements") or []
        need([e["index"] for e in elements] == list(range(len(elements))),
             "elements must be indexed in reading order")
    return errors
