"""Allowed-channel manifest: loading and validation (CL-7, EV-02).

The manifest is the single codified statement of the eval rule: which
channel is allowed, which image channels are monitored, in which detector
mode, against which (separately configured) triage and enforcement
operating points, and what happens on every error class. Threshold values
stay ``unfrozen_placeholder`` until CL-27 freezes them; this module
validates structure and fail-closed behaviour, never invented numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FAMILIES = ("spatial_lsb", "jpeg_dct", "metadata", "geometric")
DETECTOR_MODES = ("enabled", "log_only", "disabled")
FAIL_CLOSED = "no_clean_verdict_withhold"
ERROR_CLASSES = (
    "corrupt_input",
    "unsupported_format",
    "oversized_input",
    "analysis_timeout",
    "detector_error",
    "gate_error",
)

_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "allowed-channel-manifest.json"


def default_manifest_path() -> Path:
    return _DEFAULT


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _DEFAULT
    with target.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return validation errors; an empty list means the manifest is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(isinstance(manifest.get("manifest_id"), str) and bool(manifest["manifest_id"]),
         "manifest_id is required")
    version = manifest.get("manifest_version", "")
    need(isinstance(version, str) and len(version.split(".")) == 3
         and all(p.isdigit() for p in version.split(".")),
         "manifest_version must be semantic (x.y.z)")
    owner = manifest.get("owner") or {}
    need(bool(owner.get("team")), "owner.team is required (eval-rule owner)")
    need(bool(manifest.get("eval_rule")), "eval_rule is required")

    scope = manifest.get("scope") or {}
    kinds = scope.get("artifact_kinds") or []
    need(set(kinds) <= {"png", "jpeg"} and bool(kinds),
         "scope.artifact_kinds must be a non-empty subset of png/jpeg")
    need(scope.get("analysis_input") == "original_bytes_only",
         "scope.analysis_input must be original_bytes_only (C-05)")

    allowed = manifest.get("allowed_channel") or {}
    need(bool(allowed.get("id")), "allowed_channel.id is required")

    channels = manifest.get("channels") or []
    by_family = {c.get("family"): c for c in channels if isinstance(c, dict)}
    for family in FAMILIES:
        need(family in by_family, f"channel family missing: {family}")
    for family, channel in by_family.items():
        prefix = f"channels[{family}]"
        detector = channel.get("detector") or {}
        need(detector.get("mode") in DETECTOR_MODES,
             f"{prefix}.detector.mode must be one of {DETECTOR_MODES}")
        need(detector.get("input") == "original_bytes",
             f"{prefix}.detector.input must be original_bytes")
        thresholds = channel.get("thresholds") or {}
        need(thresholds.get("status") in ("unfrozen_placeholder", "frozen"),
             f"{prefix}.thresholds.status is required")
        triage = thresholds.get("triage") or {}
        enforcement = thresholds.get("enforcement") or {}
        need(triage.get("operating_point") == "high_recall",
             f"{prefix}.thresholds.triage must be the high_recall point")
        need(enforcement.get("operating_point") == "high_precision",
             f"{prefix}.thresholds.enforcement must be the high_precision point (C-06)")
        if thresholds.get("status") == "frozen":
            flag_at, quar_at = triage.get("flag_at"), enforcement.get("quarantine_at")
            need(isinstance(flag_at, (int, float)) and isinstance(quar_at, (int, float)),
                 f"{prefix} frozen thresholds need numeric flag_at/quarantine_at")
            if isinstance(flag_at, (int, float)) and isinstance(quar_at, (int, float)):
                need(quar_at >= flag_at,
                     f"{prefix} enforcement quarantine_at must be >= triage flag_at")
        behaviour = channel.get("error_behavior") or {}
        for key in ("on_parse_error", "on_detector_error", "on_timeout"):
            need(behaviour.get(key) == FAIL_CLOSED,
                 f"{prefix}.error_behavior.{key} must be {FAIL_CLOSED}")
        need(behaviour.get("equated_with_collusion") is False,
             f"{prefix}.error_behavior must not equate errors with collusion (C-02)")

    ladder = {row.get("verdict"): row.get("delivery")
              for row in manifest.get("verdict_ladder") or [] if isinstance(row, dict)}
    need(ladder.get("log") == "permit" and ladder.get("flag") == "permit",
         "verdict ladder: log and flag must permit delivery (ENF-01)")
    need(ladder.get("quarantine") == "withhold" and ladder.get("fail_run") == "withhold",
         "verdict ladder: quarantine and fail_run must withhold delivery (ENF-01)")

    global_errors = manifest.get("error_behavior") or {}
    classes = global_errors.get("classes") or {}
    for error_class in ERROR_CLASSES:
        need(classes.get(error_class) == FAIL_CLOSED,
             f"error_behavior.classes.{error_class} must be {FAIL_CLOSED}")
    need(global_errors.get("equated_with_collusion") is False,
         "error_behavior must not equate errors with collusion (C-02)")
    return errors


def channel_families(manifest: dict[str, Any]) -> list[str]:
    return [c["family"] for c in manifest.get("channels", [])]
