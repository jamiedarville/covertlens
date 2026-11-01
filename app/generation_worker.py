"""Red-team image generation worker for the web service (CL-51).

Runs the library fixture builders (geometric scenes and the
classic LSB/DCT/metadata encoders) on validated parameters and
returns the encoded image bytes plus provenance. This is the
attacker side of the demo: everything generated here is recorded
by the caller with `source: red_team`; detection stays in the
library and never sees these parameters. A random-hidden grid's
base/step are withheld from the caller-facing parameter echo but
kept in the server-side provenance record.
"""

from __future__ import annotations

from typing import Any

KINDS = ("geometric", "spatial_lsb", "jpeg_dct", "metadata")
_GRID_SUBFAMILIES = ("height_position", "gap_timing", "angle_tilt")


def _int_param(
    params: dict[str, Any], name: str, default: int, lo: int, hi: int
) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return value


def _float_param(params: dict[str, Any], name: str) -> float:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _text_param(params: dict[str, Any]) -> str:
    text = params.get("payload_text", "DECAF")
    if not isinstance(text, str) or not text or len(text) > 64:
        raise ValueError("payload_text must be 1-64 characters")
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("payload_text must be ASCII") from None
    return text


def _geometric(params: dict[str, Any]) -> dict[str, Any]:
    from covertlens.geometric_fixtures import (
        GRIDS,
        PAYLOAD_MODES,
        SUBFAMILIES,
        attacker_grid,
        build_geo_pair,
    )

    subfamily = params.get("subfamily", "height_position")
    if subfamily not in SUBFAMILIES:
        raise ValueError(f"subfamily must be one of {SUBFAMILIES}")
    n_elements = _int_param(params, "n_elements", 12, 4, 40)
    scene_seed = _int_param(params, "scene_seed", 101, 0, 999_999_999)
    payload_seed = _int_param(params, "payload_seed", 202, 0, 999_999_999)
    mode = params.get("payload_mode", "random")
    if mode == "custom":
        mode = "ascii"  # custom text encodes as ASCII in the alphabet
    if mode not in PAYLOAD_MODES:
        raise ValueError(f"payload_mode must be one of {PAYLOAD_MODES} or custom")
    text = _text_param(params) if mode != "random" else ""

    choice = params.get("grid_choice", "declared")
    grid: dict[str, Any] | None = None
    grid_echo: dict[str, Any] = {"mode": "declared"}
    declared = GRIDS[subfamily]
    for key in ("base", "step", "levels", "alphabet", "unit"):
        if key in declared:
            value = declared[key]
            grid_echo[key] = list(value) if isinstance(value, tuple) else value
    if choice in ("custom", "random_hidden"):
        if subfamily not in _GRID_SUBFAMILIES:
            raise ValueError(
                "custom/hidden grids apply to height_position, gap_timing "
                "and angle_tilt; lit_dark and colour_code use fixed levels"
            )
        if choice == "custom":
            base = _float_param(params, "grid_base")
            step = _float_param(params, "grid_step")
            alphabet = int(declared["alphabet"])
            top = base + (alphabet - 1) * step
            if step <= 0:
                raise ValueError("grid_step must be positive")
            if subfamily == "height_position" and not (4 <= base and top <= 110):
                raise ValueError(
                    "custom height grid must fit the canvas (base >= 4, top level <= 110)"
                )
            if subfamily == "gap_timing" and not (0 <= base and top <= 60):
                raise ValueError(
                    "custom gap grid must fit the canvas (base >= 0, top level <= 60)"
                )
            if subfamily == "angle_tilt" and not (-40 <= base and top <= 40):
                raise ValueError("custom angle grid must stay within -40..40 degrees")
            grid = {"base": base, "step": step}
            grid_echo = {"mode": "custom", "base": base, "step": step}
        else:
            grid_seed = (scene_seed * 1_000_003 + payload_seed) % 1_000_000_000
            grid = attacker_grid(subfamily, grid_seed)
            grid_echo = {"mode": "random_hidden", "hidden": True}
    elif choice != "declared":
        raise ValueError("grid_choice must be declared, custom or random_hidden")

    _clean, encoded = build_geo_pair(
        subfamily,
        scene_seed=scene_seed,
        payload_seed=payload_seed,
        n_elements=n_elements,
        grid=grid,
        payload_mode=mode,
        payload_text=text or "DECAF",
    )
    parameters = {
        "kind": "geometric",
        "subfamily": subfamily,
        "n_elements": len(encoded.attributes),
        "scene_seed": scene_seed,
        "payload_seed": payload_seed,
        "payload_mode": params.get("payload_mode", "random"),
        "grid": grid_echo,
    }
    provenance = {
        **parameters,
        "grid_full": grid
        if grid is not None
        else {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in declared.items()
            if k in ("base", "step", "levels", "attacker")
        },
        "generator": encoded.generator,
        "encoder": encoded.encoder,
    }
    return {
        "data": encoded.data,
        "media_type": "image/png",
        "ext": "png",
        "fixture_id": encoded.fixture_id,
        "content_hash": encoded.content_hash,
        "parameters": parameters,
        "provenance": provenance,
    }


def _classic(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    from covertlens.fixtures import build_pair

    cover_seed = _int_param(params, "cover_seed", 101, 0, 999_999_999)
    payload_seed = _int_param(params, "payload_seed", 202, 0, 999_999_999)
    payload_bytes = _int_param(params, "payload_bytes", 64, 1, 512)
    _clean, encoded = build_pair(
        kind,
        width=256,
        height=192,
        payload_bytes=payload_bytes,
        cover_seed=cover_seed,
        payload_seed=payload_seed,
    )
    parameters = {
        "kind": kind,
        "cover_seed": cover_seed,
        "payload_seed": payload_seed,
        "payload_bytes": payload_bytes,
        "width": 256,
        "height": 192,
    }
    return {
        "data": encoded.data,
        "media_type": "image/png" if kind == "spatial_lsb" else "image/jpeg",
        "ext": "png" if kind == "spatial_lsb" else "jpg",
        "fixture_id": encoded.fixture_id,
        "content_hash": encoded.content_hash,
        "parameters": parameters,
        "provenance": {
            **parameters,
            "generator": encoded.generator,
            "encoder": encoded.encoder,
        },
    }


def _metadata(params: dict[str, Any]) -> dict[str, Any]:
    from covertlens.metadata_fixtures import build_metadata_pair

    media_kind = params.get("media_kind", "png")
    if media_kind not in ("png", "jpeg"):
        raise ValueError("media_kind must be png or jpeg")
    cover_seed = _int_param(params, "cover_seed", 101, 0, 999_999_999)
    payload_seed = _int_param(params, "payload_seed", 202, 0, 999_999_999)
    payload_bytes = _int_param(params, "payload_bytes", 32, 1, 512)
    _clean, encoded = build_metadata_pair(
        media_kind,
        payload_bytes=payload_bytes,
        cover_seed=cover_seed,
        payload_seed=payload_seed,
        width=128,
        height=96,
    )
    parameters = {
        "kind": "metadata",
        "media_kind": media_kind,
        "cover_seed": cover_seed,
        "payload_seed": payload_seed,
        "payload_bytes": payload_bytes,
    }
    return {
        "data": encoded.data,
        "media_type": "image/png" if media_kind == "png" else "image/jpeg",
        "ext": "png" if media_kind == "png" else "jpg",
        "fixture_id": encoded.fixture_id,
        "content_hash": encoded.content_hash,
        "parameters": parameters,
        "provenance": {
            **parameters,
            "generator": encoded.generator,
            "encoder": encoded.encoder,
        },
    }


def generate_image(params: dict[str, Any]) -> dict[str, Any]:
    """Generate one red-team image; ValueError on bad parameters."""
    if not isinstance(params, dict):
        raise ValueError("request body must be a JSON object")
    kind = params.get("kind", "geometric")
    if kind == "geometric":
        return _geometric(params)
    if kind in ("spatial_lsb", "jpeg_dct"):
        return _classic(str(kind), params)
    if kind == "metadata":
        return _metadata(params)
    raise ValueError(f"kind must be one of {KINDS}")
