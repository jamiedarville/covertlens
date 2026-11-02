import pytest

from covertlens.geometric import (
    analyze_geometric,
    analyze_geometric_bytes,
    validate_geometric_report,
)
from covertlens.geometric_fixtures import build_geo_dataset, build_geo_pair
from covertlens.segmentation import segment_image


@pytest.fixture(scope="module")
def dataset():
    return build_geo_dataset()


def _one(dataset, subfamily, role, index=0):
    matches = [f for f in dataset if f.subfamily == subfamily and f.role == role]
    return matches[index]


def test_quantization_report_is_a_measurement_not_a_verdict(dataset):
    fixture = _one(dataset, "height_position", "encoded")
    report = analyze_geometric_bytes(fixture.data)
    assert validate_geometric_report(report) == []
    channel = report["channels"]["height"]
    # Grid step, residuals and supporting count are all reported.
    assert channel["grid"]["step"] == 10.0
    assert channel["supporting"] == 12
    assert channel["support_fraction"] == 1.0
    assert max(abs(r) for r in channel["residuals"]) <= 1.6
    assert report["finding"].score == pytest.approx(1.0)


def test_clean_continuous_variation_scores_low(dataset):
    fixture = _one(dataset, "height_position", "clean")
    report = analyze_geometric_bytes(fixture.data)
    assert report["channels"]["height"]["support_fraction"] < 0.9
    assert report["classification"] in ("weak_signal", "no_signal")
    assert report["finding"].score < 0.9


def test_legitimate_chart_is_quantized_without_structure(dataset):
    chart = _one(dataset, "height_position", "negative")
    assert chart.negative_kind == "legitimate_chart"
    report = analyze_geometric_bytes(chart.data)
    # Grid-snapped by design, but the symbol sequence maps to no
    # declared-code word: weak triage signal only (GEO-05).
    assert report["classification"] == "quantized_without_structure"
    assert report["structure"]["claimed"] is False


def test_structure_claimed_only_through_declared_code():
    # Heights spelling DECAF (D=3, E=4, C=2, A=0, F=5) + filler.
    _clean, encoded = build_geo_pair("height_position", scene_seed=11, payload_seed=12)
    seg = segment_image(encoded.data)
    symbols = [3, 4, 2, 0, 5, 3, 4, 2, 0, 5, 3, 4]  # DECAFDECAFDE
    heights = [16 + 10 * s for s in symbols]
    for element, height in zip(seg.elements, heights):
        element["height"] = height
    report = analyze_geometric(seg)
    assert report["primary_channel"] == "height"
    assert report["classification"] == "structure_claimed"
    assert report["structure"]["code"] == "alphabet_position_a0"
    assert report["structure"]["null_exceedance"] <= 0.01
    # CL-46: no mapped text in the finding; the candidate decode is
    # transient on the report for the reviewer evidence path only.
    assert "mapped_preview" not in report["structure"]
    assert report["candidate_decode"]["text"].startswith("DECAF")
    import json

    assert "DECAF" not in json.dumps(report["finding"].to_dict())
    # The finding never presents this as a decoded message.
    assert report["finding"].evidence["label"] == "evidence_aid_not_decoded_message"


def test_bit_packing_structure_and_failed_segmentation(dataset):
    fixture = _one(dataset, "lit_dark", "encoded")
    report = analyze_geometric_bytes(fixture.data)
    assert report["channels"]["lit"]["support_fraction"] == 1.0
    # Failed segmentation yields no finding, not a clean score.
    bad = analyze_geometric_bytes(b"\xff\xd8\xff\xe0" + bytes(32))
    assert bad["finding"] is None
    assert bad["status"] == "corrupt_input"
    assert validate_geometric_report(bad) == []
