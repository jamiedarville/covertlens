"""matplotlib figure vector-source adapter (CL-69, GEO-04/C-10).

Plotting code is the other usual vector source of a generated chart.
This adapter reads a live `matplotlib.figure.Figure` (after drawing
it, so layout and transforms are final) and produces the CL-39
record shape on the rendered raster's pixel grid, through the same
shape measurement as the SVG parser (`covertlens._shapes`).

matplotlib is an optional dependency (`pip install
'covertlens[matplotlib]'`); the library itself stays standard-library
only and imports matplotlib lazily here.

Measured artists:

- patches, including every bar of a `BarContainer` (`ax.bar`,
  `ax.barh`, histograms), rectangles, polygons, circles, wedges and
  path patches, with face colour, edge colour/width and clip box;
- collections: `LineCollection` segments (per-segment colour and
  width) and path-based collections (`PolyCollection`,
  `PatchCollection`, `PathCollection` scatter markers) with their
  per-item transforms and offsets, drawn in matplotlib's own order;
- `Line2D` lines without markers, and visible spines.

Fail-closed (C-10): visible text (titles, tick labels, annotations),
tick marks, line markers, images, legends and any unknown artist are
listed in `unparsed`, so the combined report refuses clearance for a
partially parsed figure. Hatching and dashes are recorded as
approximations. The rendered raster stays the delivered, scored
artifact; nothing here decodes a message (C-09).
"""

from __future__ import annotations

import math
from typing import Any

from ._shapes import (
    Colour,
    MeasureLimitExceeded,
    Polygon,
    Shape,
    ShapePart,
    VectorParse,
    build_vector_result,
    composite,
    measure_shapes,
    stroke_parts,
)
from .segmentation import SegmentationResult, SegmenterConfig

MPL_PARSER_NAME = "geometric-matplotlib-adapter"
MPL_PARSER_VERSION = "1.0.0"
MPL_SOURCE_KIND = "matplotlib"
MAX_MPL_SHAPES = 20_000
MPL_LIMITATIONS = (
    "matplotlib source: attributes measured from the drawn figure's "
    "display-space geometry on the rendered raster's pixel grid; "
    "anti-aliased raster edges can differ by a pixel",
    "artists are measured one by one: touching bars that the raster "
    "segmenter fuses stay separate records",
    "the raster must be saved from the same figure (same size and dpi, "
    "or pass raster_size) and without bbox_inches='tight' cropping",
)
_NO_MARKER = (None, "None", "none", "", " ")


def _require_matplotlib() -> Any:
    try:
        import matplotlib
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise ImportError(
            "the matplotlib adapter needs matplotlib: "
            "pip install 'covertlens[matplotlib]'"
        ) from exc
    return matplotlib


def _rgb(rgba: Any) -> tuple[Colour, float]:
    values = [float(v) for v in list(rgba)[:4]]
    if len(values) == 3:
        values.append(1.0)
    colour = tuple(int(round(min(1.0, max(0.0, v)) * 255)) for v in values[:3])
    return colour, values[3]  # type: ignore[return-value]


class _Canvas:
    """Display (y up, figure px) -> raster pixel (y down) mapping."""

    def __init__(self, figure: Any, raster_size: tuple[int, int] | None) -> None:
        self.fig_w = float(figure.bbox.width)
        self.fig_h = float(figure.bbox.height)
        if raster_size is not None:
            self.size = (int(raster_size[0]), int(raster_size[1]))
        else:
            self.size = (int(round(self.fig_w)), int(round(self.fig_h)))
        self.sx = self.size[0] / self.fig_w
        self.sy = self.size[1] / self.fig_h
        self.px_per_point = float(figure.dpi) / 72.0

    def points(self, xy: Any) -> Polygon:
        return [
            (float(x) * self.sx, (self.fig_h - float(y)) * self.sy)
            for x, y in xy
            if math.isfinite(float(x)) and math.isfinite(float(y))
        ]

    def clip(self, artist: Any) -> tuple[float, float, float, float] | None:
        if not artist.get_clip_on():
            return None
        box = artist.get_clip_box()
        if box is None:
            return None
        x0, y0, x1, y1 = box.x0, box.y0, box.x1, box.y1
        return (
            min(x0, x1) * self.sx,
            (self.fig_h - max(y0, y1)) * self.sy,
            max(x0, x1) * self.sx,
            (self.fig_h - min(y0, y1)) * self.sy,
        )

    def stroke(self, linewidth_points: float) -> float:
        return linewidth_points * self.px_per_point * (self.sx + self.sy) / 4.0


class _Walker:
    def __init__(self, figure: Any, canvas: _Canvas) -> None:
        self.figure = figure
        self.canvas = canvas
        self.shapes: list[tuple[Shape, dict[str, Any]]] = []
        self.unparsed: list[dict[str, Any]] = []
        self.approximations: list[str] = []
        self.containers = 0

    def _add(
        self,
        kind: str,
        fill: list[Polygon],
        stroke: list[tuple[Polygon, bool]],
        style: dict[str, Any],
        clip: tuple[float, float, float, float] | None,
    ) -> None:
        if len(self.shapes) >= MAX_MPL_SHAPES:
            raise ValueError("figure has too many artists for the adapter limit")
        parts: list[ShapePart] = []
        polygons = [p for p in fill if len(p) >= 3]
        if polygons and style.get("fill_alpha", 0.0) > 0:
            parts.append(ShapePart(polygons))
        if style.get("stroke_half", 0.0) > 0 and style.get("stroke_alpha", 0.0) > 0:
            parts.extend(stroke_parts(stroke, style["stroke_half"], square_caps=False))
        if parts:
            shape = Shape(parts, (0, 0, 0), kind, len(self.shapes), clip)
            self.shapes.append((shape, style))

    # -- artists ---------------------------------------------------------

    def patch(self, patch: Any, kind: str = "patch") -> None:
        if not patch.get_visible():
            return
        if patch.get_hatch():
            self.approximations.append("patch hatching is measured as a plain fill")
        if patch.get_linestyle() not in ("solid", "-", None):
            self.approximations.append("dashed edges are measured as solid")
        transform = patch.get_transform()
        polygons = [
            self.canvas.points(poly)
            for poly in patch.get_path().to_polygons(transform, closed_only=False)
        ]
        face, face_alpha = _rgb(patch.get_facecolor())
        edge, edge_alpha = _rgb(patch.get_edgecolor())
        filled = bool(patch.get_fill())
        style = {
            "fill": face if filled else None,
            "fill_alpha": face_alpha if filled else 0.0,
            "stroke": edge,
            "stroke_alpha": edge_alpha,
            "stroke_half": self.canvas.stroke(float(patch.get_linewidth() or 0.0)),
        }
        closed = [(p, True) for p in polygons]
        self._add(kind, polygons, closed, style, self.canvas.clip(patch))

    def line(self, line: Any) -> None:
        if not line.get_visible():
            return
        if line.get_marker() not in _NO_MARKER:
            self.unparsed.append(
                {"artist": "Line2D", "reason": "line markers are not measured"}
            )
        if line.get_linestyle() in _NO_MARKER or line.get_linestyle() == "None":
            return
        if line.get_linestyle() not in ("-", "solid"):
            self.approximations.append("dashed lines are measured as solid")
        path = line.get_transform().transform_path(line.get_path())
        points = self.canvas.points(path.vertices)
        colour, alpha = _rgb(_to_rgba(line.get_color(), line.get_alpha()))
        style = {
            "fill": None,
            "fill_alpha": 0.0,
            "stroke": colour,
            "stroke_alpha": alpha,
            "stroke_half": self.canvas.stroke(float(line.get_linewidth() or 0.0)),
        }
        self._add("line", [], [(points, False)], style, self.canvas.clip(line))

    def collection(self, collection: Any) -> None:
        if not collection.get_visible():
            return
        from matplotlib.collections import LineCollection
        from matplotlib.transforms import Affine2D

        clip = self.canvas.clip(collection)
        faces = list(collection.get_facecolor())
        edges = list(collection.get_edgecolor())
        widths = list(collection.get_linewidth()) or [0.0]
        if isinstance(collection, LineCollection):
            transform = collection.get_transform()
            for i, segment in enumerate(collection.get_segments()):
                if len(segment) < 2:
                    continue
                points = self.canvas.points(transform.transform(segment))
                colour, alpha = (
                    _rgb(edges[i % len(edges)]) if edges else ((0, 0, 0), 0.0)
                )
                style = {
                    "fill": None,
                    "fill_alpha": 0.0,
                    "stroke": colour,
                    "stroke_alpha": alpha,
                    "stroke_half": self.canvas.stroke(float(widths[i % len(widths)])),
                }
                self._add("line_segment", [], [(points, False)], style, clip)
            return
        paths = list(collection.get_paths())
        if not paths:
            return
        per_item = list(collection.get_transforms())
        offsets = collection.get_offsets()
        offsets = [] if offsets is None else [tuple(o) for o in offsets]
        offset_transform = collection.get_offset_transform()
        master = collection.get_transform()
        count = max(len(paths), len(offsets))
        for i in range(count):
            path = paths[i % len(paths)]
            transform = master
            if per_item:
                transform = Affine2D(per_item[i % len(per_item)]) + master
            polygons_display = path.to_polygons(transform, closed_only=False)
            if offsets:
                ox, oy = offset_transform.transform(offsets[i % len(offsets)])
                polygons_display = [
                    [(x + ox, y + oy) for x, y in poly] for poly in polygons_display
                ]
            polygons = [self.canvas.points(poly) for poly in polygons_display]
            face, face_alpha = (
                _rgb(faces[i % len(faces)]) if faces else ((0, 0, 0), 0.0)
            )
            edge, edge_alpha = (
                _rgb(edges[i % len(edges)]) if edges else ((0, 0, 0), 0.0)
            )
            style = {
                "fill": face,
                "fill_alpha": face_alpha,
                "stroke": edge,
                "stroke_alpha": edge_alpha,
                "stroke_half": self.canvas.stroke(float(widths[i % len(widths)])),
            }
            self._add(
                type(collection).__name__,
                polygons,
                [(p, True) for p in polygons],
                style,
                clip,
            )

    def text(self, text: Any, where: str) -> None:
        if text.get_visible() and str(text.get_text()).strip():
            self.unparsed.append(
                {"artist": "Text", "reason": "text is not measured", "where": where}
            )

    def axis(self, axis: Any, name: str) -> None:
        if not axis.get_visible():
            return
        ticks = [*axis.get_major_ticks(), *axis.get_minor_ticks()]
        if any(
            t.get_visible() and (t.tick1line.get_visible() or t.tick2line.get_visible())
            for t in ticks
        ):
            self.unparsed.append(
                {"artist": f"{name}axis", "reason": "tick marks are not measured"}
            )
        if any(
            t.get_visible()
            and (
                (t.label1.get_visible() and str(t.label1.get_text()).strip())
                or (t.label2.get_visible() and str(t.label2.get_text()).strip())
            )
            for t in ticks
        ):
            self.unparsed.append(
                {"artist": f"{name}axis", "reason": "tick labels are not measured"}
            )
        self.text(axis.label, f"{name}axis label")
        if axis.get_offset_text().get_visible():
            self.text(axis.get_offset_text(), f"{name}axis offset")

    def axes(self, ax: Any) -> None:
        from matplotlib.axis import Axis
        from matplotlib.collections import Collection
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        from matplotlib.spines import Spine
        from matplotlib.text import Text

        if not ax.get_visible():
            return
        self.containers += len(getattr(ax, "containers", []))
        self.patch(ax.patch, "axes_background")
        for artist in ax.get_children():
            if artist is ax.patch:
                continue
            if isinstance(artist, Spine):
                if ax.axison:
                    self.patch(artist, "spine")
            elif isinstance(artist, Axis):
                if ax.axison:
                    self.axis(artist, str(getattr(artist, "axis_name", "")))
            elif isinstance(artist, Patch):
                self.patch(artist)
            elif isinstance(artist, Collection):
                self.collection(artist)
            elif isinstance(artist, Line2D):
                self.line(artist)
            elif isinstance(artist, Text):
                self.text(artist, "axes")
            elif artist.get_visible():
                self.unparsed.append(
                    {
                        "artist": type(artist).__name__,
                        "reason": "artist type is not measured",
                    }
                )

    def figure_level(self) -> None:
        from matplotlib.collections import Collection
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        from matplotlib.text import Text

        self.patch(self.figure.patch, "figure_background")
        for ax in self.figure.axes:
            self.axes(ax)
        for artist in self.figure.get_children():
            if artist is self.figure.patch or artist in self.figure.axes:
                continue
            if isinstance(artist, Patch):
                self.patch(artist)
            elif isinstance(artist, Collection):
                self.collection(artist)
            elif isinstance(artist, Line2D):
                self.line(artist)
            elif isinstance(artist, Text):
                self.text(artist, "figure")
            elif artist.get_visible():
                self.unparsed.append(
                    {
                        "artist": type(artist).__name__,
                        "reason": "artist type is not measured",
                    }
                )


def _to_rgba(colour: Any, alpha: float | None) -> Any:
    from matplotlib.colors import to_rgba

    return to_rgba(colour, alpha)


def parse_matplotlib_figure(
    figure: Any,
    *,
    raster_size: tuple[int, int] | None = None,
    config: SegmenterConfig | None = None,
) -> VectorParse:
    """Parse a matplotlib Figure into CL-39 records on the raster grid.

    The figure is drawn (Agg) first so transforms are final.
    `raster_size` is the rendered raster's (width, height) when it
    was saved at a different dpi than the figure's own.
    """
    _require_matplotlib()
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    base = config or SegmenterConfig()
    active = SegmenterConfig(
        **{**base.__dict__, "name": MPL_PARSER_NAME, "version": MPL_PARSER_VERSION}
    )
    if not isinstance(figure, Figure):
        return VectorParse(
            SegmentationResult(
                "corrupt_source", detail="not a matplotlib Figure", config=active
            ),
            limitations=MPL_LIMITATIONS,
        )
    if not hasattr(figure.canvas, "get_renderer"):
        FigureCanvasAgg(figure)
    try:
        figure.canvas.draw()
        canvas = _Canvas(figure, raster_size)
        walker = _Walker(figure, canvas)
        walker.figure_level()
    except (ValueError, TypeError, OverflowError) as exc:
        return VectorParse(
            SegmentationResult(
                "corrupt_source", detail=f"figure not measurable: {exc}", config=active
            ),
            limitations=MPL_LIMITATIONS,
        )

    def colour_of(shape: Shape, style: dict[str, Any], bg: Colour) -> Colour | None:
        if style.get("fill") is not None and style.get("fill_alpha", 0.0) > 0:
            return composite(style["fill"], style["fill_alpha"], bg)
        if style.get("stroke_alpha", 0.0) > 0 and style.get("stroke_half", 0.0) > 0:
            return composite(style["stroke"], style["stroke_alpha"], bg)
        return None

    try:
        raw, background, panels = measure_shapes(
            walker.shapes, canvas.size, (255, 255, 255), active, colour_of=colour_of
        )
    except MeasureLimitExceeded as exc:
        return VectorParse(
            SegmentationResult("limit_exceeded", detail=str(exc), config=active),
            limitations=MPL_LIMITATIONS,
        )
    return build_vector_result(
        raw,
        canvas.size,
        active,
        media_kind="matplotlib",
        unparsed=walker.unparsed,
        approximations=walker.approximations,
        background=background,
        panels=panels,
        shapes=len(walker.shapes),
        limitations=MPL_LIMITATIONS,
    )
