import json

import pytest

from covertlens.calibration import (
    calibrate_thresholds,
    development_calibration_data,
    load_frozen_thresholds,
    validate_calibration,
)
from covertlens.fixtures import build_dataset
from covertlens.parsing import Finding
from covertlens.splits import assign_splits
from covertlens.verdicts import decide_verdict


def _dev():
    return development_calibration_data()


def test_calibration_uses_development_data_only():
    fixtures, assignments = _dev()
    report = calibrate_thresholds(fixtures, assignments)
    assert validate_calibration(report) == []
    assert report["held_out_labels_used"] is False
    assert report["targets"] == {
        "triage_recall_at_least": 0.95,
        "enforcement_precision_at_least": 0.99,
    }
    for family in ("spatial_lsb", "jpeg_dct", "metadata"):
        block = report["families"][family]
        # Triage is high-recall, enforcement is high-precision (C-06).
        assert block["at_triage"]["recall"] >= 0.95
        assert block["at_quarantine"]["precision"] >= 0.99
        assert block["triage_flag_at"] <= block["enforcement_quarantine_at"]
        # The high band is absent from development splits: coverage
        # is narrowed, never silently extended.
        assert block["calibrated_payload_bands"] == ["low", "medium"]
        assert block["uncalibrated_payload_bands"] == ["high"]


def test_calibration_rejects_held_out_labels():
    dataset = build_dataset()
    assignments = assign_splits(dataset)
    with pytest.raises(ValueError, match="held-out"):
        calibrate_thresholds(dataset, assignments)


def test_shipped_freeze_matches_recalibration_and_is_enforceable():
    fixtures, assignments = _dev()
    report = calibrate_thresholds(fixtures, assignments)
    config, frozen = load_frozen_thresholds()
    assert frozen["threshold_config"] == report["threshold_config"]
    assert frozen["families"] == report["families"]
    assert frozen["development_dataset_hash"] == report["development_dataset_hash"]
    assert frozen["geometric_detector"] == report["geometric_detector"]
    assert config.version == "frozen-1.1.0"
    assert all(fam.status == "frozen" for fam in config.families.values())
    # A frozen config changes CL-17 behaviour: enforcement points are
    # no longer log-only.
    finding = Finding(
        family="metadata",
        detector_name="metadata-ancillary-entries",
        detector_version="1.0.0",
        score=0.95,
        coverage={"entries": 1},
    )
    decision = decide_verdict([finding], config)
    assert decision.verdict.value == "fail_run"
    assert decision.enforceable is True


def test_calibration_schema_accepts_frozen_artifact():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema = json.loads(open("schemas/calibration.schema.json").read())
    _, frozen = load_frozen_thresholds()
    jsonschema.validate(frozen, schema)
