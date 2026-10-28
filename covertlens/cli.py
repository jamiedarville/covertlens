"""Command-line checks for the CL-7 contracts.

Usage:
    python -m covertlens validate-manifest [PATH]
    python -m covertlens list-events
    python -m covertlens list-routes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .events import REQUIRED_FAMILIES, EventType
from .manifest import load_manifest, validate_manifest
from .routes import ROUTES, validate_inventory


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

    print(f"unknown command: {command}", file=sys.stderr)
    return 2
