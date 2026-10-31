import pytest

from covertlens.handoff import run_handoff_verification, validate_handoff


@pytest.fixture(scope="module")
def report():
    return run_handoff_verification()


def test_threshold_operations_and_rollback(report):
    ops = report["threshold_operations"]
    assert ops["frozen_enforceable"] is True
    assert ops["frozen_verdict_at_0.95"] == "fail_run"
    # Rolling back to the pre-freeze shipped config restores the
    # log-only behaviour; the pin names the drifted field.
    assert ops["rollback_enforceable"] is False
    assert ops["rollback_verdict_at_0.95"] == "log"
    assert "threshold_config_version" in ops["drift_fields_when_config_changes"]


def test_quarantine_handling_and_immutable_verdict(report):
    checks = report["quarantine_handling"]
    assert checks["recipient_denied"] is True
    assert checks["reviewer_served"] is True
    assert checks["verdict_immutable_once_recorded"] is True
    assert checks["override_recorded_with_reason"] is True
    assert checks["agent_override_denied"] is True
    assert checks["audit_chain_valid"] is True


def test_infrastructure_rerun_and_retirement(report):
    assert validate_handoff(report) == []
    assert report["infrastructure_errors"]["delivery_withheld"] is True
    assert report["reruns"]["replay_repeatable"] is True
    assert report["reruns"]["reproducibility_exact"] is True
    retirement = report["dataset_retirement"]
    assert retirement["self_approval_denied"] is True
    assert retirement["final_state"] == "deleted"
    assert retirement["bundle_content_hashes"] >= 1
