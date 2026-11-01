"""Segment repeated elements and extract attribute sequences (CL-39, GEO-01).

The detector-facing segmentation layer for the geometric family.
It consumes **original raster bytes** at native resolution —
never resized, recompressed or resampled before analysis. PNG
is decoded losslessly. JPEG is reconstructed with the baseline
pixel decoder (CL-52, `covertlens/jpeg_pixels.py`) and measured
with an explicit fidelity limitation: lossy reconstruction and
anti-aliasing shift attribute values, so JPEG results record
`media_kind` and must be read as approximate. Progressive or
otherwise out-of-subset JPEGs stay `unsupported_media`.

Method (versioned in `SegmenterConfig`):

1. Background starts from the modal perimeter colour (bucketed
   vote, `background_bucket_shift`) and grows inward from
   matching border pixels: a neighbour joins the background
   region when its colour is within `background_step_tolerance`
   of the pixel it was reached from, so smooth gradients are
   background however far they drift in total. Foreground
   candidates are the remaining pixels farther than
   `background_distance_floor` (Euclidean RGB) from the modal
   colour, cleaned by a 3x3 morphological open/close pass so
   anti-aliased fringes and sensor/JPEG noise do not fuse or
   speckle components (CL-52). A component is foreground when
   any pixel exceeds `background_distance_tolerance`, or when
   it is a coherent near-background element: at least
   `coherent_colour_fraction` of its pixels share one colour
   and it does not touch the image border (the lit-window case:
   flat grey 235 on a 238 background is a drawn element, while
   border-connected or variegated near-background regions are
   background variation and noise).
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
import struct
from dataclasses import asdict, dataclass, field
from typing import Any

from .geometric_fixtures import GRIDS
from .jpeg_pixels import JpegDecodeError, decode_jpeg_rgb, probe_jpeg_size
from .png_pixels import PngDecodeError, decode_png_rgb

SEGMENTER_NAME = "geometric-segmenter"
SEGMENTER_VERSION = "1.1.0"
SEGMENTATION_SCHEMA = "covertlens.segmentation"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

FAILURE_MODES: tuple[dict[str, str], ...] = (
    {
        "status": "no_foreground",
        "meaning": "no pixel is farther than the background distance floor from the modal perimeter colour",
    },
    {
        "status": "too_few_elements",
        "meaning": "fewer than min_elements repeated components found",
    },
    {
        "status": "unsupported_media",
        "meaning": "not a PNG raster or a supported baseline-JPEG raster",
    },
    {
        "status": "limit_exceeded",
        "meaning": "input exceeds byte or pixel limits for this segmenter",
    },
    {
        "status": "corrupt_input",
        "meaning": "bytes claim to be PNG/JPEG but do not decode",
    },
    {
        "status": "corrupt_source",
        "meaning": "a vector source was intercepted but could not be parsed "
        "(CL-41); clearance is refused, never inferred from the raster",
    },
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
    # CL-52 robustness: a component containing any pixel farther
    # than this Euclidean RGB distance from the modal perimeter
    # colour is foreground.
    background_distance_tolerance: float = 24.0
    # CL-52: pixels farther than this floor distance enter the
    # candidate mask; weaker variation never can.
    background_distance_floor: float = 3.0
    # CL-52: a weaker component still counts as an element when
    # at least this fraction of its pixels share its modal colour
    # (and it does not touch the border): flat near-background
    # elements such as lit windows.
    coherent_colour_fraction: float = 0.9
    # CL-52: perimeter background votes are bucketed by dropping
    # this many low bits per channel before the modal vote, so a
    # gradient background beats one flat foreground edge colour.
    background_bucket_shift: int = 4
    # CL-52: maximum per-step Euclidean RGB change for the
    # border-seeded background region to grow through a pixel;
    # absorbs smooth gradients whatever their total drift.
    background_step_tolerance: float = 4.0
    # CL-52: 3x3 morphological open/close on the candidate mask.
    morphology: bool = True

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
    media_kind: str = ""
    config: SegmenterConfig = field(default_factory=SegmenterConfig)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def sequence(self, attribute: str) -> list[Any]:
        """One attribute across elements, in reading order."""
        return [e[attribute] for e in self.elements]

    def sequences(self) -> dict[str, list[Any]]:
        keys = (
            "height",
            "top",
            "width",
            "gap_to_next",
            "angle_deg",
            "colour_index",
            "brightness",
        )
        return {k: self.sequence(k) for k in keys}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SEGMENTATION_SCHEMA,
            "schema_version": 1,
            "segmenter": {"name": self.config.name, "version": self.config.version},
            "status": self.status,
            "media_kind": self.media_kind,
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
                "background_distance_tolerance": self.config.background_distance_tolerance,
                "background_distance_floor": self.config.background_distance_floor,
                "coherent_colour_fraction": self.config.coherent_colour_fraction,
                "background_bucket_shift": self.config.background_bucket_shift,
                "background_step_tolerance": self.config.background_step_tolerance,
                "morphology_3x3_open_close": self.config.morphology,
            },
            "failure_modes": list(FAILURE_MODES),
            "decoded_message": None,
        }


def _components(
    mask: list[bool], width: int, height: int, min_pixels: int
) -> list[list[int]]:
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
            for nidx in (
                idx - 1 if x else -1,
                idx + 1 if x < width - 1 else -1,
                idx - width if y else -1,
                idx + width if y < height - 1 else -1,
            ):
                if nidx >= 0 and mask[nidx] and not seen[nidx]:
                    seen[nidx] = 1
                    stack.append(nidx)
        if len(points) >= min_pixels:
            components.append(points)
    return components


def _reading_order(
    components: list[dict[str, Any]], overlap: float
) -> list[dict[str, Any]]:
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


def _erode(mask: list[bool], width: int, height: int) -> list[bool]:
    """3x3 erosion: foreground survives only with all 8 neighbours set."""
    out = [False] * len(mask)
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            i = row + x
            if (
                mask[i]
                and mask[i - 1]
                and mask[i + 1]
                and mask[i - width]
                and mask[i + width]
                and mask[i - width - 1]
                and mask[i - width + 1]
                and mask[i + width - 1]
                and mask[i + width + 1]
            ):
                out[i] = True
    return out


def _dilate(mask: list[bool], width: int, height: int) -> list[bool]:
    """3x3 dilation: a pixel is set when any of its 8 neighbours is."""
    out = list(mask)
    for y in range(height):
        row = y * width
        for x in range(width):
            i = row + x
            if not mask[i]:
                continue
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < height:
                    continue
                for dx in (-1, 0, 1):
                    nx = x + dx
                    if 0 <= nx < width:
                        out[ny * width + nx] = True
    return out


def _open_close(mask: list[bool], width: int, height: int) -> list[bool]:
    """Morphological open then close (despeckle, fill pinholes)."""
    opened = _dilate(_erode(mask, width, height), width, height)
    return _erode(_dilate(opened, width, height), width, height)


def _background_colour(
    pixels: bytes, width: int, height: int, shift: int = 4
) -> tuple[int, int, int]:
    """Modal colour over the full image perimeter.

    Perimeter colours are first voted into coarse buckets
    (`shift` low bits dropped per channel) so a smooth gradient
    background is not out-voted by one flat foreground colour on
    a single edge; the returned colour is the exact modal colour
    within the winning bucket (CL-52).
    """
    border: dict[tuple[int, int, int], int] = {}
    buckets: dict[tuple[int, int, int], int] = {}

    def count(x: int, y: int) -> None:
        base = (y * width + x) * 3
        c = (pixels[base], pixels[base + 1], pixels[base + 2])
        border[c] = border.get(c, 0) + 1
        b = (c[0] >> shift, c[1] >> shift, c[2] >> shift)
        buckets[b] = buckets.get(b, 0) + 1

    for x in range(width):
        count(x, 0)
        count(x, height - 1)
    for y in range(1, height - 1):
        count(0, y)
        count(width - 1, y)
    winning = max(buckets, key=lambda b: buckets[b])
    in_bucket = {
        c: n
        for c, n in border.items()
        if (c[0] >> shift, c[1] >> shift, c[2] >> shift) == winning
    }
    return max(in_bucket, key=lambda c: in_bucket[c])


def _background_region(
    pixels: bytes,
    width: int,
    height: int,
    background: tuple[int, int, int],
    shift: int,
    step_tolerance: float,
) -> bytearray:
    """Pixels reachable from background-coloured border pixels.

    Growth is 4-connected; a neighbour joins when its colour is
    within `step_tolerance` (Euclidean RGB) of the pixel it was
    reached from, so smooth gradients are absorbed whatever
    their total drift from the modal colour, while a hard edge
    (including the 5.2-step into a flat lit element) blocks.
    Seeds are only border pixels in the modal background bucket,
    so an element clipped by the frame edge is never seeded.
    """
    region = bytearray(width * height)
    bg_bucket = (
        background[0] >> shift,
        background[1] >> shift,
        background[2] >> shift,
    )
    step_sq = step_tolerance**2

    def colour(idx: int) -> tuple[int, int, int]:
        base = idx * 3
        return pixels[base], pixels[base + 1], pixels[base + 2]

    stack: list[int] = []

    def seed(idx: int) -> None:
        c = colour(idx)
        if (c[0] >> shift, c[1] >> shift, c[2] >> shift) == bg_bucket:
            region[idx] = 1
            stack.append(idx)

    for x in range(width):
        seed(x)
        seed((height - 1) * width + x)
    for y in range(1, height - 1):
        seed(y * width)
        seed(y * width + width - 1)
    while stack:
        idx = stack.pop()
        x, y = idx % width, idx // width
        r, g, b = colour(idx)
        for nidx in (
            idx - 1 if x else -1,
            idx + 1 if x < width - 1 else -1,
            idx - width if y else -1,
            idx + width if y < height - 1 else -1,
        ):
            if nidx < 0 or region[nidx]:
                continue
            nr, ng, nb = colour(nidx)
            if (nr - r) ** 2 + (ng - g) ** 2 + (nb - b) ** 2 <= step_sq:
                region[nidx] = 1
                stack.append(nidx)
    return region


def _decode_raster(
    data: bytes, active: SegmenterConfig
) -> tuple[bytes, int, int, str] | SegmentationResult:
    """Decode original bytes, or return the failure result."""
    if data.startswith(_JPEG_MAGIC):
        size = probe_jpeg_size(data)
        if size is None:
            return SegmentationResult(
                "corrupt_input", detail="JPEG frame header not found", config=active
            )
        width, height = size
        if width * height > active.max_pixels:
            return SegmentationResult(
                "limit_exceeded",
                detail="pixel count over limit",
                width=width,
                height=height,
                media_kind="jpeg",
                config=active,
            )
        try:
            pixels, width, height = decode_jpeg_rgb(data, max_pixels=active.max_pixels)
        except JpegDecodeError as exc:
            message = str(exc)
            unsupported = (
                "outside" in message or "unsupported" in message or "only " in message
            )
            return SegmentationResult(
                "unsupported_media" if unsupported else "corrupt_input",
                detail=message,
                width=width,
                height=height,
                media_kind="jpeg",
                config=active,
            )
        return pixels, width, height, "jpeg"
    if not data.startswith(_PNG_MAGIC):
        return SegmentationResult(
            "unsupported_media", detail="not a PNG or JPEG raster", config=active
        )
    png_width = png_height = 0
    if len(data) >= 24:
        png_width, png_height = struct.unpack(">II", data[16:24])
    if png_width * png_height > active.max_pixels:
        return SegmentationResult(
            "limit_exceeded",
            detail="pixel count over limit",
            width=png_width,
            height=png_height,
            media_kind="png",
            config=active,
        )
    try:
        pixels, width, height = decode_png_rgb(data, max_pixels=active.max_pixels)
    except PngDecodeError as exc:
        message = str(exc)
        unsupported = "outside supported subset" in message or "unknown" in message
        return SegmentationResult(
            "unsupported_media" if unsupported else "corrupt_input",
            detail=message,
            width=png_width,
            height=png_height,
            media_kind="png",
            config=active,
        )
    return pixels, width, height, "png"


def segment_image(
    data: bytes, config: SegmenterConfig | None = None
) -> SegmentationResult:
    """Segment repeated elements in original bytes (reading order)."""
    active = config or SegmenterConfig()
    if len(data) > active.max_input_bytes:
        return SegmentationResult(
            "limit_exceeded", detail="input bytes over limit", config=active
        )
    decoded = _decode_raster(data, active)
    if isinstance(decoded, SegmentationResult):
        return decoded
    pixels, width, height, media_kind = decoded
    if width * height > active.max_pixels:
        return SegmentationResult(
            "limit_exceeded",
            detail="pixel count over limit",
            width=width,
            height=height,
            media_kind=media_kind,
            config=active,
        )

    background = _background_colour(
        pixels, width, height, active.background_bucket_shift
    )
    region = _background_region(
        pixels,
        width,
        height,
        background,
        active.background_bucket_shift,
        active.background_step_tolerance,
    )
    tolerance_sq = active.background_distance_tolerance**2
    floor_sq = active.background_distance_floor**2
    br, bg, bb = background
    dist_sq: list[float] = []
    mask = []
    for i in range(0, width * height * 3, 3):
        dr = pixels[i] - br
        dg = pixels[i + 1] - bg
        db = pixels[i + 2] - bb
        d2 = float(dr * dr + dg * dg + db * db)
        dist_sq.append(d2)
        mask.append(d2 > floor_sq and not region[i // 3])
    if active.morphology:
        mask = _open_close(mask, width, height)
    if not any(mask):
        return SegmentationResult(
            "no_foreground",
            width=width,
            height=height,
            media_kind=media_kind,
            config=active,
        )

    raw = []
    for points in _components(mask, width, height, active.min_component_pixels):
        xs = [p % width for p in points]
        ys = [p // width for p in points]
        colours: dict[tuple[int, int, int], int] = {}
        for point in points:
            c = (pixels[point * 3], pixels[point * 3 + 1], pixels[point * 3 + 2])
            colours[c] = colours.get(c, 0) + 1
        colour = max(colours, key=lambda c: colours[c])
        # Two-threshold decision: a component is an element when it
        # contains a strongly non-background pixel, or when it is a
        # coherent flat region away from the border (lit-window
        # elements vs background variation/noise).
        strong = any(dist_sq[p] > tolerance_sq for p in points)
        if not strong:
            touches_border = (
                min(xs) == 0
                or max(xs) == width - 1
                or min(ys) == 0
                or max(ys) == height - 1
            )
            coherent = colours[colour] / len(points) >= active.coherent_colour_fraction
            if touches_border or not coherent:
                continue
        rows: dict[int, list[int]] = {}
        for point in points:
            rows.setdefault(point // width, []).append(point % width)
        ordered_y = sorted(rows)
        mean_y = sum(ordered_y) / len(ordered_y)
        num = sum((y - mean_y) * (sum(rows[y]) / len(rows[y])) for y in ordered_y)
        den = sum((y - mean_y) ** 2 for y in ordered_y) or 1.0
        palette_index = min(
            range(len(active.colour_palette)),
            key=lambda i: math.dist(colour, active.colour_palette[i]),
        )
        raw.append(
            {
                "left": min(xs),
                "top": min(ys),
                "width": max(xs) - min(xs) + 1,
                "height": max(ys) - min(ys) + 1,
                "bottom": max(ys),
                "area": len(points),
                "colour": list(colour),
                "colour_index": palette_index,
                "colour_distance": round(
                    math.dist(colour, active.colour_palette[palette_index]), 3
                ),
                "brightness": round(sum(colour) / 3.0, 3),
                "angle_deg": round(math.degrees(math.atan(-(num / den))), 3),
            }
        )
    ordered = _reading_order(raw, active.row_overlap_fraction)
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
            }
        )
    detail = (
        "jpeg raster reconstructed lossily; attributes are approximate"
        if media_kind == "jpeg"
        else ""
    )
    if len(elements) < active.min_elements:
        return SegmentationResult(
            "too_few_elements",
            detail=f"{len(elements)} element(s) below min_elements={active.min_elements}",
            width=width,
            height=height,
            elements=elements,
            media_kind=media_kind,
            config=active,
        )
    return SegmentationResult(
        "ok",
        width=width,
        height=height,
        elements=elements,
        detail=detail,
        media_kind=media_kind,
        config=active,
    )


def validate_segmentation(doc: dict[str, Any]) -> list[str]:
    """Return validation errors for a segmentation result doc."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(
        doc.get("schema") == SEGMENTATION_SCHEMA,
        f"schema must be {SEGMENTATION_SCHEMA}",
    )
    need(
        doc.get("decoded_message") is None,
        "segmentation must not claim a decoded message (C-09)",
    )
    segmenter = doc.get("segmenter") or {}
    need(segmenter.get("name") == SEGMENTER_NAME, "segmenter name is required")
    need(bool(segmenter.get("version")), "segmenter version is required")
    statuses = {m["status"] for m in FAILURE_MODES} | {"ok"}
    need(doc.get("status") in statuses, "status must be a recorded status/failure mode")
    if doc.get("status") == "ok":
        need(
            doc.get("element_count", 0) >= 3, "ok results need >= min_elements elements"
        )
        elements = doc.get("elements") or []
        need(
            [e["index"] for e in elements] == list(range(len(elements))),
            "elements must be indexed in reading order",
        )
    return errors
