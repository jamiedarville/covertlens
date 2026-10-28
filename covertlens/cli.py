"""Command-line checks for the CL-7 contracts and CL-8 store.

Usage:
    python -m covertlens validate-manifest [PATH]
    python -m covertlens list-events
    python -m covertlens list-routes
    python -m covertlens store-demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .events import REQUIRED_FAMILIES, EventType
from .manifest import load_manifest, validate_manifest
from .routes import ROUTES, validate_inventory
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

    print(f"unknown command: {command}", file=sys.stderr)
    return 2
