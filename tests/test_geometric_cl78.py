"""CL-78 section 2: the geometric findings of the 2026-11-03 review."""

import json
import random
from pathlib import Path

import pytest

from covertlens._png import load_png, save_png
from covertlens.calibration import load_frozen_thresholds
from covertlens.geo_benchmark import STRUCTURED_SPECS, structured_payload_fixture
from covertlens.geometric import (
    NON_STRUCTURE_SCORE_CEILING,
    SIGNAL_DECLARED,
    SIGNAL_QUANTIZED,
    SIGNAL_STRUCTURE,
    _map_alphabet,
    _structure,
    _text_value,
    analyze_geometric_bytes,
    validate_geometric_report,
)
from covertlens.geometric_fixtures import (
    _render,
    _scene_elements,
    build_attacker_geo_pair,
    build_geo_pair,
)
from covertlens.segmentation import segment_image
from covertlens.verdicts import decide_verdict

DECLARED_HEIGHT = {"declared_channels": ["height"], "context": "data_visualization"}


@pytest.fixture(scope="module")
def frozen():
    return load_frozen_thresholds()[0]


def _jittered_decaf(seed: int, amplitude: int) -> bytes:
    _c, encoded = build_geo_pair(
        "height_position",
        payload_mode="word",
        payload_text="DECAF",
        scene_seed=60_000 + seed,
        jitter_px=amplitude,
    )
    return encoded.data


@pytest.mark.parametrize("seed", range(5))
def test_one_pixel_of_jitter_does_not_hide_a_structured_word(seed):
    report = analyze_geometric_bytes(_jittered_decaf(seed, 1))
    assert validate_geometric_report(report) == []
    assert report["classification"] == SIGNAL_STRUCTURE
    height = report["channels"]["height"]
    assert height["decodable"] is True
    assert height["decode_tolerance"] >= 2.4  # a quarter of the 10 px step


def test_structure_is_found_on_a_channel_that_is_not_the_top_scorer():
    # Lit/dark word with random grid-snapped heights on top: height is
    # the stronger grid, but the word is on lit (review 3.2 item 2).
    spec = STRUCTURED_SPECS["lit_dark"]
    elements, _symbols, _a = _scene_elements(
        "lit_dark",
        encoded=True,
        scene_seed=7,
        payload_seed=7,
        n_elements=spec["n_elements"],
        payload_mode="ascii",
        payload_text="SEND",
    )
    rng = random.Random(3)
    for element in elements:
        element["height"] = 16.0 + 10.0 * rng.randrange(8)
    report = analyze_geometric_bytes(_render(elements, spec["width"], 128))
    assert report["channels"]["height"]["quantized"] is True
    assert report["classification"] == SIGNAL_STRUCTURE
    assert report["primary_channel"] == "lit"
    assert set(report["structure_by_channel"]) >= {"height", "lit"}


def test_a_declared_channel_lowers_the_prior_but_is_still_tested(frozen):
    scene = structured_payload_fixture()
    report = analyze_geometric_bytes(scene.data, declared_context=DECLARED_HEIGHT)
    assert report["classification"] == SIGNAL_DECLARED
    assert report["signal_grade"] == "triage_declared_structure"
    structure = report["structure_by_channel"]["height"]
    assert structure["declared_channel"] is True
    assert structure["passes_undeclared_level"] is True
    assert structure["level"] < structure["undeclared_level"]
    finding = report["finding"]
    assert finding.score > 0.0
    assert decide_verdict([finding], frozen).verdict.value == "flag"


def test_invalid_symbols_are_not_printable():
    assert _map_alphabet([0, 3, 30], 0) == "AD�"
    assert _map_alphabet([0, 1], 1) == "�A"
    # Mostly invalid text can neither claim nor inflate the null.
    assert _text_value("�FG�CGGDB�GE") == float("-inf")
    assert _text_value("DECAFDECAFDE") > float("-inf")


def test_random_payloads_are_claimed_near_the_stated_level():
    rng = random.Random(78)
    claimed = 0
    for _ in range(300):
        block = {
            "symbols": [rng.randrange(8) for _ in range(12)],
            "decodable": True,
            "applicable": True,
            "elements": 12,
        }
        claimed += _structure("height", block, _default_config(), alpha=0.01)["claimed"]
    # Stated level 1%: 3 expected; the binomial tail beyond 9 is < 0.1%.
    assert claimed <= 9


def _default_config():
    from covertlens.geometric import DEFAULT_GEO_CONFIG

    return DEFAULT_GEO_CONFIG


def test_colour_levels_are_discovered_not_read_from_the_fixture_palette():
    blues = ((40, 70, 170), (90, 140, 230), (20, 30, 110))
    spec = STRUCTURED_SPECS["colour_code"]
    _c, encoded = build_geo_pair(
        "colour_code",
        payload_mode="ascii",
        payload_text="DECAF",
        n_elements=spec["n_elements"],
        width=spec["width"],
        grid={"palette": blues},
    )
    report = analyze_geometric_bytes(encoded.data)
    assert report["classification"] == SIGNAL_STRUCTURE
    assert len(report["channels"]["colour"]["grid"]["levels"]) == 3
    source = Path("covertlens/segmentation.py").read_text()
    assert "geometric_fixtures" not in source


@pytest.mark.parametrize("bars", (5, 6, 7))
def test_short_sequences_top_out_at_triage(bars, frozen):
    elements, _s, _a = _scene_elements(
        "height_position",
        encoded=True,
        scene_seed=1,
        payload_seed=1,
        n_elements=bars,
        payload_mode="word",
        payload_text="DECAF",
    )
    report = analyze_geometric_bytes(_render(elements, 384, 128))
    assert report["classification"] != SIGNAL_STRUCTURE
    assert "too few symbols" in report["structure"]["reason"]
    finding = report["finding"]
    assert finding.score <= NON_STRUCTURE_SCORE_CEILING
    assert decide_verdict([finding], frozen).delivery == "permit"


def test_findings_carry_a_symbol_digest_never_the_sequence():
    report = analyze_geometric_bytes(structured_payload_fixture().data)
    as_json = json.dumps(report["finding"].to_dict())
    for name, channel in report["finding"].evidence["channels"].items():
        assert "symbols" not in channel, name
        assert channel["symbols_digest"].startswith("sha256:")
        assert channel["symbol_count"] == channel["elements"]
    # The DECAF symbol run [3, 4, 2, 0, 5] (or shifted) is nowhere.
    assert "3, 4, 2, 0, 5" not in as_json
    assert "4, 5, 3, 1, 6" not in as_json


def _noisy(data: bytes, amplitude: int, seed: int) -> bytes:
    pixels, width, height = load_png(data)
    rng = random.Random(seed)
    noisy = bytes(
        max(0, min(255, v + rng.randint(-amplitude, amplitude))) for v in pixels
    )
    return save_png(noisy, width, height)


@pytest.mark.parametrize("amplitude", (3, 6))
def test_segmentation_survives_per_channel_noise(amplitude):
    for subfamily, count in (("height_position", 12), ("colour_code", 12)):
        _c, encoded = build_geo_pair(subfamily)
        for seed in range(3):
            result = segment_image(_noisy(encoded.data, amplitude, seed))
            assert result.status == "ok", (subfamily, seed)
            assert len(result.elements) == count, (subfamily, seed)
            assert result.noise_level >= 1.0


def test_near_background_elements_are_a_documented_noise_limit():
    # Lit windows are grey 235 on a 238 background: under +/-3 noise
    # only the dark elements remain (docs/contracts/segmentation.md).
    _c, encoded = build_geo_pair("lit_dark")
    clean = segment_image(encoded.data)
    noisy = segment_image(_noisy(encoded.data, 3, 0))
    assert len(clean.elements) == 12
    assert 0 < len(noisy.elements) < 12
    assert all(e["brightness"] < 150 for e in noisy.elements)


def test_every_other_level_attacker_is_quantized_on_twice_the_step():
    _c, encoded = build_attacker_geo_pair(
        "height_position", scene_seed=11, payload_seed=12, grid_seed=13, level_stride=2
    )
    assert all(s % 2 == 0 for s in encoded.symbols)
    report = analyze_geometric_bytes(encoded.data)
    assert report["classification"] == SIGNAL_QUANTIZED
    step = report["channels"]["height"]["step"]
    encoder_step = encoded.encoder["config"]["grid"]["step"]
    assert abs(step - 2 * encoder_step) <= 1.6


def test_quantization_alone_never_withholds_under_the_freeze(frozen):
    doc = json.loads(Path("config/frozen-thresholds.json").read_text())
    geometric = doc["families"]["geometric"]
    assert geometric["enforcement_quarantine_at"] > NON_STRUCTURE_SCORE_CEILING
    _c, encoded = build_geo_pair("height_position", scene_seed=5, payload_seed=6)
    report = analyze_geometric_bytes(encoded.data)
    assert report["classification"] == SIGNAL_QUANTIZED
    assert decide_verdict([report["finding"]], frozen).delivery == "permit"
