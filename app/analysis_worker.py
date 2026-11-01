"""Process-pool analysis worker for the web service (CL-47).

Runs the library pipeline on original bytes and returns
JSON-shaped data. Reviewer-only material is stripped here: the
geometric candidate decode never crosses into an API response
(it belongs to the EvidenceGateway reviewer path, CL-46).
"""

from __future__ import annotations

import os
from typing import Any

MAX_PIXELS_DEFAULT = 20_000_000


def _max_pixels() -> int:
    try:
        return int(os.environ.get("COVERTLENS_MAX_PIXELS", MAX_PIXELS_DEFAULT))
    except ValueError:
        return MAX_PIXELS_DEFAULT


def analyze_bytes(data: bytes, max_pixels: int | None = None) -> dict[str, Any]:
    """Analyze one uploaded artifact; explicit oversized status (CL-47)."""
    if max_pixels is None:
        max_pixels = _max_pixels()
    from covertlens.geometric import analyze_geometric_bytes
    from covertlens.metadata import analyze_all_bytes
    from covertlens.parsing import analyze_bytes as parse_bytes
    from covertlens.verdicts import decide_verdict

    parsed = parse_bytes(data)
    base: dict[str, Any] = {
        "status": parsed.status.value,
        "analysis": None,
        "geometric": None,
        "decision": None,
    }
    if parsed.status.value != "parsed":
        return base
    image = parsed.image or {}
    if parsed.media_kind == "png" and image.get("width"):
        width, height = int(image["width"]), int(image["height"])
        if width * height > max_pixels:
            # Explicit oversized status instead of an unbounded
            # pure-Python decode/segmentation (CL-47 acceptance).
            base["status"] = "oversized"
            base["detail"] = (
                f"image is {width}x{height} "
                f"({width * height} px > {max_pixels} px limit)")
            return base

    result = analyze_all_bytes(data)
    base["analysis"] = result.to_dict()
    if parsed.media_kind == "png":
        geometric = analyze_geometric_bytes(data)
        geometric.pop("candidate_decode", None)  # reviewer-only (CL-46)
        geometric.pop("finding", None)  # already in analysis.findings
        base["geometric"] = geometric
    if result.findings:
        base["decision"] = decide_verdict(result.findings).to_dict()
    return base
