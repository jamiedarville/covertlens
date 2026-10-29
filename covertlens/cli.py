"""Command-line checks for the CL-7 contracts and CL-8 store.

Usage:
    python -m covertlens validate-manifest [PATH]
    python -m covertlens list-events
    python -m covertlens list-routes
    python -m covertlens store-demo
    python -m covertlens build-fixtures [OUT_DIR]
    python -m covertlens split-dataset [OUT_DIR]
    python -m covertlens validate-runtime [PATH]
    python -m covertlens runtime-demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .events import REQUIRED_FAMILIES, EventType
from .manifest import load_manifest, validate_manifest
from .routes import ROUTES, validate_inventory
from .fixtures import build_dataset, manifest as fixture_manifest, write_dataset
from .runtime import (
    AuditLog,
    EvidenceGateway,
    Principal,
    load_runtime_policy,
    validate_runtime_policy,
)
from .splits import assign_splits, validate_no_leakage, verify_recovery, write_split_dataset
from .store import ArtifactStore


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "validate-manifest"

    if command == "validate-manifest":
        path = Path(args[1]) if len(args) > 1 else None
        manifest = load_manifest(path)
        errors = validate_manifest(manifest)
        route_errors = validate_inventory()
        errors.extend(route_errors)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print(f"manifest {manifest['manifest_id']} v{manifest['manifest_version']}: valid")
        print(f"route inventory: {len(ROUTES)} routes valid")
        return 0

    if command == "list-events":
        rows = [{"family": name, "event_type": etype.value}
                for name, etype in REQUIRED_FAMILIES.items()]
        rows.append({"family": "gate_verdict (linkage)", "event_type": EventType.GATE_VERDICT.value})
        print(json.dumps(rows, indent=2))
        return 0

    if command == "list-routes":
        rows = [{"route_id": r.route_id, "kind": r.kind, "name": r.name,
                 "gate_required": r.gate_required} for r in ROUTES]
        print(json.dumps(rows, indent=2))
        return 0

    if command == "store-demo":
        store = ArtifactStore()
        v1 = store.put_original(
            b"\x89PNG\r\n\x1a\n" + b"synthetic-clean-png-v1",
            run_id="run_demo", producer_id="agent-a",
        )
        store.register_verdict("vrd_demo", v1.artifact_version_id)
        v2 = store.put_original(
            b"\x89PNG\r\n\x1a\n" + b"synthetic-changed-png-v2",
            run_id="run_demo", producer_id="agent-a", artifact_id=v1.artifact_id,
        )
        print(json.dumps({
            "v1": store.export_record(v1.artifact_version_id),
            "v2": store.export_record(v2.artifact_version_id),
            "vrd_demo_status": store.verdict_status("vrd_demo"),
            "verify_all": store.verify_all(),
            "stats": store.stats(),
        }, indent=2))
        return 0

    if command == "build-fixtures":
        out_dir = Path(args[1]) if len(args) > 1 else Path("fixtures-out")
        fixtures = build_dataset()
        write_dataset(out_dir, fixtures)
        doc = fixture_manifest(fixtures)
        roles: dict[str, int] = {}
        for row in doc["fixtures"]:
            roles[row["role"]] = roles.get(row["role"], 0) + 1
        print(f"wrote {len(fixtures)} fixtures to {out_dir}: {roles}")
        print(f"verified payloads: {sum(f.verify_payload() for f in fixtures)}/{len(fixtures)}")
        return 0

    if command == "split-dataset":
        out_dir = Path(args[1]) if len(args) > 1 else Path("split-out")
        fixtures = build_dataset()
        assignments = assign_splits(fixtures)
        errors = validate_no_leakage(fixtures, assignments)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        write_split_dataset(out_dir, fixtures, assignments)
        counts: dict[str, int] = {}
        for split in assignments.values():
            counts[split] = counts.get(split, 0) + 1
        report = verify_recovery(fixtures)
        print(f"wrote split dataset to {out_dir}: {counts}")
        print(f"recovery checks: {report.passed}/{report.checked} passed")
        return 0

    if command == "validate-runtime":
        path = Path(args[1]) if len(args) > 1 else None
        policy = load_runtime_policy(path)
        errors = validate_runtime_policy(policy)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print(f"runtime policy {policy['policy_id']} v{policy['policy_version']}: valid")
        return 0

    if command == "runtime-demo":
        audit = AuditLog()
        store = ArtifactStore()
        version = store.put_original(
            b"\x89PNG\r\n\x1a\n" + b"runtime-demo-original",
            run_id="run_demo", producer_id="agent-a",
        )
        gateway = EvidenceGateway(store, audit)
        researcher = Principal("researcher-1", roles={"researcher"}, datasets={"dataset-a"})
        agent = Principal("agent-1", roles={"agent"}, datasets={"dataset-a"})
        served = gateway.read_original(researcher, "dataset-a", version.artifact_version_id)
        denied = False
        try:
            gateway.read_original(agent, "dataset-a", version.artifact_version_id)
        except PermissionError:
            denied = True
        print(json.dumps({
            "served_bytes": len(served),
            "agent_denied": denied,
            "audit_entries": len(audit.entries),
            "audit_chain_valid": audit.verify_chain(),
        }, indent=2))
        return 0

    print(f"unknown command: {command}", file=sys.stderr)
    return 2
