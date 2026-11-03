"""CL-69: matplotlib figure adapter (optional `matplotlib` extra)."""

import io
import json
from pathlib import Path

import jsonschema
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from covertlens.mpl_source import MPL_PARSER_NAME, parse_matplotlib_figure  # noqa: E402
from covertlens.segmentation import segment_image  # noqa: E402
from covertlens.store import ArtifactStore  # noqa: E402
from covertlens.svg_source import parse_svg_source  # noqa: E402
from covertlens.vector_source import (  # noqa: E402
    analyze_rendered_with_source,
    validate_vector_binding,
)

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schemas/vector-binding.schema.json").read_text()
)
KEYS = ("left", "top", "width", "height", "gap_to_next", "colour_index", "brightness")


def _bar_chart(heights, colours="#427dad", dpi=100):
    fig = plt.figure(figsize=(6.4, 2.4), dpi=dpi, facecolor="#f5f7fa")
    ax = fig.add_axes((0, 0, 1, 1), facecolor="#f5f7fa")
    ax.bar(range(len(heights)), heights, width=0.55, color=colours)
    ax.set(xlim=(-1, len(heights)), ylim=(-12, max(heights) * 1.15))
    ax.set_axis_off()
    return fig


def _save(fig, fmt, **kwargs):
    buffer = io.BytesIO()
    fig.savefig(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "heights, colours",
    [
        ([36, 73, 48, 92, 64, 110, 83, 52], "#427dad"),
        # Heights on a 10-unit grid, colours from the declared palette.
        (
            [20, 50, 30, 70, 40, 90, 60, 20, 80, 50],
            ["#c83c32", "#3caa46", "#3c5ac8", "#c83c32", "#3caa46"] * 2,
        ),
    ],
)
def test_svg_and_figure_match_segmenting_their_png(heights, colours):
    """Acceptance: SVG export and the figure object both parse to the
    attribute sequences segmentation measures on the rendered PNG."""
    fig = _bar_chart(heights, colours)
    png = _save(fig, "png", dpi=100)
    svg = _save(fig, "svg")
    raster = segment_image(png)
    size = (raster.width, raster.height)
    svg_parse = parse_svg_source(svg, raster_size=size)
    fig_parse = parse_matplotlib_figure(fig, raster_size=size)
    plt.close(fig)
    assert raster.status == "ok" and len(raster.elements) == len(heights)
    for parse in (svg_parse, fig_parse):
        assert parse.fully_parsed, parse.unparsed
        assert len(parse.result.elements) == len(raster.elements)
        for r, v in zip(raster.elements, parse.result.elements):
            for key in KEYS:
                if r[key] is None:
                    assert v[key] is None
                else:
                    assert abs(r[key] - v[key]) <= 1.6, (key, r, v)


def test_raster_saved_at_another_dpi_maps_through_raster_size():
    fig = _bar_chart([30, 60, 45, 90])
    png = _save(fig, "png", dpi=150)
    raster = segment_image(png)
    parse = parse_matplotlib_figure(fig, raster_size=(raster.width, raster.height))
    plt.close(fig)
    assert (raster.width, raster.height) == (960, 360)
    assert [e["height"] for e in parse.result.elements] == pytest.approx(
        [e["height"] for e in raster.elements], abs=1.6
    )


def test_collections_and_lines_are_measured():
    fig = plt.figure(figsize=(4, 2), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_axis_off()
    ax.set(xlim=(0, 10), ylim=(0, 10))
    ax.vlines([1, 3, 5, 7], 1, [4, 6, 8, 5], linewidth=6, color="#222")
    ax.fill_between([8, 9], [1, 1], [7, 7], color="#a33")
    ax.plot([0.5, 9.5], [9, 9], linewidth=3, color="#33a")
    parse = parse_matplotlib_figure(fig)
    plt.close(fig)
    assert parse.fully_parsed
    kinds = [e["source_kind"] for e in parse.result.elements]
    assert kinds.count("line_segment") == 4
    assert "PolyCollection" in kinds or "FillBetweenPolyCollection" in kinds
    assert "line" in kinds


def test_axes_text_ticks_and_markers_are_listed_as_unparsed():
    fig, ax = plt.subplots(figsize=(4, 3), dpi=80)
    ax.bar(["a", "b", "c", "d"], [3, 5, 2, 4])
    ax.set_title("title")
    ax.plot([0, 3], [1, 4], marker="o")
    parse = parse_matplotlib_figure(fig)
    png = _save(fig, "png")
    plt.close(fig)
    reasons = {item["reason"] for item in parse.unparsed}
    assert "tick labels are not measured" in reasons
    assert "text is not measured" in reasons
    assert "line markers are not measured" in reasons
    assert not parse.fully_parsed
    report = analyze_rendered_with_source(png, fig, source_kind="matplotlib")
    assert report["clearance"] == "refused_partially_parsed_vector_source"
    assert report["cleared"] is False


def test_figure_binding_needs_an_explicit_source_record_for_lineage():
    fig = _bar_chart([20, 40, 60, 30])
    png = _save(fig, "png", dpi=100)
    store = ArtifactStore()
    with pytest.raises(ValueError, match="source_record"):
        analyze_rendered_with_source(png, fig, source_kind="matplotlib", store=store)
    code = b"ax.bar(range(4), [20, 40, 60, 30])"
    report = analyze_rendered_with_source(
        png, fig, source_kind="matplotlib", store=store, source_record=code
    )
    plt.close(fig)
    assert validate_vector_binding(report) == []
    jsonschema.validate(report, SCHEMA)
    assert report["vector_parser"]["name"] == MPL_PARSER_NAME
    assert report["lineage"]["source_kind"] == "matplotlib"


def test_not_a_figure_is_corrupt():
    parse = parse_matplotlib_figure(object())
    assert parse.result.status == "corrupt_source"
