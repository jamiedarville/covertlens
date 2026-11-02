import pytest

from covertlens.geometric_fixtures import build_geo_dataset
from covertlens.store import ArtifactStore
from covertlens.vector_source import (
    analyze_with_source,
    build_vector_source,
    parse_vector_source,
    validate_vector_binding,
)


@pytest.fixture(scope="module")
def dataset():
    return build_geo_dataset()


def _one(dataset, subfamily, role):
    return next(f for f in dataset if f.subfamily == subfamily and f.role == role)


def test_vector_parse_reads_attributes_directly_in_reading_order(dataset):
    fixture = _one(dataset, "height_position", "encoded")
    source = build_vector_source(fixture)
    assert source["rendered"]["content_hash"] == fixture.content_hash
    seg = parse_vector_source(source)
    assert seg.ok
    assert seg.config.name == "geometric-vector-parser"
    lefts = [e["left"] for e in seg.elements]
    assert lefts == sorted(lefts)
    # Vector heights are exact (no raster quantization noise).
    assert all(isinstance(h, int) for h in seg.sequence("height"))


def test_lineage_links_source_to_rendered_version(dataset):
    fixture = _one(dataset, "gap_timing", "encoded")
    store = ArtifactStore()
    report = analyze_with_source(fixture, build_vector_source(fixture), store=store)
    assert validate_vector_binding(report) == []
    lineage = report["lineage"]
    assert lineage["relation"] == "rendered_from_vector_source"
    assert lineage["lineage_parent"] == lineage["rendered_version_id"]
    assert lineage["rendered_content_hash"] == fixture.content_hash
    assert report["bound_rendered_version_id"] == lineage["rendered_version_id"]
    # Store lineage is traversable from the rendered version.
    chain = store.lineage(lineage["rendered_version_id"])
    assert chain[0].artifact_version_id == lineage["rendered_version_id"]


def test_clean_raster_never_clears_unintercepted_vector_source(dataset):
    fixture = _one(dataset, "height_position", "clean")
    source = build_vector_source(fixture)
    refused = analyze_with_source(fixture, source, source_intercepted=False)
    assert refused["raster_classification"] == "no_signal"
    assert refused["cleared"] is False
    assert refused["clearance"] == "refused_unparsed_vector_source"
    assert validate_vector_binding(refused) == []
    # Intercepted + parsed, both paths agree: clearance is honest.
    cleared = analyze_with_source(fixture, source, source_intercepted=True)
    assert cleared["vector_status"] == "ok"
    assert cleared["cleared"] is True


def test_raster_fallback_records_limitations_and_combines(dataset):
    fixture = _one(dataset, "height_position", "encoded")
    fallback = analyze_with_source(fixture, None)
    assert fallback["vector_status"] == "absent_raster_fallback"
    assert any("original bytes" in text for text in fallback["limitations"])
    assert fallback["combined_classification"] == "quantized_without_structure"
    combined = analyze_with_source(fixture, build_vector_source(fixture))
    assert combined["vector_classification"] == "quantized_without_structure"
    assert combined["cleared"] is True
    assert combined["decision"]["delivery"] == "permit"
    # Corrupt sources are explicit, never silently raster-cleared.
    corrupt = analyze_with_source(fixture, {"schema": "nope"})
    assert corrupt["vector_status"] == "corrupt_source"
    assert corrupt["cleared"] is False
