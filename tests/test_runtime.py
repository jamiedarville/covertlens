"""CL-11 acceptance tests: internal runtime, evidence permissions and audit logging.

AC1 dataset/project permissions protect originals, traces, payloads and exports (OP-01)
AC2 evidence reads, configuration changes and overrides are audited (OP-01)
AC3 dataset retirement policy preserves reproducibility until approved deletion (OP-01)
"""

import pytest

from covertlens.fixtures import build_dataset
from covertlens.runtime import (
    AuditLog,
    DatasetRetirement,
    EvidenceGateway,
    Principal,
    RuntimeConfig,
    load_runtime_policy,
    validate_runtime_policy,
)
from covertlens.splits import assign_splits
from covertlens.store import ArtifactStore

PNG = b"\x89PNG\r\n\x1a\n" + b"runtime-test-original"
DATASET = "dataset-a"
OTHER_DATASET = "dataset-b"

RESEARCHER = Principal("researcher-1", roles={"researcher"}, datasets={DATASET})
SCORER = Principal("scorer-1", roles={"scorer"}, datasets={DATASET})
AGENT = Principal("agent-1", roles={"agent"}, datasets={DATASET})
OPERATOR = Principal("operator-1", roles={"operator"}, datasets={DATASET})
APPROVER = Principal("approver-1", roles={"approver"}, datasets={DATASET})


def gateway_with_original():
    store = ArtifactStore()
    version = store.put_original(PNG, run_id="run_t", producer_id="agent-1")
    audit = AuditLog()
    gateway = EvidenceGateway(store, audit)
    return gateway, audit, version.artifact_version_id


def test_policy_file_is_valid_and_fails_closed():
    policy = load_runtime_policy()
    assert validate_runtime_policy(policy) == []
    assert policy["internal_only"] is True
    broken = dict(policy, internal_only=False)
    assert any("internal" in e for e in validate_runtime_policy(broken))


def test_permissions_protect_originals_by_role_and_dataset():
    gateway, audit, version_id = gateway_with_original()
    assert gateway.read_original(RESEARCHER, DATASET, version_id) == PNG
    with pytest.raises(PermissionError):
        gateway.read_original(AGENT, DATASET, version_id)
    stranger = Principal("researcher-2", roles={"researcher"}, datasets={OTHER_DATASET})
    with pytest.raises(PermissionError):
        gateway.read_original(stranger, DATASET, version_id)
    outcomes = [(e.action, e.outcome) for e in audit.entries]
    assert ("evidence.read", "allowed") in outcomes
    assert outcomes.count(("evidence.read", "denied")) == 2


def test_payloads_are_scorer_only_through_the_gateway():
    fixtures = build_dataset()
    assignments = assign_splits(fixtures)
    audit = AuditLog()
    gateway = EvidenceGateway(ArtifactStore(), audit)
    with pytest.raises(PermissionError):
        gateway.export_held_out_truth(RESEARCHER, DATASET, fixtures, assignments)
    truth = gateway.export_held_out_truth(SCORER, DATASET, fixtures, assignments)
    assert all(isinstance(v, dict) for v in truth.values())
    assert any(e.action == "payload.export" and e.outcome == "denied" for e in audit.entries)
    assert any(e.action == "payload.export" and e.outcome == "allowed" for e in audit.entries)


def test_config_changes_are_permissioned_versioned_and_audited():
    audit = AuditLog()
    config = RuntimeConfig(audit, initial={"max_image_bytes": 10_000_000})
    with pytest.raises(PermissionError):
        config.apply_change(AGENT, "max_image_bytes", 5, reason="shrink")
    assert config.version == 1
    new_version = config.apply_change(OPERATOR, "max_image_bytes", 5_000_000, reason="worker limit")
    assert new_version == 2 and config.get("max_image_bytes") == 5_000_000
    entry = [e for e in audit.entries if e.action == "config.change"][-1]
    assert entry.detail["old"] == 10_000_000 and entry.detail["new"] == 5_000_000
    assert entry.detail["config_version"] == 2


def test_verdict_overrides_need_permission_reason_and_are_audited():
    audit = AuditLog()
    gateway = EvidenceGateway(ArtifactStore(), audit)
    with pytest.raises(PermissionError):
        gateway.record_override(SCORER, DATASET, "vrd_1", "flag", reason="manual review")
    with pytest.raises(ValueError):
        gateway.record_override(RESEARCHER, DATASET, "vrd_1", "flag", reason="")
    record = gateway.record_override(RESEARCHER, DATASET, "vrd_1", "flag", reason="benign skyline")
    assert record["verdict_id"] == "vrd_1" and record["override"] == "flag"
    assert any(e.action == "verdict.override" and e.outcome == "applied" for e in audit.entries)


def test_audit_chain_is_tamper_evident():
    audit = AuditLog()
    audit.append(actor_id="a", action="evidence.read", dataset_id=DATASET, outcome="allowed")
    audit.append(actor_id="b", action="config.change", dataset_id=DATASET, outcome="applied")
    assert audit.verify_chain() is True
    object.__setattr__(audit.entries[0], "actor_id", "mallory")
    assert audit.verify_chain() is False


def test_retirement_requires_separate_approval_and_preserves_bundle(tmp_path):
    root = tmp_path / "evidence"
    store = ArtifactStore(root)
    version = store.put_original(PNG, run_id="run_t", producer_id="agent-1")
    audit = AuditLog()
    retirement = DatasetRetirement(store, audit, config_version=3, store_root=root)

    with pytest.raises(PermissionError):
        retirement.request(AGENT, DATASET, reason="cleanup")
    retirement.request(OPERATOR, DATASET, reason="dataset superseded")
    with pytest.raises(PermissionError):
        retirement.approve(OPERATOR, DATASET)  # requester cannot approve own request
    with pytest.raises(RuntimeError):
        retirement.execute(APPROVER, DATASET)  # not yet approved
    retirement.approve(APPROVER, DATASET)
    bundle = retirement.execute(APPROVER, DATASET)
    assert bundle["content_hashes"] == [version.content_hash]
    assert bundle["config_version"] == 3
    assert not root.exists()  # approved deletion removed the dataset bytes
    assert any(e.action == "retirement.execute" for e in audit.entries)
    assert audit.verify_chain() is True  # audit + bundle record survive deletion
