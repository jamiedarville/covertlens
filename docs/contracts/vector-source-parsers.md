# Vector-source parsers for SVG and matplotlib figures (CL-69)

Implements: CL-69 (GEO-04, C-10). Extends
[vector-source.md](vector-source.md) (CL-41). Schema:
[schemas/vector-binding.schema.json](../../schemas/vector-binding.schema.json).

## Why

CL-41 parses only the project's own `covertlens.vector-source` JSON
object list. In an agent harness the vector source of a generated
chart is usually an SVG or plotting code. CL-69 adds two parsers that
produce the CL-39 record shape, so CL-40 scores vector and raster
evidence identically.

## Parsers

| Source | Module | Parser name |
|---|---|---|
| SVG bytes | `covertlens.svg_source.parse_svg_source` | `geometric-svg-parser` 1.0.0 |
| `matplotlib.figure.Figure` | `covertlens.mpl_source.parse_matplotlib_figure` | `geometric-matplotlib-adapter` 1.0.0 |

Both reduce every drawable to polygons in the rendered raster's pixel
coordinates and measure them with `covertlens._shapes`, using the
CL-39 definitions: a pixel counts when its centre is inside the
shape; bbox, area and gap are pixel counts; tilt is the row-centroid
regression; colour is the painted colour (opacity composited over the
background) with the nearest declared-palette index. Shapes covering
at least half the canvas are background panels. Shapes painted in the
background colour, or smaller than `min_component_pixels`, are
invisible in the raster and are dropped exactly as segmentation drops
them.

- **SVG** (`xml.etree`, standard library): `rect` (incl. rounded
  corners), `circle`, `ellipse`, `line`, `polyline`, `polygon`, `path`
  (M/L/H/V/C/S/Q/T/A/Z, absolute and relative, packed arc flags;
  curves and arcs flattened), `fill`/`stroke`/opacities/`display`/
  `visibility` from attributes, inline style or groups, CSS colour
  forms, every `transform` function, `<use>` (depth 8), `clip-path`
  (as the clip's bounding box), and the root `viewBox` mapped onto the
  rendered raster size (`raster_size`), honouring
  `preserveAspectRatio`.
- **matplotlib** (optional extra, `pip install
  'covertlens[matplotlib]'`): the figure is drawn with Agg first, then
  patches (every bar of a `BarContainer`), `LineCollection` segments,
  path collections (`PolyCollection`, `PatchCollection`,
  `PathCollection` with per-item transforms and offsets, in
  matplotlib's draw order), marker-free `Line2D` lines and visible
  spines are measured in display space and mapped onto the raster.

## Fail-closed rules (C-10)

- **Partially parsed sources never clear.** Visible content a parser
  cannot measure is listed in `vector_parse.unparsed`: SVG `text`,
  `image`, `foreignObject`, pattern fills, filters, masks, nested
  viewports and stylesheet rules that could restyle elements;
  matplotlib text, tick marks and labels, line markers, images,
  legends and unknown artists. The binding report then sets
  `clearance: refused_partially_parsed_vector_source`,
  `cleared: false`. Stylesheet rules that cannot change geometry or
  colour (matplotlib's `stroke-linejoin`/`stroke-linecap` default)
  pass.
- **Bombs and garbage are corrupt, not empty.** Entity declarations
  and DOCTYPE internal subsets are refused before parsing (a bare
  public DOCTYPE, as matplotlib writes, is accepted: ElementTree never
  fetches external DTDs). Bad lengths, colours, transforms or path
  data, a non-`<svg>` root, or no usable size return `corrupt_source`.
  Over 10 MiB, 20,000 elements, 400,000 path points or a 16,384 px
  side return `limit_exceeded`. Both refuse clearance
  (`refused_unparseable_vector_source`).
- **CL-41 rules unchanged.** The rendered raster stays the delivered,
  scored artifact: the report binds to the raster's content hash, and
  in the store the source is a derivative of the rendered version with
  `relation: rendered_from_vector_source` (`source_kind` recorded). An
  unintercepted source is `refused_unparsed_vector_source` whatever
  the raster says. A matplotlib figure is not bytes, so registering it
  needs an explicit `source_record` (the plotting code or its SVG
  export).

Approximations are recorded, not hidden: gradient fills use the mean
stop colour, non-rect clip paths their bounding box, hatching a plain
fill, dashes a solid stroke. Objects are measured one by one, so
touching objects the raster segmenter would fuse stay separate
records (listed in each parser's limitations).

## Entry point

`covertlens.vector_source.analyze_rendered_with_source(rendered,
source, source_kind="svg" | "matplotlib" | "covertlens.vector-source",
...)` returns the CL-41 binding report with `vector_source_kind`,
`vector_parser` and (SVG/matplotlib) `vector_parse`. CL-41's
`analyze_with_source(fixture, json_source)` is the JSON path of the
same function and its output is unchanged.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| An SVG and a matplotlib bar chart parse to the same attribute sequences as segmenting their rendered PNGs, within tolerance | `tests/test_mpl_source.py::test_svg_and_figure_match_segmenting_their_png` (SVG export and figure object vs `segment_image` of the PNG, every attribute within 1.6 px; measured: exact on both charts), `tests/test_svg_source.py::test_svg_source_matches_raster_segmentation` (all five CL-38 subfamilies; exact except tilted bars, whose boxes differ by up to 3 px after raster morphology while the angle stays within 3.5 degrees) |
| Lineage and C-10 rules exactly as CL-41 | `test_binding_scores_the_raster_and_records_svg_lineage`, `test_unintercepted_partial_and_corrupt_sources_never_clear`, `test_figure_binding_needs_an_explicit_source_record_for_lineage` |

## Verification

`python -m covertlens svg-source-demo` prints an SVG parse of a CL-38
fixture, its binding report and the partial-parse refusal.
