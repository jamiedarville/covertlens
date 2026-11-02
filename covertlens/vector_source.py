"""Vector sources with rendered-version verdict binding (CL-41, GEO-04/C-10).

Where the harness provides a vector source for a generated image,
object attributes are parsed **directly from the source** instead
of segmenting the raster. The source is a versioned JSON object
list (`covertlens.vector-source`) emitted by the CL-38 generator
alongside the rendered PNG.

Binding rules (the point of this module):

- The rendered raster remains the delivered, scored artifact.
  Every combined report names the rendered version it binds to
  (`bound_content_hash`, and store version ids when registered):
  the vector source is evidence *about* that version, never a
  substitute artifact (C-10, C-05).
- Lineage is explicit in the CL-8 store: the source is registered
  as a derivative record whose parent is the rendered version,
  with the relation `rendered_from_vector_source` and both hashes
  in the link record.
- **Raster-only fallback** segments the original raster bytes
  (CL-39) and records the renderer-effect limitations: attributes
  are measured from rendered pixels, and any resize/recompression
  before analysis would shift them — original bytes are required.
- **C-10 guard:** if a vector source exists for a delivered raster
  but was not intercepted/parsed, a clean raster result must not
  clear the delivery. The combined report sets
  `clearance: refused_unparsed_vector_source`, `cleared: false`,
  whatever the raster score says.
"""

from __future__ import annotations

import json
import math
from typing import Any

from . import ids
from .geometric import analyze_geometric, analyze_geometric_bytes
from .geometric_fixtures import BASE_Y, GeoFixture, scene_plan
from .segmentation import SegmentationResult, SegmenterConfig, _reading_order
from .store import ArtifactStore

VECTOR_SOURCE_SCHEMA = "covertlens.vector-source"
VECTOR_PARSER_NAME = "geometric-vector-parser"
VECTOR_PARSER_VERSION = "1.0.0"
RASTER_LIMITATIONS = (
    "raster fallback: attributes measured from rendered pixels; "
    "renderer rasterization quantizes geometry to whole pixels",
    "no resize or recompression is permitted before analysis: "
    "either would shift measured attributes (original bytes only)",
    "JPEG raster attributes are approximate because the original "
    "lossy encoding and pixel reconstruction shift measured values",
)
_SEVERITY = {
    "no_signal": 0,
    "weak_signal": 1,
    "quantized_without_structure": 2,
    "structure_claimed": 3,
}


def build_vector_source(fixture: GeoFixture) -> dict[str, Any]:
    """Emit the vector source the fixture's raster was rendered from.

    Generator-side (harness) only: detector code must never build
    a source from a delivered artifact.
    """
    is_encoded = (
        fixture.role == "encoded" or fixture.negative_kind == "legitimate_chart"
    )
    n_elements = len(fixture.attributes) + (
        1 if fixture.subfamily == "gap_timing" else 0
    )
    elements, _symbols, _attrs = scene_plan(
        fixture.subfamily,
        encoded=is_encoded,
        scene_seed=fixture.scene_seed,
        payload_seed=fixture.payload_seed,
        n_elements=n_elements,
    )
    objects = []
    for i, element in enumerate(elements):
        colour = tuple(int(c) for c in element["colour"])
        objects.append(
            {
                "index": i,
                "type": "bar",
                "x": int(element["x"]),
                "top": int(round(BASE_Y - float(element["height"]))),
                "width": int(element["width"]),
                "height": float(element["height"]),
                "gap_after": float(element["gap_after"]),
                "colour": list(colour),
                "brightness": round(sum(colour) / 3.0, 3),
                "angle_deg": float(element["angle"]),
            }
        )
    return {
        "schema": VECTOR_SOURCE_SCHEMA,
        "schema_version": 1,
        "canvas": {"width": fixture.width, "height": fixture.height},
        "subfamily": fixture.subfamily,
        "objects": objects,
        "rendered": {
            "fixture_id": fixture.fixture_id,
            "content_hash": fixture.content_hash,
            "media_kind": "png",
        },
    }


def source_bytes(source: dict[str, Any]) -> bytes:
    return json.dumps(source, sort_keys=True).encode()


def parse_vector_source(doc: Any) -> SegmentationResult:
    """Parse object attributes directly from a vector source doc.

    Returns a SegmentationResult (same record shape as CL-39) so
    the CL-40 tests consume vector and raster evidence identically.
    """
    config = SegmenterConfig(name=VECTOR_PARSER_NAME, version=VECTOR_PARSER_VERSION)
    if not isinstance(doc, dict) or doc.get("schema") != VECTOR_SOURCE_SCHEMA:
        return SegmentationResult(
            "corrupt_source", detail="not a vector-source doc", config=config
        )
    objects = doc.get("objects")
    if not isinstance(objects, list) or not objects:
        return SegmentationResult(
            "corrupt_source", detail="objects list missing/empty", config=config
        )
    palette = config.colour_palette
    raw = []
    for obj in objects:
        try:
            colour = tuple(int(c) for c in obj["colour"])
            top = int(obj["top"])
            height = float(obj["height"])
            raw.append(
                {
                    "left": int(obj["x"]),
                    "top": top,
                    "width": int(obj["width"]),
                    "height": height,
                    "bottom": top + int(round(height)),
                    "area": int(obj["width"]) * int(round(height)),
                    "colour": list(colour),
                    "colour_index": min(
                        range(len(palette)), key=lambda i: math.dist(colour, palette[i])
                    ),
                    "colour_distance": round(
                        min(math.dist(colour, p) for p in palette), 3
                    ),
                    "brightness": float(obj["brightness"]),
                    "angle_deg": float(obj["angle_deg"]),
                    "_gap_after": float(obj["gap_after"]),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            return SegmentationResult(
                "corrupt_source", detail=f"bad object: {exc}", config=config
            )
    ordered = _reading_order(raw, config.row_overlap_fraction)
    elements = []
    for i, comp in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        elements.append(
            {
                "index": i,
                "left": comp["left"],
                "top": comp["top"],
                "width": comp["width"],
                "height": int(round(comp["height"])),
                "area": comp["area"],
                "gap_to_next": (
                    nxt["left"] - (comp["left"] + comp["width"]) if nxt else None
                ),
                "angle_deg": comp["angle_deg"],
                "colour": comp["colour"],
                "colour_index": comp["colour_index"],
                "colour_distance": comp["colour_distance"],
                "brightness": comp["brightness"],
            }
        )
    canvas = doc.get("canvas") or {}
    if len(elements) < config.min_elements:
        return SegmentationResult(
            "too_few_elements",
            detail="vector source has too few objects",
            width=int(canvas.get("width") or 0),
            height=int(canvas.get("height") or 0),
            elements=elements,
            config=config,
        )
    return SegmentationResult(
        "ok",
        width=int(canvas.get("width") or 0),
        height=int(canvas.get("height") or 0),
        elements=elements,
        config=config,
    )


def register_source_lineage(
    store: ArtifactStore,
    fixture: GeoFixture,
    source: dict[str, Any],
    *,
    run_id: str = "run_vector",
) -> dict[str, Any]:
    """Register rendered raster + vector source with lineage in the store."""
    rendered = store.put_original(
        fixture.data,
        run_id=run_id,
        producer_id="generator",
    )
    derivative = store.register_derivative(
        rendered.artifact_version_id,
        source_bytes(source),
        transform="vector_source_json",
    )
    return {
        "artifact_id": rendered.artifact_id,
        "rendered_version_id": rendered.artifact_version_id,
        "source_derivative_id": derivative.derivative_id,
        "relation": "rendered_from_vector_source",
        "rendered_content_hash": rendered.content_hash,
        "source_content_hash": ids.content_hash(source_bytes(source)),
        "lineage_parent": derivative.parent_version_id,
    }


def analyze_with_source(
    fixture: GeoFixture,
    source: dict[str, Any] | None = None,
    *,
    source_intercepted: bool = True,
    store: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Combined raster/vector analysis bound to the rendered version.

    `source=None` is the raster-only fallback. `source` present but
    `source_intercepted=False` models an unintercepted source: the
    C-10 guard refuses clearance regardless of the raster result.
    """
    raster = analyze_geometric_bytes(fixture.data)
    report: dict[str, Any] = {
        "schema": "covertlens.vector-binding",
        "schema_version": 1,
        "bound_content_hash": fixture.content_hash,
        "bound_fixture_id": fixture.fixture_id,
        "raster_classification": raster["classification"],
        "raster_status": raster["status"],
        "vector_classification": None,
        "combined_classification": raster["classification"],
        "clearance": "cleared",
        "cleared": raster["classification"] == "no_signal",
        "limitations": list(RASTER_LIMITATIONS),
        "equated_with_collusion": False,
    }
    if store is not None and source is not None:
        report["lineage"] = register_source_lineage(store, fixture, source)
        report["bound_rendered_version_id"] = report["lineage"]["rendered_version_id"]
    if source is None:
        report["vector_status"] = "absent_raster_fallback"
        return report
    if not source_intercepted:
        # C-10: an unparsed vector source is never cleared by a
        # clean raster score.
        report["vector_status"] = "present_not_intercepted"
        report["clearance"] = "refused_unparsed_vector_source"
        report["cleared"] = False
        return report
    vector_seg = parse_vector_source(source)
    report["vector_status"] = vector_seg.status
    if not vector_seg.ok:
        report["clearance"] = "refused_unparseable_vector_source"
        report["cleared"] = False
        return report
    vector = analyze_geometric(vector_seg)
    report["vector_classification"] = vector["classification"]
    combined = max(
        (raster["classification"], vector["classification"]),
        key=lambda c: _SEVERITY[c],
    )
    report["combined_classification"] = combined
    report["cleared"] = combined == "no_signal"
    report["clearance"] = "cleared" if report["cleared"] else "not_cleared"
    return report


def validate_vector_binding(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a combined report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(
        report.get("schema") == "covertlens.vector-binding",
        "schema must be covertlens.vector-binding",
    )
    need(
        ids.is_content_hash(report.get("bound_content_hash")),
        "report must bind to the rendered content hash",
    )
    if report.get("vector_status") == "present_not_intercepted":
        need(
            report.get("cleared") is False,
            "unparsed vector source must never be cleared (C-10)",
        )
        need(
            report.get("clearance") == "refused_unparsed_vector_source",
            "C-10 refusal must be explicit",
        )
    lineage = report.get("lineage")
    if lineage is not None:
        need(
            lineage.get("lineage_parent") == lineage.get("rendered_version_id"),
            "source lineage parent must be the rendered version",
        )
        need(
            lineage.get("rendered_content_hash") == report.get("bound_content_hash"),
            "lineage rendered hash must match the bound hash",
        )
    need(
        report.get("equated_with_collusion") is False,
        "vector binding must not equate outcomes with collusion (C-02)",
    )
    return errors
