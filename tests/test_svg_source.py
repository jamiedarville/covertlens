"""CL-69: SVG vector-source parser and its rendered-raster binding."""

import json
from pathlib import Path

import jsonschema
import pytest

from covertlens import ids
from covertlens.geometric_fixtures import SUBFAMILIES, build_geo_pair
from covertlens.segmentation import SegmenterConfig, segment_image
from covertlens.store import ArtifactStore
from covertlens.svg_source import (
    MAX_SVG_ELEMENTS,
    SVG_PARSER_NAME,
    parse_colour,
    parse_path_data,
    parse_svg_source,
    svg_from_fixture,
)
from covertlens.vector_source import (
    analyze_rendered_with_source,
    validate_vector_binding,
)

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schemas/vector-binding.schema.json").read_text()
)
TOLERANCE = SegmenterConfig()
SVG_HEAD = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'


def _svg(body: bytes, head: bytes = SVG_HEAD) -> bytes:
    return head + body + b"</svg>"


def _boxes(parse):
    return [
        (e["left"], e["top"], e["width"], e["height"]) for e in parse.result.elements
    ]


@pytest.mark.parametrize("subfamily", SUBFAMILIES)
def test_svg_source_matches_raster_segmentation(subfamily):
    """Acceptance: an SVG parses to the raster's attribute sequences."""
    for fixture in build_geo_pair(subfamily):
        raster = segment_image(fixture.data)
        parse = parse_svg_source(
            svg_from_fixture(fixture), raster_size=(fixture.width, fixture.height)
        )
        assert parse.fully_parsed
        assert parse.result.status == raster.status == "ok"
        assert len(parse.result.elements) == len(raster.elements)
        tilted = subfamily == "angle_tilt"
        # Tilted bars: the raster's 3x3 morphology trims stair-stepped
        # corners, so boxes move by a few pixels; the angle channel is
        # what CL-40 scores and it stays inside the angle tolerance.
        box_tolerance = 3 if tilted else 0
        for r, v in zip(raster.elements, parse.result.elements):
            for key in ("left", "top", "width", "height"):
                assert abs(r[key] - v[key]) <= box_tolerance, (key, r, v)
            if r["gap_to_next"] is not None:
                assert abs(r["gap_to_next"] - v["gap_to_next"]) <= box_tolerance
            assert abs(r["angle_deg"] - v["angle_deg"]) <= TOLERANCE.angle_tolerance_deg
            assert r["colour_index"] == v["colour_index"]
            assert r["brightness"] == v["brightness"]


def test_svg_shapes_transforms_use_and_viewbox():
    doc = _svg(
        b'<defs><rect id="bar" width="10" height="20" fill="#336"/></defs>'
        b'<use href="#bar" x="5" y="10"/>'
        b'<use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#bar" x="20" y="10"/>'
        b'<circle cx="45" cy="20" r="8" fill="rgb(200,0,0)"/>'
        b'<ellipse cx="65" cy="20" rx="6" ry="9" fill="olive"/>'
        b'<g transform="translate(80 5)" opacity="0.5">'
        b'<rect width="6" height="30" fill="navy" transform="rotate(10 3 30)"/></g>'
        b'<polygon points="95,40 105,40 100,10" fill="#0a0"/>'
    )
    parse = parse_svg_source(doc)
    assert parse.fully_parsed
    boxes = _boxes(parse)
    assert boxes[:2] == [(5, 10, 10, 20), (20, 10, 10, 20)]  # <use> offsets
    assert boxes[2] == (37, 12, 16, 16)  # circle r=8 on pixel centres
    assert parse.result.elements[4]["angle_deg"] == pytest.approx(10.0, abs=1.5)
    # Group opacity composites over the (white) background.
    navy_half = parse.result.elements[4]["colour"]
    assert navy_half == [128, 128, 192]


def test_viewbox_maps_onto_the_raster_size():
    doc = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="60pt" height="30pt" '
        b'viewBox="0 0 60 30">'
        b'<rect x="10" y="5" width="10" height="20" fill="#000"/>'
        b'<rect x="25" y="5" width="10" height="20" fill="#000"/>'
        b'<rect x="40" y="5" width="10" height="20" fill="#000"/></svg>'
    )
    at_points = parse_svg_source(doc)  # 60pt = 80 CSS px
    assert (at_points.result.width, at_points.result.height) == (80, 40)
    doubled = parse_svg_source(doc, raster_size=(120, 60))
    assert _boxes(doubled)[0] == (20, 10, 20, 40)


def test_path_data_commands_and_packed_arc_flags():
    subpaths = parse_path_data("M10 40 a10 10 0 01 20 0 z M40 40 h10 v-10 H40 Z")
    assert len(subpaths) == 2 and all(closed for _pts, closed in subpaths)
    xs = [x for x, _y in subpaths[0][0]]
    assert min(xs) == pytest.approx(10) and max(xs) == pytest.approx(30)
    curves = parse_path_data(
        "M0 0 C 10 0 10 10 0 10 S -10 20 0 20 Q 5 25 10 20 T 20 20"
    )
    assert curves[0][0][-1] == pytest.approx((20, 20))
    with pytest.raises(ValueError):
        parse_path_data("L 1 1")


def test_colour_forms():
    assert parse_colour("#abc") == (170, 187, 204)
    assert parse_colour("#427dad") == (66, 125, 173)
    assert parse_colour("rgb(100%, 0%, 50%)") == (255, 0, 128)
    assert parse_colour("none") is None
    assert parse_colour("url(#g1)") == ("url", "g1")
    with pytest.raises(ValueError):
        parse_colour("not-a-colour")


def test_background_panels_and_invisible_shapes_are_not_elements():
    doc = _svg(
        b'<rect width="120" height="60" fill="#f5f7fa"/>'
        b'<rect x="10" y="10" width="8" height="30" fill="#f5f7fa"/>'  # invisible
        b'<rect x="30" y="10" width="8" height="30" fill="#123" display="none"/>'
        b'<rect x="50" y="10" width="8" height="30" fill="#123" visibility="hidden"/>'
        b'<rect x="70" y="10" width="8" height="30" fill="#123" fill-opacity="0"/>'
        b'<rect x="90" y="10" width="8" height="30" fill="#123"/>'
        b'<rect x="100" y="10" width="2" height="2" fill="#123"/>'  # under 8 px
    )
    parse = parse_svg_source(doc)
    assert parse.background == (245, 247, 250)
    assert parse.panels == 1
    assert _boxes(parse) == [(90, 10, 8, 30)]
    assert parse.result.status == "too_few_elements"


def test_clip_path_limits_the_measured_box():
    doc = _svg(
        b'<defs><clipPath id="c"><rect x="0" y="20" width="120" height="40"/></clipPath></defs>'
        b'<rect x="10" y="0" width="10" height="60" fill="#000" clip-path="url(#c)"/>'
        b'<rect x="30" y="0" width="10" height="60" fill="#000" clip-path="url(#c)"/>'
        b'<rect x="50" y="0" width="10" height="60" fill="#000" clip-path="url(#c)"/>'
    )
    assert _boxes(parse_svg_source(doc))[0] == (10, 20, 10, 40)


@pytest.mark.parametrize(
    "body, element",
    [
        (b'<text x="4" y="12">hi</text>', "text"),
        (b'<image href="data:image/png;base64,AAAA" width="9" height="9"/>', "image"),
        (
            b"<foreignObject width='9' height='9'><p>x</p></foreignObject>",
            "foreignObject",
        ),
        (b"<style>.a{fill:red}</style>", "style"),
        (b'<rect width="9" height="9" filter="url(#f)"/>', "rect"),
    ],
)
def test_unmeasurable_content_is_listed_never_silently_dropped(body, element):
    bars = b"".join(
        b'<rect x="%d" y="10" width="8" height="30" fill="#123"/>' % (10 + 20 * i)
        for i in range(4)
    )
    parse = parse_svg_source(_svg(bars + body))
    assert not parse.fully_parsed
    assert parse.unparsed[0]["element"] == element


def test_harmless_stylesheet_rules_pass():
    css = b"<style>*{stroke-linejoin: round; stroke-linecap: butt}</style>"
    bars = b"".join(
        b'<rect x="%d" y="10" width="8" height="30" fill="#123"/>' % (10 + 20 * i)
        for i in range(4)
    )
    assert parse_svg_source(_svg(css + bars)).fully_parsed


@pytest.mark.parametrize(
    "doc, status",
    [
        (
            b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aa"><!ENTITY b "&a;&a;">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg">&b;</svg>',
            "corrupt_source",
        ),
        (
            b"<!DOCTYPE svg [ ]><svg xmlns='http://www.w3.org/2000/svg'/>",
            "corrupt_source",
        ),
        (b"<html/>", "corrupt_source"),
        (b"<svg", "corrupt_source"),
        (_svg(b'<path d="M 1 1 L x"/>'), "corrupt_source"),
        (_svg(b'<rect width="9" height="9" fill="nope"/>'), "corrupt_source"),
        (_svg(b"<g/>" * (MAX_SVG_ELEMENTS + 1)), "limit_exceeded"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "corrupt_source"),  # no size
        (
            b"<svg xmlns='http://www.w3.org/2000/svg' width='4000' height='4000'>"
            b"<rect width='9' height='9'/></svg>",
            "limit_exceeded",
        ),
        (
            b"<svg xmlns='http://www.w3.org/2000/svg' width='1400' height='1400'>"
            + (
                b"<polygon points='"
                + b" ".join(b"%d,%d" % (i % 9, i) for i in range(1400))
                + b"'/>"
            )
            * 40
            + b"</svg>",
            "limit_exceeded",
        ),
    ],
)
def test_bombs_and_garbage_fail_closed(doc, status):
    parse = parse_svg_source(doc)
    assert parse.result.status == status
    assert parse.result.elements == []


def test_bare_public_doctype_is_accepted():
    doc = (
        b'<?xml version="1.0"?>\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"\n'
        b'  "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
        + _svg(
            b"".join(
                b'<rect x="%d" y="10" width="8" height="30"/>' % (10 + 20 * i)
                for i in range(3)
            )
        )
    )
    assert parse_svg_source(doc).result.status == "ok"


# -- binding (C-10, lineage) -------------------------------------------------


def _encoded():
    return next(f for f in build_geo_pair("height_position") if f.role == "encoded")


def test_binding_scores_the_raster_and_records_svg_lineage():
    fixture = _encoded()
    svg = svg_from_fixture(fixture)
    store = ArtifactStore()
    report = analyze_rendered_with_source(
        fixture.data, svg, source_kind="svg", store=store
    )
    assert validate_vector_binding(report) == []
    jsonschema.validate(report, SCHEMA)
    assert report["bound_content_hash"] == ids.content_hash(fixture.data)
    assert report["vector_status"] == "ok"
    assert report["vector_parser"]["name"] == SVG_PARSER_NAME
    assert report["vector_parse"]["fully_parsed"] is True
    lineage = report["lineage"]
    assert lineage["relation"] == "rendered_from_vector_source"
    assert lineage["source_content_hash"] == ids.content_hash(svg)
    assert lineage["lineage_parent"] == lineage["rendered_version_id"]
    assert report["vector_classification"] == report["raster_classification"]


def test_unintercepted_partial_and_corrupt_sources_never_clear():
    fixture = _encoded()
    svg = svg_from_fixture(fixture)
    unintercepted = analyze_rendered_with_source(
        fixture.data, svg, source_kind="svg", source_intercepted=False
    )
    assert unintercepted["clearance"] == "refused_unparsed_vector_source"
    partial = analyze_rendered_with_source(
        fixture.data,
        svg.replace(b"</svg>", b'<text x="4" y="12">x</text></svg>'),
        source_kind="svg",
    )
    assert partial["clearance"] == "refused_partially_parsed_vector_source"
    assert partial["cleared"] is False
    corrupt = analyze_rendered_with_source(fixture.data, b"<svg", source_kind="svg")
    assert corrupt["clearance"] == "refused_unparseable_vector_source"
    for report in (unintercepted, partial, corrupt):
        assert report["cleared"] is False
        assert validate_vector_binding(report) == []
        jsonschema.validate(report, SCHEMA)


def test_raster_fallback_and_unknown_kind():
    fixture = _encoded()
    assert (
        analyze_rendered_with_source(fixture.data, None)["vector_status"]
        == "absent_raster_fallback"
    )
    with pytest.raises(ValueError):
        analyze_rendered_with_source(fixture.data, b"x", source_kind="pdf")
