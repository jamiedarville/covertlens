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
    python -m covertlens gate-demo
    python -m covertlens parse-demo
    python -m covertlens lsb-demo
    python -m covertlens benchmark-lsb
    python -m covertlens dct-demo
    python -m covertlens benchmark-dct
    python -m covertlens trace-demo
    python -m covertlens verdict-demo
    python -m covertlens replay-demo
    python -m covertlens metadata-demo
    python -m covertlens sequence-demo
    python -m covertlens report-demo
    python -m covertlens pinning-demo
    python -m covertlens calibrate-demo
    python -m covertlens frozen-demo
    python -m covertlens latency-demo
    python -m covertlens pilot-demo
    python -m covertlens ablation-demo
    python -m covertlens route-audit-demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .events import REQUIRED_FAMILIES, Event, EventType, ParseStatus
from .manifest import load_manifest, validate_manifest
from .routes import ROUTES, validate_inventory
from .events import Verdict
from .fixtures import build_dataset, build_pair, manifest as fixture_manifest, write_dataset
from .dct import analyze_dct_bytes, benchmark_dct
from .gate import InterceptionContext, InterceptionGate, PendingDeliveryError
from .lsb import analyze_lsb_bytes, analyze_lsb_version, benchmark_lsb
from .trace_join import join_trace
from .metadata import analyze_all_bytes, benchmark_metadata
from .calibration import calibrate_thresholds
from .frozen_benchmark import run_frozen_evaluation
from .latency import run_reliability_report
from .ablations import run_ablations
from .route_audit import run_route_audit
from .pilot import run_pilot
from .pinning import build_pin, verify_reproducibility
from .report import build_run_report
from .sequence import SequenceCase, benchmark_sequences
from .metadata_fixtures import build_metadata_dataset
from .replay import run_replay
from .verdicts import decide_verdict
from .parsing import ParserLimits, analyze_bytes, analyze_version
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

    if command == "gate-demo":
        gate = InterceptionGate(ArtifactStore())
        ctx = InterceptionContext(run_id="run_demo", episode_id="ep_1", sender_id="agent-a")
        handle = gate.intercept_bytes("R-01", b"\x89PNG\r\n\x1a\n" + b"gate-demo-image", ctx)
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        pending_blocked = False
        try:
            gate.recipient_access(delivery.delivery_id)
        except PendingDeliveryError:
            pending_blocked = True
        gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
        served = gate.recipient_access(delivery.delivery_id)
        print(json.dumps({
            "artifact_version_id": handle.artifact_version_id,
            "content_hash": handle.content_hash,
            "delivery_id": delivery.delivery_id,
            "pending_blocked": pending_blocked,
            "served_bytes_after_verdict": len(served),
            "coverage_missing": gate.coverage_report()["missing"],
            "events": [e.event_type.value for e in gate.events("run_demo")],
        }, indent=2))
        return 0

    if command == "parse-demo":
        store = ArtifactStore()
        results = []
        for family in ("spatial_lsb", "jpeg_dct"):
            clean, _ = build_pair(family, width=32, height=24, payload_bytes=8)
            version = store.put_original(
                clean.data, run_id="run_demo", producer_id="agent-a")
            results.append(analyze_version(
                store, version.artifact_version_id, actor_id="detector").to_dict())
        good, _ = build_pair("spatial_lsb", width=32, height=24, payload_bytes=8)
        results.append(analyze_bytes(good.data[: len(good.data) // 2]).to_dict())
        results.append(analyze_bytes(
            good.data, limits=ParserLimits(max_input_bytes=16)).to_dict())
        print(json.dumps(
            [{"status": r["status"], "media_kind": r["media_kind"],
              "content_hash": r["content_hash"], "coverage": r["coverage"],
              "errors": r["errors"]} for r in results], indent=2))
        return 0

    if command == "lsb-demo":
        clean, medium = build_pair(
            "spatial_lsb", width=64, height=48, payload_bytes=64)
        _, high = build_pair(
            "spatial_lsb", width=64, height=48, payload_bytes=192)
        rows = []
        for fixture in (clean, medium, high):
            result = analyze_lsb_bytes(fixture.data)
            finding = result.findings[0] if result.findings else None
            rows.append({
                "role": fixture.role,
                "payload_band": fixture.payload_band,
                "status": result.status.value,
                "score": finding.score if finding else None,
                "coverage": finding.coverage if finding else None,
            })
        print(json.dumps(rows, indent=2))
        return 0

    if command == "benchmark-lsb":
        report = benchmark_lsb(build_dataset())
        print(json.dumps({
            "detector": report["detector"],
            "positive_count": report["positive_count"],
            "negative_count": report["negative_count"],
            "roc_auc": report["roc_auc"],
            "pr_auc": report["pr_auc"],
            "by_payload_band": report["by_payload_band"],
        }, indent=2))
        return 0

    if command == "dct-demo":
        clean, medium = build_pair(
            "jpeg_dct", width=64, height=48, payload_bytes=64)
        _, high = build_pair(
            "jpeg_dct", width=64, height=48, payload_bytes=192)
        rows = []
        for fixture in (clean, medium, high):
            result = analyze_dct_bytes(fixture.data)
            finding = result.findings[0] if result.findings else None
            rows.append({
                "role": fixture.role,
                "payload_band": fixture.payload_band,
                "status": result.status.value,
                "score": finding.score if finding else None,
                "coverage": finding.coverage if finding else None,
            })
        print(json.dumps(rows, indent=2))
        return 0

    if command == "benchmark-dct":
        report = benchmark_dct(build_dataset())
        print(json.dumps({
            "detector": report["detector"],
            "positive_count": report["positive_count"],
            "negative_count": report["negative_count"],
            "roc_auc": report["roc_auc"],
            "pr_auc": report["pr_auc"],
            "by_payload_band": report["by_payload_band"],
        }, indent=2))
        return 0

    if command == "trace-demo":
        from datetime import datetime, timezone

        gate = InterceptionGate(ArtifactStore())
        ctx = InterceptionContext(
            run_id="run_demo", episode_id="ep_1", sender_id="agent-a")
        clean, encoded = build_pair(
            "spatial_lsb", width=64, height=48, payload_bytes=64)
        results = []
        deliveries = []
        for fixture in (clean, encoded):
            handle = gate.intercept_bytes("R-01", fixture.data, ctx)
            results.append(analyze_lsb_version(
                gate.store, handle.artifact_version_id, actor_id="detector"))
            delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
            gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
            gate.recipient_access(delivery.delivery_id)
            deliveries.append(delivery)
        gate.record_parse(deliveries[0].delivery_id, ParseStatus.PARSED)
        events = gate.events("run_demo")
        events.append(Event(
            EventType.RECIPIENT_ACTION, "run_demo", len(events),
            datetime.now(timezone.utc).isoformat(),
            recipient_id="agent-b", payload={"action": "answer"},
        ))
        report = join_trace(events, results)
        print(json.dumps({
            "run_id": report["run_id"],
            "summary": report["summary"],
            "deliveries": [
                {
                    "delivery_id": d["delivery_id"],
                    "content_hash": d["content_hash"],
                    "verdict": (d["verdict"] or {}).get("verdict"),
                    "findings": len(d["findings"]),
                    "parse": d["parse"],
                    "missing": d["missing"],
                }
                for d in report["deliveries"]
            ],
            "actions": report["actions"],
        }, indent=2))
        return 0

    if command == "metadata-demo":
        fixtures = build_metadata_dataset()
        rows = []
        for fixture in fixtures:
            if fixture.role not in ("encoded", "negative"):
                continue
            result = analyze_all_bytes(fixture.data)
            rows.append({
                "role": fixture.role,
                "media_kind": fixture.media_kind,
                "findings": {f.family: f.score for f in result.findings},
            })
        report = benchmark_metadata(fixtures)
        print(json.dumps({"rows": rows[:4], "roc_auc": report["roc_auc"],
                          "by_payload_band": report["by_payload_band"]}, indent=2))
        return 0

    if command == "report-demo":
        gate = InterceptionGate(ArtifactStore())
        ctx = InterceptionContext(
            run_id="run_demo", episode_id="ep_1", sender_id="agent-a")
        clean, encoded = build_pair(
            "spatial_lsb", width=64, height=48, payload_bytes=64)
        results = []
        for fixture in (clean, encoded):
            handle = gate.intercept_bytes("R-01", fixture.data, ctx)
            results.append(analyze_lsb_version(
                gate.store, handle.artifact_version_id, actor_id="detector"))
            delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
            gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
            gate.recipient_access(delivery.delivery_id)
            gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
        report = build_run_report(gate.events("run_demo"), results, report_id="rpt_demo")
        print(json.dumps({
            "run_id": report["run_id"],
            "originals": len(report["originals"]),
            "triage_queue": report["triage_queue"],
            "disposition_counts": report["disposition_counts"],
        }, indent=2))
        return 0

    if command == "pinning-demo":
        fixtures = build_dataset()
        pin = build_pin(fixtures, seeds={"replay": 20261028})
        repro = verify_reproducibility(fixtures[:4], repetitions=2)
        print(json.dumps({"pin_hash": pin["pin_hash"],
                          "dataset_hash": pin["dataset"]["dataset_hash"],
                          "detectors": pin["detectors"],
                          "reproducibility": repro}, indent=2))
        return 0

    if command == "calibrate-demo":
        fixtures, assignments = [], {}
        for dataset in (build_dataset(), build_metadata_dataset()):
            split = assign_splits(dataset)
            assignments.update(split)
            fixtures.extend(
                f for f in dataset if split[f.fixture_id] != "held_out"
            )
        report = calibrate_thresholds(fixtures, assignments)
        print(json.dumps({
            "frozen_config_version": report["frozen_config_version"],
            "held_out_labels_used": report["held_out_labels_used"],
            "points": {
                family: {
                    "flag": block["triage_flag_at"],
                    "quarantine": block["enforcement_quarantine_at"],
                    "fail_run": block["enforcement_fail_run_at"],
                    "calibrated_bands": block["calibrated_payload_bands"],
                }
                for family, block in report["families"].items()
            },
        }, indent=2))
        return 0

    if command == "frozen-demo":
        report = run_frozen_evaluation()
        print(json.dumps({
            "frozen_config_version": report["frozen_config_version"],
            "held_out_families": {
                family: {
                    "recall": block["recall_at_triage"]["value"],
                    "precision": block["enforcement_precision"]["value"],
                    "positives": block["positives"],
                }
                for family, block in report["held_out"]["families"].items()
            },
            "clean_runs": report["clean_run_stability"]["runs"],
            "clean_false_failure_rate":
                report["clean_run_stability"]["false_failure_rate"]["value"],
            "assessment": report["assessment"],
        }, indent=2))
        return 0

    if command == "latency-demo":
        report = run_reliability_report()
        print(json.dumps({
            "proposal": report["proposal"],
            "classes": {
                f"{row['class']}/{row['media']}": {
                    "p95_s": row["p95_s"], "meets": row["meets_proposal"],
                    "statuses": row["statuses"],
                }
                for row in report["classes"]
            },
            "concurrent_p95_s": report["concurrent"]["p95_s"],
            "limits": report["limit_behavior"],
            "assessment": report["assessment"],
        }, indent=2))
        return 0

    if command == "pilot-demo":
        report = run_pilot(adjudications={
            "uns-1": {"disposition": "suspected",
                      "note": "strong DCT evidence; no independent basis yet"},
            "uns-5": {"disposition": "benign", "note": "clean control pattern"},
        })
        print(json.dumps({
            "pin_hash": report["pin_hash"],
            "seeded": {
                "traces": report["seeded"]["traces"],
                "log_flag": report["seeded"]["log_flag"],
                "enforcement": report["seeded"]["enforcement"],
            },
            "disagreements": report["disagreements"],
            "review_volume": report["review_volume"],
            "repeated_weak_signals": report["repeated_weak_signals"],
        }, indent=2))
        return 0

    if command == "ablation-demo":
        report = run_ablations()
        print(json.dumps({
            "frozen_config_version": report["frozen_config_version"],
            "traces": report["traces"],
            "arms": report["arms"],
            "prevention": {
                "attempts": report["prevention"]["attempts"],
                "clean_controls": report["prevention"]["clean_controls"],
            },
        }, indent=2))
        return 0

    if command == "route-audit-demo":
        report = run_route_audit()
        print(json.dumps({
            "routes": {r["route_id"]: r["status"] for r in report["routes"]},
            "coverage": report["coverage"],
            "trace_missing_reasons": report["trace"]["missing_link_reasons"],
            "gaps": report["gaps"],
        }, indent=2))
        return 0

    if command == "sequence-demo":
        def feats(n, actions, peak):
            return {"prior_deliveries": n, "prior_delivered": n,
                    "prior_actions": actions, "prior_max_score": peak,
                    "prior_mean_score": peak}
        cases = [
            SequenceCase("sig-1", 1, 0.25, feats(4, 3, 0.25)),
            SequenceCase("sig-2", 1, 0.22, feats(3, 2, 0.24)),
            SequenceCase("ben-1", 0, 0.26, feats(0, 0, 0.0)),
            SequenceCase("ben-2", 0, 0.21, feats(1, 0, 0.2)),
        ]
        print(json.dumps(benchmark_sequences(cases), indent=2))
        return 0

    if command == "replay-demo":
        report = run_replay(build_dataset())
        print(json.dumps({
            "config": report["config"],
            "by_condition": report["by_condition"],
            "by_payload_band": report["by_payload_band"],
        }, indent=2))
        return 0

    if command == "verdict-demo":
        rows = []
        clean, encoded = build_pair(
            "spatial_lsb", width=64, height=48, payload_bytes=192)
        for fixture in (clean, encoded):
            result = analyze_lsb_bytes(fixture.data)
            decision = decide_verdict(result.findings)
            rows.append({
                "role": fixture.role,
                "payload_band": fixture.payload_band,
                "score": result.findings[0].score if result.findings else None,
                "decision": decision.to_dict(),
            })
        print(json.dumps(rows, indent=2))
        return 0

    print(f"unknown command: {command}", file=sys.stderr)
    return 2
