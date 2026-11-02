"""CL-57: deterministic malformed-input campaign over all fixture sources."""

import json
import random
from pathlib import Path

from jsonschema import Draft202012Validator

from covertlens.fixtures import build_dataset
from covertlens.geometric_fixtures import build_geo_dataset
from covertlens.parsing import analyze_bytes, validate_result

ROOT = Path(__file__).resolve().parent.parent


def test_2000_mutated_images_never_raise_and_validate():
    sources = [f.data for f in build_dataset() + build_geo_dataset()]
    sources += [
        p.read_bytes()
        for directory in (ROOT / "tests/data/jpeg", ROOT / "tests/data/real")
        for p in sorted(directory.glob("*"))
        if p.suffix in (".jpg", ".jpeg", ".png")
    ]
    validator = Draft202012Validator(
        json.loads((ROOT / "schemas/analysis-result.schema.json").read_text())
    )
    rng = random.Random(57)
    for i in range(2000):
        data = bytearray(sources[i % len(sources)])
        if i % 2:
            data = data[: rng.randrange(len(data))]
        else:
            for _ in range(rng.randint(1, 4)):
                data[rng.randrange(len(data))] ^= rng.randint(1, 255)
        result = analyze_bytes(bytes(data))
        assert validate_result(result) == [], i
        validator.validate(result.to_dict())


def test_independent_libjpeg_subsampling_and_huffman_selectors():
    for name, sampling in [
        ("420", "4:2:0"),
        ("422", "4:2:2"),
        ("444", "4:4:4"),
        ("optimized", "4:2:0"),
    ]:
        result = analyze_bytes((ROOT / f"tests/data/jpeg/{name}.jpg").read_bytes())
        assert result.status == "parsed", result.errors
        assert result.image["sampling"] == sampling
        assert result.coefficients and all(len(b) == 64 for b in result.coefficients)
        # Odd 97x65 image: 7*5 MCUs, six blocks each for 4:2:0.
        if sampling == "4:2:0":
            assert len(result.coefficients) == 210


def test_truncated_sof_and_dht_are_corrupt():
    import struct

    for marker, body in [
        (b"\xff\xc0", b"\x08\x00\x01\x00\x01\x03"),
        (b"\xff\xc4", b"\x00\x01"),
    ]:
        data = (
            b"\xff\xd8" + marker + struct.pack(">H", len(body) + 2) + body + b"\xff\xd9"
        )
        assert analyze_bytes(data).status == "corrupt"
