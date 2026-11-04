"""Calibrate and freeze research/enforcement thresholds (CL-27, OPS-02).

Operating points are selected on **development data only**: the
calibration input must carry CL-10 split assignments, and any
fixture assigned `held_out` in the input raises — held-out labels
can never tune the points that will later be scored against them
(C-07). Detector-visible calibration may use train + calibration
assignments.

Two points are selected separately per family (C-06):

- **triage** (`flag_at`, high-recall): the highest candidate
  threshold whose development recall still meets the recall target;
- **enforcement** (`quarantine_at` / `fail_run_at`, high-precision):
  successively stricter candidates whose development precision meets
  the precision target.

CL-68 recalibrates on the banded suite (`banded_fixtures`): dozens of
development pairs per payload band and cover texture. Two selection
rules are refined for the CL-27 families, because with real sample
sizes the CL-27 rules leave recall on the table and collapse the
fail-run point onto quarantine:

- **free-recall triage:** after the highest candidate meeting the
  recall target is found, triage moves down to the lowest candidate
  that admits no additional development negative;
- **fail-run above every development negative:** fail-run is the
  first candidate above both the quarantine point and the highest
  development negative score that still meets the precision target
  (1.0, unreachable, when none does). Clean-run false failures are
  then bounded by the clean tail beyond the whole development set,
  not by the precision target alone.

Development textures are per family (`CALIBRATED_TEXTURES`): the
pixel detectors' clean baselines depend on cover texture, and one
per-family point cannot serve every texture (CL-68 measurement), so
LSB/DCT calibrate on `gradient_noise`; metadata is texture-independent
and calibrates on all three. Geometric keeps its CL-54 rules, with
one CL-78 floor: its quarantine point must lie above the
non-structure score ceiling, so quantization alone never withholds.

The owners' freeze is the shipped `config/frozen-thresholds.json`:
versioned points, acceptance targets, calibrated coverage (media and
payload bands actually present in development data), and the
calibration dataset hash. Bands absent from development data are
recorded as *not calibrated* — coverage is narrowed, never silently
extended. Detector or dataset changes after the freeze require a new
freeze (CL-26 pin differences name the drift).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ._validation import make_need
from .fixtures import Fixture
from .geometric import (
    DEFAULT_GEO_CONFIG,
    GEO_DETECTOR_NAME,
    GEO_DETECTOR_VERSION,
    NON_STRUCTURE_SCORE_CEILING,
)
from .geometric_fixtures import GeoFixture
from .metadata import analyze_all_bytes
from .pinning import dataset_hash
from .splits import SPLITS
from .verdicts import FamilyThresholds, ThresholdConfig

CALIBRATION_SCHEMA = "covertlens.calibration"
CALIBRATION_VERSION = "1.2.0"
# frozen-1.2.0 was the label on the unmerged CL-78 branch and is
# skipped so one label never names two different freezes.
FROZEN_CONFIG_VERSION = "frozen-1.4.0"
FROZEN_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "frozen-thresholds.json"
)
RECALL_TARGET = 0.95
PRECISION_TARGET = 0.99
FAMILIES = ("spatial_lsb", "jpeg_dct", "metadata", "geometric")
ALL_TEXTURES = ("gradient_noise", "smooth", "blocks")
# CL-68: development cover textures per family (the detection claim).
CALIBRATED_TEXTURES: dict[str, tuple[str, ...]] = {
    "spatial_lsb": ("gradient_noise",),
    "jpeg_dct": ("gradient_noise",),
    "metadata": ALL_TEXTURES,
}
# Families calibrated with the CL-68 refined selection rules.
REFINED_RULE_FAMILIES = ("spatial_lsb", "jpeg_dct", "metadata")
CL27_RULES = {
    "triage": "highest candidate meeting the recall target",
    "quarantine": "first stricter candidate meeting the precision target",
    "fail_run": "next candidate above quarantine meeting the precision target",
}
CL68_RULES = {
    "triage": "highest candidate meeting the recall target, then the lowest "
    "candidate admitting no additional development negative (free recall)",
    "quarantine": "first stricter candidate meeting the precision target",
    "fail_run": "first candidate above quarantine and above every development "
    "negative that meets the precision target, else 1.0 (unreachable)",
}

# Detector scores are a pure function of the bytes; calibration, the
# frozen benchmark and the scorecard score the same fixtures, so one
# process scores each artifact once (CL-68 suites are large).
_SCORE_MEMO: dict[str, tuple[tuple[str, str, float], ...]] = {}


def _score_bytes(data: bytes) -> tuple[str, tuple[tuple[str, str, float], ...]]:
    import hashlib

    return hashlib.sha256(data).hexdigest(), tuple(
        (f.family, f.detector_name, float(f.score))
        for f in analyze_all_bytes(data).findings
    )


def prime_detector_scores(datas: Iterable[bytes]) -> None:
    """Score many artifacts at once (process pool), filling the memo."""
    import hashlib

    from ._parallel import process_map

    missing = {}
    for data in datas:
        key = hashlib.sha256(data).hexdigest()
        if key not in _SCORE_MEMO:
            missing[key] = data
    for key, scores in process_map(_score_bytes, list(missing.values()), chunksize=16):
        _SCORE_MEMO[key] = scores


def detector_scores(data: bytes) -> tuple[tuple[str, str, float], ...]:
    """(family, detector_name, score) for every finding on these bytes."""
    import hashlib

    key = hashlib.sha256(data).hexdigest()
    cached = _SCORE_MEMO.get(key)
    if cached is None:
        cached = tuple(
            (f.family, f.detector_name, float(f.score))
            for f in analyze_all_bytes(data).findings
        )
        _SCORE_MEMO[key] = cached
    return cached


def texture_of(fixture: Fixture | GeoFixture) -> str:
    """Cover texture of a fixture (geometric scenes have none)."""
    if isinstance(fixture, GeoFixture):
        return "synthetic_scene"
    return str((fixture.generator or {}).get("pattern") or "unknown")


def _candidates(scores: list[float]) -> list[float]:
    unique = sorted(set(scores))
    points = set(unique)
    for low, high in zip(unique, unique[1:]):
        points.add(round((low + high) / 2.0, 6))
    return sorted(points)


def _metrics(
    positive: list[float], negative: list[float], threshold: float
) -> dict[str, Any]:
    tp = sum(1 for s in positive if s >= threshold)
    fp = sum(1 for s in negative if s >= threshold)
    return {
        "threshold": round(threshold, 6),
        "tp": tp,
        "fp": fp,
        "recall": round(tp / len(positive), 6) if positive else None,
        "precision": round(tp / (tp + fp), 6) if tp + fp else 1.0,
    }


def calibrate_family(
    positive: list[float],
    negative: list[float],
    *,
    recall_target: float = RECALL_TARGET,
    precision_target: float = PRECISION_TARGET,
    refined_rules: bool = False,
    enforcement_floor: float | None = None,
) -> dict[str, Any]:
    """Select triage/enforcement candidates for one family's dev scores.

    `refined_rules` applies the CL-68 free-recall triage and the
    fail-run-above-every-negative rule (module docstring).

    `enforcement_floor` (CL-78): the quarantine point must lie strictly
    above it. Geometric passes its non-structure score ceiling, so
    quantization alone can never be calibrated into withholding.
    """
    if not positive or not negative:
        raise ValueError("calibration needs positive and negative development scores")
    candidates = _candidates([*positive, *negative])
    triage = None
    for candidate in candidates:  # highest candidate meeting recall target
        if _metrics(positive, negative, candidate)["recall"] >= recall_target:
            triage = candidate
    if triage is None:
        raise ValueError("no candidate meets the triage recall target")
    if refined_rules:
        admitted = _metrics(positive, negative, triage)["fp"]
        triage = min(
            c
            for c in candidates
            if c <= triage and _metrics(positive, negative, c)["fp"] == admitted
        )
    floor = triage if enforcement_floor is None else max(triage, enforcement_floor)
    stricter = [c for c in candidates if c > floor]
    quarantine = next(
        (
            c
            for c in stricter
            if _metrics(positive, negative, c)["precision"] >= precision_target
        ),
        None,
    )
    if quarantine is None:
        raise ValueError("no candidate meets the enforcement precision target")
    fail_floor = max(quarantine, max(negative)) if refined_rules else quarantine
    fail = next(
        (
            c
            for c in candidates
            if c > fail_floor
            and _metrics(positive, negative, c)["precision"] >= precision_target
        ),
        1.0,
    )
    return {
        "triage_flag_at": round(triage, 6),
        "enforcement_quarantine_at": round(quarantine, 6),
        "enforcement_fail_run_at": round(fail, 6),
        "at_triage": _metrics(positive, negative, triage),
        "at_quarantine": _metrics(positive, negative, quarantine),
        "at_fail_run": _metrics(positive, negative, fail),
        "development": {
            "positives": len(positive),
            "negatives": len(negative),
            "positive_scores": [round(s, 6) for s in sorted(positive)],
            "negative_max": round(max(negative), 6),
        },
        "selection_rules": dict(CL68_RULES if refined_rules else CL27_RULES),
    }


def calibrate_thresholds(
    fixtures: Iterable[Fixture | GeoFixture],
    assignments: dict[str, str],
    *,
    recall_target: float = RECALL_TARGET,
    precision_target: float = PRECISION_TARGET,
) -> dict[str, Any]:
    """Calibrate all families from development (train/calibration) fixtures.

    Raises if any supplied fixture is assigned `held_out`: those
    labels are scorer-only and must never tune thresholds (C-07).
    """
    rows = list(fixtures)
    for fixture in rows:
        split = assignments.get(fixture.fixture_id)
        if split not in SPLITS:
            raise ValueError(f"fixture {fixture.fixture_id} has no split assignment")
        if split == "held_out":
            raise ValueError(
                "calibration must never use held-out labels (C-07): "
                f"{fixture.fixture_id} is held_out"
            )
    scores: dict[str, dict[str, list[float]]] = {
        family: {"positive": [], "negative": []} for family in FAMILIES
    }
    bands: dict[str, set[str]] = {family: set() for family in FAMILIES}
    textures: dict[str, set[str]] = {family: set() for family in FAMILIES}
    band_positive: dict[str, dict[str, list[float]]] = {
        family: {} for family in FAMILIES
    }
    # Calibration stays pinned to the detectors the frozen points were
    # calibrated for (CL-61 second detectors never tune these points).
    calibrated_detectors = {
        "lsb-pov-chisquare",
        "dct-coefficient-pov-chisquare",
        "metadata-ancillary-entries",
        GEO_DETECTOR_NAME,
    }
    prime_detector_scores(f.data for f in rows)
    for fixture in rows:
        for family, detector_name, score in detector_scores(fixture.data):
            if detector_name not in calibrated_detectors:
                continue
            bucket = scores[family]
            if fixture.family == family or family == "metadata":
                # Family fixtures score their own family; every parsed
                # fixture also yields a metadata score-0/evidence row,
                # but metadata calibration uses CL-22 fixtures only.
                if family == "metadata" and fixture.family != "metadata":
                    continue
                textures[family].add(texture_of(fixture))
                if fixture.role == "encoded":
                    band = (
                        "symbol_sequence"
                        if isinstance(fixture, GeoFixture)
                        else fixture.payload_band
                    )
                    bucket["positive"].append(score)
                    bands[family].add(band)
                    band_positive[family].setdefault(band, []).append(score)
                elif fixture.role in ("clean", "negative"):
                    bucket["negative"].append(score)
    families: dict[str, Any] = {}
    thresholds: dict[str, FamilyThresholds] = {}
    for family in FAMILIES:
        refined = family in REFINED_RULE_FAMILIES
        calibrated = calibrate_family(
            scores[family]["positive"],
            scores[family]["negative"],
            recall_target=recall_target,
            precision_target=precision_target,
            refined_rules=refined,
            enforcement_floor=(
                NON_STRUCTURE_SCORE_CEILING if family == "geometric" else None
            ),
        )
        if (
            refined
            and band_positive[family].get("low")
            and any(band_positive[family].get(b) for b in ("medium", "high"))
        ):
            # Owners' decision support (CL-68): where triage would sit
            # if the low band were not claimed, and the low-band
            # development recall that would cost.
            without_low = [
                s
                for band, values in band_positive[family].items()
                if band != "low"
                for s in values
            ]
            alternative = calibrate_family(
                without_low,
                scores[family]["negative"],
                recall_target=recall_target,
                precision_target=precision_target,
                refined_rules=True,
            )
            low = band_positive[family]["low"]
            calibrated["alternative_triage_without_low_band"] = {
                "flag_at": alternative["triage_flag_at"],
                "development_low_band_recall": round(
                    sum(1 for s in low if s >= alternative["triage_flag_at"])
                    / len(low),
                    6,
                ),
                "development_negatives_flagged": sum(
                    1
                    for s in scores[family]["negative"]
                    if s >= alternative["triage_flag_at"]
                ),
                "shipped": False,
            }
        if family == "geometric":
            # Geometric evidence supports withholding, not a run-failure claim.
            # Its score is capped below 1; reserve fail_run until severity is calibrated.
            calibrated["enforcement_fail_run_at"] = 1.0
            calibrated["at_fail_run"] = _metrics(
                scores[family]["positive"], scores[family]["negative"], 1.0
            )
            calibrated["fail_run_policy"] = (
                "reserved_unreachable_pending_severity_calibration"
            )
        families[family] = {
            **calibrated,
            "calibrated_textures": sorted(textures[family]),
            "calibrated_payload_bands": sorted(bands[family]),
            "uncalibrated_payload_bands": sorted(
                {"low", "medium", "high"} - bands[family]
            ),
        }
        thresholds[family] = FamilyThresholds(
            family,
            "frozen",
            calibrated["triage_flag_at"],
            calibrated["enforcement_quarantine_at"],
            calibrated["enforcement_fail_run_at"],
        )
    config = ThresholdConfig(version=FROZEN_CONFIG_VERSION, families=thresholds)
    return {
        "schema": CALIBRATION_SCHEMA,
        "schema_version": 1,
        "calibration_version": CALIBRATION_VERSION,
        "geometric_detector": {
            "version": GEO_DETECTOR_VERSION,
            "config": DEFAULT_GEO_CONFIG.to_dict(),
        },
        "frozen_config_version": FROZEN_CONFIG_VERSION,
        "targets": {
            "triage_recall_at_least": recall_target,
            "enforcement_precision_at_least": precision_target,
        },
        "development_only": True,
        "held_out_labels_used": False,
        "development_fixture_ids": sorted(f.fixture_id for f in rows),
        "development_dataset_hash": dataset_hash(rows),
        "families": families,
        "threshold_config": config.to_dict(),
    }


def development_calibration_data() -> tuple[list[Fixture | GeoFixture], dict[str, str]]:
    """Reproducible four-family development input, excluding held-out rows.

    CL-68: the CL-9/CL-22 suites plus the banded suite, restricted to
    each family's calibrated textures (`CALIBRATED_TEXTURES`).
    """
    from .banded_fixtures import build_banded_dataset
    from .fixtures import build_dataset
    from .geo_calibration import geometric_calibration_dataset
    from .metadata_fixtures import build_metadata_dataset
    from .splits import assign_splits

    fixtures: list[Fixture | GeoFixture] = []
    assignments: dict[str, str] = {}
    banded = build_banded_dataset()
    suites: list[tuple[list[Fixture], dict[str, str]]] = [
        (dataset, assign_splits(dataset))
        for dataset in (build_dataset(), build_metadata_dataset())
    ]
    suites.append((list(banded.fixtures), banded.assignments))
    for dataset, split in suites:
        assignments.update(split)
        fixtures.extend(
            f
            for f in dataset
            if split[f.fixture_id] != "held_out"
            and texture_of(f) in CALIBRATED_TEXTURES.get(f.family, ALL_TEXTURES)
        )
    geo, split = geometric_calibration_dataset()
    assignments.update(split)
    fixtures.extend(f for f in geo if split[f.fixture_id] != "held_out")
    return fixtures, assignments


FROZEN_CONFIG_ENV = "COVERTLENS_FROZEN_CONFIG"


def load_frozen_thresholds(
    path: str | Path | None = None,
) -> tuple[ThresholdConfig, dict[str, Any]]:
    """Load the owners' frozen config + its calibration provenance.

    With no explicit `path`, the `COVERTLENS_FROZEN_CONFIG`
    environment variable selects the file (CL-65) — this is how a
    campaign rolls back to a previous freeze — and the shipped
    `config/frozen-thresholds.json` is the default.
    """
    if path is None:
        env_path = os.environ.get(FROZEN_CONFIG_ENV)
        path = Path(env_path) if env_path else FROZEN_PATH
    doc = json.loads(Path(path).read_text())
    config_doc = doc["threshold_config"]
    families = {}
    for family, block in (config_doc.get("families") or {}).items():
        families[family] = FamilyThresholds(
            family,
            block["status"],
            (block.get("triage") or {}).get("flag_at"),
            (block.get("enforcement") or {}).get("quarantine_at"),
            (block.get("enforcement") or {}).get("fail_run_at"),
        )
    config = ThresholdConfig(
        version=config_doc["version"],
        ladder_version=config_doc.get("ladder_version", "1.0.0"),
        families=families,
    )
    return config, doc


def validate_calibration(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a calibration report; empty is valid."""
    errors: list[str] = []

    need = make_need(errors)

    need(
        report.get("schema") == CALIBRATION_SCHEMA,
        f"schema must be {CALIBRATION_SCHEMA}",
    )
    need(
        report.get("held_out_labels_used") is False,
        "calibration must not use held-out labels (C-07)",
    )
    need(report.get("development_only") is True, "calibration must be development-only")
    targets = report.get("targets") or {}
    for family in FAMILIES:
        block = (report.get("families") or {}).get(family)
        need(block is not None, f"families.{family} is required")
        if block is None:
            continue
        need(
            block["triage_flag_at"]
            <= block["enforcement_quarantine_at"]
            <= block["enforcement_fail_run_at"],
            f"families.{family} points must be ordered",
        )
        need(
            (block.get("at_triage") or {}).get("recall", 0)
            >= targets.get("triage_recall_at_least", 2),
            f"families.{family} triage must meet the recall target on development data",
        )
        need(
            (block.get("at_quarantine") or {}).get("precision", 0)
            >= targets.get("enforcement_precision_at_least", 2),
            f"families.{family} enforcement must meet the precision target on development data",
        )
    return errors
