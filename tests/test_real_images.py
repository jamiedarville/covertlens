"""CL-52: offline element counts and locations on committed real renderings.

Counts and horizontal centre annotations are authored in manifest.json,
independently of segmenter output. No Pillow, browser or network in tests.
"""

import hashlib
import json
from pathlib import Path

import pytest

from covertlens.segmentation import segment_image, validate_segmentation

DATA = Path(__file__).parent / "data/real"
CASES = json.loads((DATA / "manifest.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["file"])
def test_real_image_element_count_and_locations(case):
    data = (DATA / case["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == case["sha256"]
    result = segment_image(data)
    assert result.status == "ok"
    assert (result.width, result.height) == tuple(case["size"])
    assert abs(len(result.elements) - case["count"]) <= 1
    assert validate_segmentation(result.to_dict()) == []
    # Matching counts alone could hide merged objects plus spurious noise.
    # Require distinct detections near the annotated visible objects.
    remaining = list(result.elements)
    missing = 0
    for x in case["centres_x"]:
        if not remaining:
            missing += 1
            continue
        closest = min(remaining, key=lambda e: abs(e["left"] + e["width"] / 2 - x))
        if abs(closest["left"] + closest["width"] / 2 - x) <= case["centre_tolerance"]:
            remaining.remove(closest)
        else:
            missing += 1
    assert missing <= 1
    assert len(remaining) <= 1
    assert all(e["area"] > 0 for e in result.elements)


def test_morphology_keeps_thin_antialiased_dashes():
    result = segment_image((DATA / "morse-dashes.jpg").read_bytes())
    assert len(result.elements) == 8
    assert all(4 <= e["height"] <= 10 for e in result.elements)
    assert result.to_dict()["tolerances"]["morphology_3x3_open_close"] is True
