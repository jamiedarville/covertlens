import copy
from dataclasses import replace

import pytest

from covertlens.review_export import (
    run_export_verification,
    validate_review_package,
)
from covertlens.runtime import AuditLog


@pytest.fixture(scope="module")
def verification():
    return run_export_verification()


def test_package_contains_findings_versions_hashes_policy_dispositions(verification):
    package = verification["package"]
    assert verification["package_valid"] is True
    assert validate_review_package(package) == []
    assert package["contains_raw_bytes"] is False
    assert package["originals"], "package must carry originals"
    for original in package["originals"]:
        assert original["content_hash"].startswith("sha256:")
        assert original["artifact_version_id"]
        assert "findings" in original
    policy = package["policy"]
    assert policy["runtime_policy_version"]
    assert policy["threshold_config_version"]
    assert policy["pin_hash"].startswith("sha256:")
    assert policy["dataset_hash"].startswith("sha256:")
    dispositions = {d["delivery_id"]: d["disposition"] for d in package["decisions"]}
    assert "suspected" in dispositions.values()
    assert all(dispositions.values()), "every decision carries a disposition"


def test_reads_and_exports_appear_in_audit_logs(verification):
    checks = verification["verification"]
    assert verification["researcher_read_ok"] is True
    assert checks["audit_chain_valid"] is True
    assert checks["evidence_reads_logged"] >= 1
    assert checks["exports_logged"] == 1
    assert checks["store_access_records"] >= 1
    assert checks["store_hash_verified"] is True
    assert checks["denied_attempts_logged"] >= 4


def test_permissions_prevent_unauthorized_evidence_access(verification):
    # Run agents hold no evidence permissions; a researcher scoped
    # to a different dataset is equally denied here.
    assert verification["denials"] == {
        "agent_read": True,
        "agent_export": True,
        "wrong_dataset_read": True,
        "wrong_dataset_export": True,
    }


def test_tampered_package_and_audit_chain_are_detected(verification):
    package = copy.deepcopy(verification["package"])
    package["decisions"][0]["disposition"] = "benign"
    assert any("seal" in e for e in validate_review_package(package))

    log = AuditLog()
    entry = log.append(actor_id="researcher-1", action="evidence.read",
                       dataset_id="ds-pilot", outcome="allowed")
    assert log.verify_chain() is True
    log._entries[0] = replace(entry, actor_id="mallory")
    assert log.verify_chain() is False
