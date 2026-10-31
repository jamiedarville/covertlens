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
from pathlib import Path
from typing import Any, Iterable

from .fixtures import Fixture
from .metadata import analyze_all_bytes
from .pinning import dataset_hash
from .splits import SPLITS
from .verdicts import FamilyThresholds, ThresholdConfig

CALIBRATION_SCHEMA = "covertlens.calibration"
CALIBRATION_VERSION = "1.0.0"
FROZEN_CONFIG_VERSION = "frozen-1.0.0"
FROZEN_PATH = Path(__file__).resolve().parent.parent / "config" / "frozen-thresholds.json"
RECALL_TARGET = 0.95
PRECISION_TARGET = 0.99
FAMILIES = ("spatial_lsb", "jpeg_dct", "metadata")


def _candidates(scores: list[float]) -> list[float]:
    unique = sorted(set(scores))
    points = set(unique)
    for low, high in zip(unique, unique[1:]):
        points.add(round((low + high) / 2.0, 6))
    return sorted(points)


def _metrics(positive: list[float], negative: list[float], threshold: float) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """Select triage/enforcement candidates for one family's dev scores."""
    if not positive or not negative:
        raise ValueError("calibration needs positive and negative development scores")
    candidates = _candidates([*positive, *negative])
    triage = None
    for candidate in candidates:  # highest candidate meeting recall target
        if _metrics(positive, negative, candidate)["recall"] >= recall_target:
            triage = candidate
    if triage is None:
        raise ValueError("no candidate meets the triage recall target")
    stricter = [c for c in candidates if c > triage]
    quarantine = next(
        (c for c in stricter
         if _metrics(positive, negative, c)["precision"] >= precision_target),
        None,
    )
    if quarantine is None:
        raise ValueError("no candidate meets the enforcement precision target")
    fail = next(
        (c for c in candidates
         if c > quarantine
         and _metrics(positive, negative, c)["precision"] >= precision_target),
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
    }


def calibrate_thresholds(
    fixtures: Iterable[Fixture],
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
    for fixture in rows:
        result = analyze_all_bytes(fixture.data)
        for finding in result.findings:
            bucket = scores[finding.family]
            if fixture.family == finding.family or finding.family == "metadata":
                # Family fixtures score their own family; every parsed
                # fixture also yields a metadata score-0/evidence row,
                # but metadata calibration uses CL-22 fixtures only.
                if finding.family == "metadata" and fixture.family != "metadata":
                    continue
                if fixture.role == "encoded":
                    bucket["positive"].append(finding.score)
                    bands[finding.family].add(fixture.payload_band)
                elif fixture.role in ("clean", "negative"):
                    bucket["negative"].append(finding.score)
    families: dict[str, Any] = {}
    thresholds: dict[str, FamilyThresholds] = {}
    for family in FAMILIES:
        calibrated = calibrate_family(
            scores[family]["positive"], scores[family]["negative"],
            recall_target=recall_target, precision_target=precision_target,
        )
        families[family] = {
            **calibrated,
            "calibrated_payload_bands": sorted(bands[family]),
            "uncalibrated_payload_bands": sorted(
                {"low", "medium", "high"} - bands[family]
            ),
        }
        thresholds[family] = FamilyThresholds(
            family, "frozen",
            calibrated["triage_flag_at"],
            calibrated["enforcement_quarantine_at"],
            calibrated["enforcement_fail_run_at"],
        )
    config = ThresholdConfig(version=FROZEN_CONFIG_VERSION, families=thresholds)
    return {
        "schema": CALIBRATION_SCHEMA,
        "schema_version": 1,
        "calibration_version": CALIBRATION_VERSION,
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


def load_frozen_thresholds(
    path: str | Path | None = None,
) -> tuple[ThresholdConfig, dict[str, Any]]:
    """Load the owners' frozen config + its calibration provenance."""
    doc = json.loads(Path(path or FROZEN_PATH).read_text())
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

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == CALIBRATION_SCHEMA, f"schema must be {CALIBRATION_SCHEMA}")
    need(report.get("held_out_labels_used") is False, "calibration must not use held-out labels (C-07)")
    need(report.get("development_only") is True, "calibration must be development-only")
    targets = report.get("targets") or {}
    for family in FAMILIES:
        block = (report.get("families") or {}).get(family)
        need(block is not None, f"families.{family} is required")
        if block is None:
            continue
        need(
            block["triage_flag_at"] <= block["enforcement_quarantine_at"]
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
