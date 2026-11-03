import json

import pytest

from covertlens.calibration import (
    CALIBRATED_TEXTURES,
    calibrate_family,
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
        # CL-68: the banded suite puts every band in development data,
        # on the family's calibrated textures only.
        assert block["calibrated_payload_bands"] == ["high", "low", "medium"]
        assert block["uncalibrated_payload_bands"] == []
        assert block["calibrated_textures"] == sorted(CALIBRATED_TEXTURES[family])
        assert block["development"]["positives"] >= 100
        assert block["selection_rules"]["fail_run"].startswith("first candidate above")
        # Fail-run sits above every development negative.
        assert block["enforcement_fail_run_at"] > block["development"]["negative_max"]
        # The no-low-band triage alternative is recorded, never shipped.
        assert block["alternative_triage_without_low_band"]["shipped"] is False
    geometric = report["families"]["geometric"]
    assert geometric["selection_rules"]["triage"] == (
        "highest candidate meeting the recall target"
    )


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
    assert config.version == "frozen-1.3.0"
    # CL-68 keeps the CL-54 geometric points exactly.
    geometric = config.for_family("geometric")
    assert (
        geometric.triage_flag_at,
        geometric.enforcement_quarantine_at,
        geometric.enforcement_fail_run_at,
    ) == (0.5, 0.708319, 1.0)
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


def test_refined_rules_take_free_recall_and_lift_fail_run_above_negatives():
    positive = [round(0.90 + i * 0.0005, 6) for i in range(100)]
    negative = [0.0] * 100
    cl27 = calibrate_family(positive, negative)
    cl68 = calibrate_family(positive, negative, refined_rules=True)
    # CL-27 triage drops ~5% of perfectly separable positives; the
    # refined rule moves down to the gap at no development FP cost.
    assert cl27["at_triage"]["recall"] < 1.0
    assert cl68["at_triage"]["recall"] == 1.0
    assert cl68["at_triage"]["fp"] == 0
    overlapping = calibrate_family(
        [0.3, 0.4, 0.5, 0.6, 0.7] * 40,
        [0.1, 0.2, 0.25, 0.45] + [0.05] * 196,
        refined_rules=True,
    )
    assert overlapping["enforcement_fail_run_at"] > 0.45
    assert (
        overlapping["enforcement_quarantine_at"]
        <= overlapping["enforcement_fail_run_at"]
    )


def test_second_detectors_stay_between_triage_and_quarantine():
    """CL-61 caps must hold under the CL-68 freeze: the unfrozen second
    detectors can flag but never withhold on their own."""
    from covertlens.dct import CAL_DEFAULT_CONFIG
    from covertlens.lsb import SPA_DEFAULT_CONFIG

    config, _ = load_frozen_thresholds()
    spatial = config.for_family("spatial_lsb")
    dct = config.for_family("jpeg_dct")
    assert SPA_DEFAULT_CONFIG.score_scale < spatial.enforcement_quarantine_at
    assert CAL_DEFAULT_CONFIG.score_cap < dct.enforcement_quarantine_at
    assert SPA_DEFAULT_CONFIG.score_scale >= spatial.triage_flag_at
    assert CAL_DEFAULT_CONFIG.score_cap >= dct.triage_flag_at
