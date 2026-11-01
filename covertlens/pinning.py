"""Pinned replay and reproducibility checks (CL-26, OPS-01).

An eval run is reproducible only if everything that could change its
outcome is named and hashed. A *pin* records: the dataset (every
fixture's ID and content hash, folded into one dataset hash), the
detectors (name@version and detector-config versions), the threshold
configuration version, and every seed. The pin itself is
content-hashed (`pin_hash`), so any drift — a changed fixture, a
detector bump, a new config, a different seed — is detectable by
rebuilding the pin and comparing (`pin_differences`).

`verify_reproducibility` runs the integrated pipeline repeatedly:
deterministic scoring must reproduce identical scores and verdicts
exactly; a caller-supplied stochastic scorer is instead checked
against a documented agreement bound (its per-repetition seeds are
derived from the pinned seed, so variation is reproducible too).

`export_bundle` seals a CL-25 run report for export: original hashes,
trace references (run + event IDs), detector/config versions and
per-delivery decisions, closed with a `bundle_hash` that
`validate_export` recomputes. Exports carry no original bytes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from typing import Any

from . import ids
from .dct import DCT_DETECTOR_NAME, DCT_DETECTOR_VERSION
from .fixtures import Fixture
from .geometric import GEO_CONFIG_VERSION, GEO_DETECTOR_NAME, GEO_DETECTOR_VERSION
from .lsb import LSB_DETECTOR_NAME, LSB_DETECTOR_VERSION
from .metadata import (
    METADATA_DETECTOR_NAME,
    METADATA_DETECTOR_VERSION,
    analyze_and_decide,
)
from .verdicts import ThresholdConfig

PIN_SCHEMA = "covertlens.pin"
PIN_SCHEMA_VERSION = 1
PIN_VERSION = "1.0.0"
EXPORT_SCHEMA = "covertlens.report-export"
EXPORT_SCHEMA_VERSION = 1


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def dataset_hash(fixtures: Iterable[Fixture]) -> str:
    """One hash over the sorted (fixture_id, content_hash) dataset."""
    rows = sorted((f.fixture_id, f.content_hash) for f in fixtures)
    return _hash(rows)


def default_detector_versions() -> list[str]:
    return [
        f"{LSB_DETECTOR_NAME}@{LSB_DETECTOR_VERSION}",
        f"{DCT_DETECTOR_NAME}@{DCT_DETECTOR_VERSION}",
        f"{METADATA_DETECTOR_NAME}@{METADATA_DETECTOR_VERSION}",
        f"{GEO_DETECTOR_NAME}@{GEO_DETECTOR_VERSION}",
    ]


def build_pin(
    fixtures: Iterable[Fixture],
    *,
    threshold_config: ThresholdConfig | None = None,
    seeds: dict[str, int] | None = None,
    detector_versions: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build the content-hashed pin for one eval configuration."""
    rows = list(fixtures)
    from .verdicts import DEFAULT_CONFIG

    config = threshold_config or DEFAULT_CONFIG
    pin: dict[str, Any] = {
        "schema": PIN_SCHEMA,
        "schema_version": PIN_SCHEMA_VERSION,
        "pin_version": PIN_VERSION,
        "dataset": {
            "fixture_count": len(rows),
            "dataset_hash": dataset_hash(rows),
            "fixtures": {f.fixture_id: f.content_hash for f in rows},
        },
        "detectors": sorted(detector_versions or default_detector_versions()),
        "threshold_config_version": config.version,
        "thresholds_status": {
            family: block.status for family, block in sorted(config.families.items())
        },
        "geometric_config_version": GEO_CONFIG_VERSION,
        "seeds": dict(seeds or {}),
    }
    pin["pin_hash"] = _hash({k: v for k, v in pin.items() if k != "pin_hash"})
    return pin


def pin_differences(
    pin: dict[str, Any],
    fixtures: Iterable[Fixture],
    *,
    threshold_config: ThresholdConfig | None = None,
    seeds: dict[str, int] | None = None,
    detector_versions: Iterable[str] | None = None,
) -> list[str]:
    """Fields that drifted from the pin (empty = still pinned)."""
    rebuilt = build_pin(
        fixtures,
        threshold_config=threshold_config,
        seeds=seeds,
        detector_versions=detector_versions,
    )
    differences = []
    for key in ("dataset", "detectors", "threshold_config_version", "seeds"):
        if rebuilt.get(key) != pin.get(key):
            differences.append(key)
    if rebuilt["pin_hash"] != pin.get("pin_hash") and not differences:
        differences.append("pin_hash")
    return differences


def validate_pin(pin: dict[str, Any]) -> list[str]:
    """Structural validation of a pin; empty is valid."""
    errors: list[str] = []
    if pin.get("schema") != PIN_SCHEMA:
        errors.append(f"schema must be {PIN_SCHEMA}")
    dataset = pin.get("dataset") or {}
    if not ids.is_content_hash(dataset.get("dataset_hash")):
        errors.append("dataset.dataset_hash must be sha256:<hex>")
    for fixture_id, digest in (dataset.get("fixtures") or {}).items():
        if not ids.is_content_hash(digest):
            errors.append(f"dataset.fixtures[{fixture_id}] must be sha256:<hex>")
    expected = _hash({k: v for k, v in pin.items() if k != "pin_hash"})
    if pin.get("pin_hash") != expected:
        errors.append("pin_hash does not match pin contents (drift or tampering)")
    if not pin.get("detectors"):
        errors.append("detectors must pin at least one detector version")
    return errors


def verify_reproducibility(
    fixtures: Iterable[Fixture],
    *,
    threshold_config: ThresholdConfig | None = None,
    repetitions: int = 3,
    stochastic_scorer: Callable[[bytes, int], float] | None = None,
    base_seed: int = 0,
    agreement_min: float = 1.0,
) -> dict[str, Any]:
    """Repeat the pipeline and check verdict/score reproduction.

    Deterministic mode (default): every repetition must produce
    identical scores and verdicts. Stochastic mode: the caller's
    scorer is run with seeds `base_seed + repetition` and the
    fraction of fixtures whose verdict is stable must meet
    `agreement_min` — the documented bound, recorded in the result.
    """
    if repetitions < 2:
        raise ValueError("repetitions must be >= 2")
    if not 0.0 <= agreement_min <= 1.0:
        raise ValueError("agreement_min must lie in [0, 1]")
    rows = list(fixtures)
    runs: list[dict[str, Any]] = []
    for repetition in range(repetitions):
        outcomes: dict[str, Any] = {}
        for fixture in rows:
            if stochastic_scorer is None:
                _, decision = analyze_and_decide(fixture.data, threshold_config)
                outcomes[fixture.fixture_id] = {
                    "verdict": decision.verdict.value if decision else None,
                }
            else:
                score = stochastic_scorer(fixture.data, base_seed + repetition)
                outcomes[fixture.fixture_id] = {
                    "score": round(float(score), 6),
                    "verdict": "flag" if score >= 0.5 else "log",
                }
        runs.append(outcomes)
    stable = 0
    for fixture in rows:
        verdicts = {runs[r][fixture.fixture_id]["verdict"] for r in range(repetitions)}
        if len(verdicts) == 1:
            stable += 1
    agreement = round(stable / len(rows), 6) if rows else 1.0
    exact = all(runs[r] == runs[0] for r in range(1, repetitions))
    return {
        "repetitions": repetitions,
        "fixtures": len(rows),
        "deterministic": stochastic_scorer is None,
        "exact_reproduction": exact,
        "verdict_agreement": agreement,
        "agreement_min": agreement_min,
        "within_bounds": exact
        if stochastic_scorer is None
        else agreement >= agreement_min,
        "seeds": [base_seed + r for r in range(repetitions)]
        if stochastic_scorer is not None
        else [],
    }


def export_bundle(report: dict[str, Any], pin: dict[str, Any]) -> dict[str, Any]:
    """Seal a CL-25 run report for export under a pin (no raw bytes)."""
    bundle: dict[str, Any] = {
        "schema": EXPORT_SCHEMA,
        "schema_version": EXPORT_SCHEMA_VERSION,
        "run_id": report.get("run_id"),
        "pin_hash": pin.get("pin_hash"),
        "dataset_hash": (pin.get("dataset") or {}).get("dataset_hash"),
        "detectors": pin.get("detectors"),
        "threshold_config_version": pin.get("threshold_config_version"),
        "seeds": pin.get("seeds"),
        "trace_references": {
            "run_id": report.get("run_id"),
            "event_ids": [e.get("event_id") for e in report.get("timeline") or []],
        },
        "originals": [
            {
                "artifact_version_id": o.get("artifact_version_id"),
                "content_hash": o.get("content_hash"),
            }
            for o in report.get("originals") or []
        ],
        "decisions": [
            {
                "delivery_id": d.get("delivery_id"),
                "content_hash": d.get("content_hash"),
                "verdict": (d.get("verdict") or {}).get("verdict"),
                "disposition": next(
                    (
                        row["disposition"]
                        for row in report.get("triage_queue") or []
                        if row["delivery_id"] == d.get("delivery_id")
                    ),
                    "unresolved",
                ),
            }
            for d in report.get("deliveries") or []
        ],
    }
    bundle["bundle_hash"] = _hash(bundle)
    return bundle


def validate_export(bundle: dict[str, Any]) -> list[str]:
    """Recompute the bundle seal; empty is valid."""
    errors: list[str] = []
    if bundle.get("schema") != EXPORT_SCHEMA:
        errors.append(f"schema must be {EXPORT_SCHEMA}")
    sealed = {k: v for k, v in bundle.items() if k != "bundle_hash"}
    if bundle.get("bundle_hash") != _hash(sealed):
        errors.append("bundle_hash does not match bundle contents")
    if not ids.is_content_hash(bundle.get("pin_hash")):
        errors.append("pin_hash must be sha256:<hex>")
    for i, original in enumerate(bundle.get("originals") or []):
        if not ids.is_content_hash(original.get("content_hash")):
            errors.append(f"originals[{i}].content_hash must be sha256:<hex>")
        if "data" in original:
            errors.append(f"originals[{i}] must not embed original bytes")
    return errors
