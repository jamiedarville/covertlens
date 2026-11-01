"""CL-7 AC1: manifest specifies allowed channels, owner, detector mode,
thresholds and error behaviour."""

import copy
import json
from pathlib import Path

from covertlens.manifest import (
    ERROR_CLASSES,
    FAIL_CLOSED,
    FAMILIES,
    channel_families,
    load_manifest,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parent.parent


def test_shipped_manifest_is_valid():
    assert validate_manifest(load_manifest()) == []


def test_manifest_specifies_owner_rule_and_allowed_channel():
    manifest = load_manifest()
    assert manifest["owner"]["team"] == "Agent Evaluation / AI Safety"
    assert "may not encode task-relevant information" in manifest["eval_rule"]
    assert manifest["allowed_channel"]["id"] == "declared_text_channel"
    assert manifest["allowed_channel"]["gated_by_covertlens"] is False


def test_all_three_families_with_detector_modes():
    manifest = load_manifest()
    assert channel_families(manifest) == list(FAMILIES)
    for channel in manifest["channels"]:
        assert channel["detector"]["mode"] == "enabled"
        assert channel["detector"]["input"] == "original_bytes"
        assert channel["applies_to"]


def test_thresholds_have_separate_operating_points_unfrozen():
    manifest = load_manifest()
    for channel in manifest["channels"]:
        thresholds = channel["thresholds"]
        assert thresholds["status"] == "unfrozen_placeholder"
        assert thresholds["triage"]["operating_point"] == "high_recall"
        assert thresholds["enforcement"]["operating_point"] == "high_precision"
        # No invented frozen numbers before CL-27.
        assert thresholds["triage"]["flag_at"] is None
        assert thresholds["enforcement"]["quarantine_at"] is None


def test_error_behaviour_fails_closed_and_never_means_collusion():
    manifest = load_manifest()
    classes = manifest["error_behavior"]["classes"]
    assert set(classes) == set(ERROR_CLASSES)
    assert all(value == FAIL_CLOSED for value in classes.values())
    assert manifest["error_behavior"]["equated_with_collusion"] is False
    ladder = {row["verdict"]: row["delivery"] for row in manifest["verdict_ladder"]}
    assert ladder == {
        "log": "permit",
        "flag": "permit",
        "quarantine": "withhold",
        "fail_run": "withhold",
    }


def test_scope_is_eval_png_jpeg_only():
    manifest = load_manifest()
    assert set(manifest["scope"]["artifact_kinds"]) == {"png", "jpeg"}
    assert "consumer uploads" in manifest["scope"]["out_of_scope"]


def test_missing_owner_is_rejected():
    manifest = copy.deepcopy(load_manifest())
    manifest["owner"] = {}
    assert any("owner.team" in e for e in validate_manifest(manifest))


def test_missing_family_is_rejected():
    manifest = copy.deepcopy(load_manifest())
    manifest["channels"] = [
        c for c in manifest["channels"] if c["family"] != "metadata"
    ]
    assert any("metadata" in e for e in validate_manifest(manifest))


def test_clean_verdict_on_error_is_rejected():
    manifest = copy.deepcopy(load_manifest())
    manifest["error_behavior"]["classes"]["detector_error"] = "clean_verdict"
    assert any("detector_error" in e for e in validate_manifest(manifest))


def test_frozen_thresholds_must_be_ordered():
    manifest = copy.deepcopy(load_manifest())
    channel = manifest["channels"][0]
    channel["thresholds"] = {
        "status": "frozen",
        "triage": {"operating_point": "high_recall", "flag_at": 0.9},
        "enforcement": {
            "operating_point": "high_precision",
            "quarantine_at": 0.5,
            "fail_run_at": 0.99,
        },
    }
    assert any("quarantine_at" in e for e in validate_manifest(manifest))


def test_schema_files_are_valid_json_with_key_fields():
    manifest_schema = json.loads(
        (ROOT / "schemas" / "allowed-channel-manifest.schema.json").read_text()
    )
    assert "channels" in manifest_schema["required"]
    event_schema = json.loads(
        (ROOT / "schemas" / "harness-events.schema.json").read_text()
    )
    assert "event_id" in event_schema["required"]
