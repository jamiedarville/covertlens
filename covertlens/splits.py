"""Leakage-safe splits and independent recovery scoring (CL-10).

Split assignment is deterministic and grouped by cover lineage: an
original and every derivative of the same cover — its encoded pair
member, benign edits, generator variations of that cover — always land
in one split (DT-03). Held-out seeds, patterns and encoder
configurations are recorded so the frozen split is auditable.

Label separation is enforced at the export boundary (DT-04): the
detector-facing manifest contains no payloads and excludes held-out
fixtures entirely, while scorer-side ground truth requires the
explicit ``scorer`` role. Independent recovery checks re-decode every
encoded fixture through the CL-9 decoders and require bit-exact
recovery. Held-out labels are never calibration inputs (C-07), and no
result here is equated with collusion (C-02).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fixtures import Fixture
from .fixtures import manifest as _fixture_manifest

SPLITS = ("train", "calibration", "held_out")
SPLIT_POLICY_VERSION = "1.0.0"
SCORER_ROLE = "scorer"


@dataclass(frozen=True)
class SplitPolicy:
    """Versioned, seeded assignment policy; ratios follow SPLITS order."""

    dataset_seed: int = 20261028
    ratios: tuple[float, float, float] = (0.5, 0.25, 0.25)
    version: str = SPLIT_POLICY_VERSION

    def __post_init__(self) -> None:
        if len(self.ratios) != len(SPLITS) or abs(sum(self.ratios) - 1.0) > 1e-9:
            raise ValueError("ratios must cover SPLITS and sum to 1")


def group_key(fixture: Fixture) -> str:
    """Cover-lineage group: everything derived from one cover stays together."""
    gen = fixture.generator
    return (
        f"cover:{gen.get('pattern')}:{gen.get('seed')}:{fixture.width}x{fixture.height}"
    )


def _split_for_group(group: str, policy: SplitPolicy) -> str:
    digest = hashlib.sha256(f"{policy.dataset_seed}|{group}".encode()).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    edge = 0.0
    for split, ratio in zip(SPLITS, policy.ratios):
        edge += ratio
        if bucket < edge:
            return split
    return SPLITS[-1]


def assign_splits(
    fixtures: Iterable[Fixture], policy: SplitPolicy | None = None
) -> dict[str, str]:
    """Assign every fixture to exactly one split, by lineage group."""
    policy = policy or SplitPolicy()
    return {f.fixture_id: _split_for_group(group_key(f), policy) for f in fixtures}


def validate_no_leakage(
    fixtures: Iterable[Fixture], assignments: dict[str, str]
) -> list[str]:
    """Return leakage errors; empty means the split assignment is safe."""
    rows = list(fixtures)
    errors: list[str] = []
    by_group: dict[str, set[str]] = {}
    by_hash: dict[str, set[str]] = {}
    by_pair: dict[str, set[str]] = {}
    for fixture in rows:
        split = assignments.get(fixture.fixture_id)
        if split is None:
            errors.append(f"{fixture.fixture_id}: no split assigned")
            continue
        if split not in SPLITS:
            errors.append(f"{fixture.fixture_id}: unknown split {split!r}")
            continue
        by_group.setdefault(group_key(fixture), set()).add(split)
        by_hash.setdefault(fixture.content_hash, set()).add(split)
        by_pair.setdefault(fixture.pair_id, set()).add(split)
    for group, splits in sorted(by_group.items()):
        if len(splits) > 1:
            errors.append(f"group {group} spans splits {sorted(splits)}")
    for digest, splits in sorted(by_hash.items()):
        if len(splits) > 1:
            errors.append(
                f"content_hash {digest} appears in multiple splits {sorted(splits)}"
            )
    for pair_id, splits in sorted(by_pair.items()):
        if len(splits) > 1:
            errors.append(f"pair {pair_id} spans splits {sorted(splits)}")
    return errors


def held_out_record(
    fixtures: Iterable[Fixture],
    assignments: dict[str, str],
    policy: SplitPolicy | None = None,
) -> dict[str, Any]:
    """Auditable record of what the held-out split contains (DT-03)."""
    policy = policy or SplitPolicy()
    held = [f for f in fixtures if assignments.get(f.fixture_id) == "held_out"]
    encoder_configs = {json.dumps(f.encoder, sort_keys=True) for f in held}
    return {
        "schema": "covertlens.held-out-record",
        "version": 1,
        "policy": {
            "version": policy.version,
            "dataset_seed": policy.dataset_seed,
            "ratios": dict(zip(SPLITS, policy.ratios)),
        },
        "split": "held_out",
        "fixture_count": len(held),
        "fixture_ids": sorted(f.fixture_id for f in held),
        "cover_seeds": sorted({f.generator["seed"] for f in held}),
        "payload_seeds": sorted({f.payload_seed for f in held if f.role == "encoded"}),
        "patterns": sorted({f.generator["pattern"] for f in held}),
        "encoder_configs": [json.loads(c) for c in sorted(encoder_configs)],
        "tasks": [],
        "agents": [],
        "task_agent_note": "fixture records carry no task/agent identity; "
        "those dimensions are recorded when present on future records",
    }


def detector_manifest(
    fixtures: Iterable[Fixture], assignments: dict[str, str]
) -> dict[str, Any]:
    """Detector-facing manifest: no payloads, no held-out fixtures (DT-04)."""
    visible = [f for f in fixtures if assignments.get(f.fixture_id) != "held_out"]
    doc = _fixture_manifest(visible)
    doc["split_view"] = "detector"
    return doc


def scorer_ground_truth(
    fixtures: Iterable[Fixture],
    assignments: dict[str, str],
    *,
    role: str,
) -> dict[str, Any]:
    """Held-out payload labels; scorer role only (DT-04)."""
    if role != SCORER_ROLE:
        raise PermissionError("held-out labels require the scorer role")
    return {
        f.fixture_id: {
            "payload_hex": f.payload.hex(),
            "payload_bits": f.payload_bits,
            "payload_seed": f.payload_seed,
        }
        for f in fixtures
        if assignments.get(f.fixture_id) == "held_out" and f.role == "encoded"
    }


@dataclass(frozen=True)
class RecoveryReport:
    checked: int
    passed: int
    failures: tuple[str, ...] = ()


def verify_recovery(fixtures: Iterable[Fixture]) -> RecoveryReport:
    """Independently re-decode every encoded fixture (DT-04)."""
    failures: list[str] = []
    checked = 0
    for fixture in fixtures:
        if fixture.role != "encoded":
            continue
        checked += 1
        if not fixture.verify_payload():
            failures.append(fixture.fixture_id)
    return RecoveryReport(
        checked=checked, passed=checked - len(failures), failures=tuple(failures)
    )


def split_manifest(
    fixtures: Iterable[Fixture],
    assignments: dict[str, str],
    policy: SplitPolicy | None = None,
) -> dict[str, Any]:
    """Full assignment manifest (scorer/ops view; contains no payloads)."""
    rows = list(fixtures)
    return {
        "schema": "covertlens.split-manifest",
        "version": 1,
        "policy": {
            "version": (policy or SplitPolicy()).version,
            "dataset_seed": (policy or SplitPolicy()).dataset_seed,
            "ratios": dict(zip(SPLITS, (policy or SplitPolicy()).ratios)),
        },
        "assignments": {f.fixture_id: assignments[f.fixture_id] for f in rows},
        "held_out": held_out_record(rows, assignments, policy),
        "leakage_errors": validate_no_leakage(rows, assignments),
    }


def write_split_dataset(
    out_dir: str | Path,
    fixtures: Iterable[Fixture],
    assignments: dict[str, str],
    policy: SplitPolicy | None = None,
) -> Path:
    """Write detector and scorer outputs as separate directory trees."""
    rows = list(fixtures)
    target = Path(out_dir)
    detector_dir = target / "detector"
    scorer_dir = target / "scorer"
    detector_dir.mkdir(parents=True, exist_ok=True)
    scorer_dir.mkdir(parents=True, exist_ok=True)
    for fixture in rows:
        if assignments.get(fixture.fixture_id) == "held_out":
            continue
        ext = "png" if fixture.media_kind == "png" else "jpg"
        (detector_dir / f"{fixture.fixture_id}.{ext}").write_bytes(fixture.data)
    (detector_dir / "manifest.json").write_text(
        json.dumps(detector_manifest(rows, assignments), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (scorer_dir / "ground-truth.json").write_text(
        json.dumps(
            scorer_ground_truth(rows, assignments, role=SCORER_ROLE),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (target / "assignments.json").write_text(
        json.dumps(split_manifest(rows, assignments, policy), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target
