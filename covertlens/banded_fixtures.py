"""Larger payload bands across cover textures (CL-68, DT-01/DT-02).

The CL-9 suite has one pair per payload band per family, so the
CL-27 freeze rested on two positives per family and CL-28 on one or
two held-out positives. This suite builds dozens of paired fixtures
per payload band per family on all three CL-9 cover textures
(`gradient_noise`, `smooth`, `blocks`) and sizes every cell so the
held-out split holds at least `HELD_OUT_TARGET` positives.

Rules:

- **Same factories.** Pairs come from the CL-9/CL-22 builders
  (`build_pair`, `build_metadata_pair`) with fresh cover seeds, so
  every encoded fixture is verified by independent decode exactly as
  before, and CL-10 lineage groups (`cover:<pattern>:<seed>:<size>`)
  keep each clean/encoded pair in one split.
- **Bands by bits per pixel** (CL-9 `_payload_band`): payload sizes
  are drawn per pair inside the band's byte range at 64x48.
- **Sizing never looks at labels or scores.** A cell keeps adding
  pairs (in a fixed seed order) until the deterministic CL-10 split
  has placed `HELD_OUT_TARGET` of them in `held_out`. Split
  assignment is a hash of the lineage group, so sizing by it uses no
  detector output and no ground truth.
- **Capacity limits are recorded, not hidden.** The CL-9 DCT encoder
  only embeds in |AC| >= 2 coefficients; smooth and blocks covers at
  64x48 cannot carry a high-band payload (and smooth covers rarely
  carry more than ~40 bytes). Those cells are marked
  `not_constructible` with the reason.
- **Metadata is texture-independent.** The metadata detector reads
  ancillary entries, so its cells are per band, cycling through the
  three textures and both media.

Nothing here decodes a payload outside the scorer path; manifests
carry hashes, never payload bytes (DT-04).
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ._parallel import process_map, star
from .fixtures import Fixture, build_pair, dct_carrier_capacity_bits, generate_cover
from .metadata_fixtures import build_metadata_pair
from .splits import SPLITS, SplitPolicy, assign_splits

BANDED_SUITE_NAME = "banded-textures"
BANDED_SUITE_VERSION = "1.0.0"
TEXTURES = ("gradient_noise", "smooth", "blocks")
BANDS = ("low", "medium", "high")
FAMILIES = ("spatial_lsb", "jpeg_dct", "metadata")
WIDTH = 64
HEIGHT = 48
HELD_OUT_TARGET = 20
# Payload bytes per band at 64x48 (3072 px): low <= 0.05 bpp,
# medium <= 0.25 bpp, high above (CL-9 `_payload_band`).
BAND_BYTES: dict[str, tuple[int, int]] = {
    "low": (6, 19),
    "medium": (20, 96),
    "high": (97, 240),
}
# Disjoint from every other suite's seeds (CL-9 101..135, CL-28
# stability 100_000+ and 200_000+, CL-61 smooth_field suite).
SEED_BASE = 600_000
# Cap on attempts per cell, so an unconstructible cell stops.
MAX_ATTEMPTS = 400
# A DCT cell is not constructible after this many consecutive seeds
# that cannot hold the band's smallest payload.
MAX_CAPACITY_FAILURES = 40


@dataclass(frozen=True)
class BandedCell:
    """One (family, texture, band) cell and its split counts."""

    family: str
    texture: str
    band: str
    pairs: int
    split_pairs: dict[str, int]
    constructible: bool = True
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "texture": self.texture,
            "band": self.band,
            "pairs": self.pairs,
            "split_pairs": dict(self.split_pairs),
            "constructible": self.constructible,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BandedDataset:
    """Fixtures, their CL-10 split assignment and the cell table."""

    fixtures: tuple[Fixture, ...]
    assignments: dict[str, str]
    cells: tuple[BandedCell, ...]
    held_out_target: int
    policy_version: str = field(default_factory=lambda: SplitPolicy().version)

    def summary(self) -> dict[str, Any]:
        return {
            "suite": BANDED_SUITE_NAME,
            "version": BANDED_SUITE_VERSION,
            "width": WIDTH,
            "height": HEIGHT,
            "held_out_target": self.held_out_target,
            "split_policy_version": self.policy_version,
            "fixture_count": len(self.fixtures),
            "cells": [cell.to_dict() for cell in self.cells],
        }


def texture_of(fixture: Fixture) -> str:
    """Cover texture recorded in the fixture's generator provenance."""
    return str((fixture.generator or {}).get("pattern") or "unknown")


def _seed(family: str, texture: str, band: str, attempt: int) -> int:
    return (
        SEED_BASE
        + FAMILIES.index(family) * 100_000
        + TEXTURES.index(texture) * 20_000
        + BANDS.index(band) * 5_000
        + attempt
    )


def _payload_sizes(band: str, seed: int) -> list[int]:
    """Deterministic payload sizes to try, largest first, inside the band."""
    low, high = BAND_BYTES[band]
    first = random.Random(seed).randint(low, high)
    sizes = [first]
    step = first
    while step > low:
        step = max(low, (step + low) // 2)
        sizes.append(step)
    return sorted(set(sizes), reverse=True)


def _pair(
    family: str, texture: str, band: str, seed: int, media_kind: str
) -> tuple[Fixture, Fixture] | None:
    """One verified pair in the band, or None when capacity rules it out."""
    sizes = _payload_sizes(band, seed)
    if family == "jpeg_dct":
        # Same outcome as trying each size until one embeds, without
        # paying for failed encodes: embedding fails exactly when the
        # payload has more bits than the cover's carriers.
        capacity = dct_carrier_capacity_bits(
            generate_cover(WIDTH, HEIGHT, pattern=texture, seed=seed), WIDTH, HEIGHT
        )
        sizes = [n for n in sizes if 8 * n <= capacity][:1]
    for n_bytes in sizes:
        try:
            if family == "metadata":
                return build_metadata_pair(
                    media_kind,
                    payload_bytes=n_bytes,
                    cover_seed=seed,
                    payload_seed=seed + 7,
                    width=WIDTH,
                    height=HEIGHT,
                    pattern=texture,
                )
            return build_pair(
                family,
                width=WIDTH,
                height=HEIGHT,
                payload_bytes=n_bytes,
                cover_seed=seed,
                payload_seed=seed + 7,
                pattern=texture,
            )
        except ValueError as exc:
            if "capacity" not in str(exc):
                raise
    return None


def _fill_cell(
    family: str,
    textures: tuple[str, ...],
    band: str,
    held_out_target: int,
) -> tuple[list[Fixture], BandedCell]:
    """Add pairs in seed order until the held-out split reaches its target."""
    fixtures: list[Fixture] = []
    counts = {split: 0 for split in SPLITS}
    capacity_failures = 0
    media = ("png", "jpeg")
    texture_label = textures[0] if len(textures) == 1 else "mixed"
    for attempt in range(MAX_ATTEMPTS):
        texture = textures[attempt % len(textures)]
        media_kind = media[(attempt // len(textures)) % len(media)]
        seed = _seed(family, textures[0], band, attempt)
        pair = _pair(family, texture, band, seed, media_kind)
        if pair is None:
            capacity_failures += 1
            if capacity_failures >= MAX_CAPACITY_FAILURES and not fixtures:
                return [], BandedCell(
                    family,
                    texture_label,
                    band,
                    0,
                    counts,
                    constructible=False,
                    reason=(
                        "DCT carrier capacity (|AC| >= 2) on this texture "
                        f"cannot hold a {band}-band payload at {WIDTH}x{HEIGHT}"
                    ),
                )
            continue
        capacity_failures = 0
        clean, encoded = pair
        if encoded.payload_band != band:
            raise AssertionError(
                f"{encoded.fixture_id} landed in {encoded.payload_band}, not {band}"
            )
        split = assign_splits([encoded])[encoded.fixture_id]
        counts[split] += 1
        fixtures.extend(pair)
        if counts["held_out"] >= held_out_target:
            break
    else:
        return fixtures, BandedCell(
            family,
            texture_label,
            band,
            sum(counts.values()),
            counts,
            constructible=counts["held_out"] >= held_out_target,
            reason=f"held-out target not reached in {MAX_ATTEMPTS} attempts",
        )
    return fixtures, BandedCell(
        family, texture_label, band, sum(counts.values()), counts
    )


@lru_cache(maxsize=4)
def build_banded_dataset(
    held_out_target: int = HELD_OUT_TARGET,
    families: tuple[str, ...] = FAMILIES,
) -> BandedDataset:
    """The CL-68 suite: dozens of pairs per band, family and texture.

    Pixel families get one cell per (texture, band); metadata gets
    one cell per band cycling textures and media. Deterministic and
    cached per process (calibration, the frozen benchmark and the
    scorecard share one build).
    """
    plan: list[tuple[str, tuple[str, ...], str]] = []
    for family in families:
        if family not in FAMILIES:
            raise ValueError(f"family must be one of {FAMILIES}")
        texture_groups = (
            [TEXTURES] if family == "metadata" else [(t,) for t in TEXTURES]
        )
        for textures in texture_groups:
            for band in BANDS:
                plan.append((family, textures, band))
    # Cells are independent and deterministic: a process pool returns
    # the serial result in plan order (covertlens._parallel).
    results = process_map(
        star,
        [
            (_fill_cell, (family, textures, band, held_out_target))
            for family, textures, band in plan
        ],
        chunksize=1,
    )
    fixtures: list[Fixture] = []
    cells: list[BandedCell] = []
    for rows, cell in results:
        fixtures.extend(rows)
        cells.append(cell)
    assignments = assign_splits(fixtures)
    return BandedDataset(
        fixtures=tuple(fixtures),
        assignments=assignments,
        cells=tuple(cells),
        held_out_target=held_out_target,
    )


def held_out_positive_counts(
    fixtures: Iterable[Fixture], assignments: dict[str, str]
) -> dict[str, dict[str, dict[str, int]]]:
    """Held-out encoded counts per family -> texture -> band."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for fixture in fixtures:
        if fixture.role != "encoded" or assignments.get(fixture.fixture_id) != (
            "held_out"
        ):
            continue
        bands = out.setdefault(fixture.family, {}).setdefault(texture_of(fixture), {})
        bands[fixture.payload_band] = bands.get(fixture.payload_band, 0) + 1
    return out
