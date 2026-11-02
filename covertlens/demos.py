"""Handlers for the `covertlens` command-line checks and demos.

Split from `cli.py` in CL-50: `cli.py` owns argument parsing and
dispatch; each command here is one typed function returning a
`DemoResult` — an exit code, a JSON-shaped payload (what `--json`
and `--out PATH` emit, and what the schema tests validate), and
the default human-readable summary. Handlers are thin wrappers
over library calls, the same calls the web service makes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ablations import run_ablations
from .calibration import calibrate_thresholds, development_calibration_data
from .dct import analyze_dct_bytes, benchmark_dct
from .events import REQUIRED_FAMILIES, Event, EventType, ParseStatus, Verdict
from .fixtures import build_dataset, build_pair, write_dataset
from .fixtures import manifest as fixture_manifest
from .frozen_benchmark import run_frozen_evaluation
from .gate import InterceptionContext, InterceptionGate, PendingDeliveryError
from .geo_benchmark import run_geo_benchmark, validate_geo_benchmark
from .geometric import analyze_geometric_bytes
from .geometric_fixtures import (
    assign_geo_splits,
    build_geo_dataset,
    build_geo_pair,
    geo_manifest,
    validate_geo_splits,
    verify_geo_fixture,
)
from .handoff import run_handoff_verification
from .latency import run_reliability_report
from .lsb import analyze_lsb_bytes, analyze_lsb_version, benchmark_lsb
from .manifest import load_manifest, validate_manifest
from .metadata import analyze_all_bytes, benchmark_metadata
from .metadata_fixtures import build_metadata_dataset
from .parsing import ParserLimits, analyze_bytes, analyze_version
from .pilot import run_pilot
from .pinning import build_pin, verify_reproducibility
from .replay import run_replay
from .report import build_run_report
from .review_export import run_export_verification
from .robustness import run_robustness
from .route_audit import run_route_audit
from .routes import ROUTES, validate_inventory
from .runtime import (
    AuditLog,
    EvidenceGateway,
    Principal,
    load_runtime_policy,
    validate_runtime_policy,
)
from .scorecard import load_scorecard
from .segmentation import segment_image
from .sequence import SequenceCase, benchmark_sequences
from .splits import (
    assign_splits,
    split_manifest,
    validate_no_leakage,
    verify_recovery,
    write_split_dataset,
)
from .store import ArtifactStore
from .trace_join import join_trace
from .vector_source import analyze_with_source, build_vector_source
from .verdicts import decide_verdict


@dataclass(frozen=True)
class DemoResult:
    """One command's outcome: exit code plus output payloads."""

    exit_code: int
    payload: Any = None
    summary: str | None = None


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2)


def cmd_validate_manifest(args: argparse.Namespace) -> DemoResult:
    path = Path(args.path) if args.path else None
    manifest = load_manifest(path)
    errors = validate_manifest(manifest)
    errors.extend(validate_inventory())
    if errors:
        summary = "\n".join(f"ERROR: {error}" for error in errors)
        return DemoResult(1, payload=manifest, summary=summary)
    summary = (
        f"manifest {manifest['manifest_id']} "
        f"v{manifest['manifest_version']}: valid\n"
        f"route inventory: {len(ROUTES)} routes valid"
    )
    return DemoResult(0, payload=manifest, summary=summary)


def cmd_list_events(args: argparse.Namespace) -> DemoResult:
    del args
    rows = [
        {"family": name, "event_type": etype.value}
        for name, etype in REQUIRED_FAMILIES.items()
    ]
    rows.append(
        {"family": "gate_verdict (linkage)", "event_type": EventType.GATE_VERDICT.value}
    )
    return DemoResult(0, payload=rows)


def cmd_list_routes(args: argparse.Namespace) -> DemoResult:
    del args
    rows = [
        {
            "route_id": r.route_id,
            "kind": r.kind,
            "name": r.name,
            "gate_required": r.gate_required,
        }
        for r in ROUTES
    ]
    return DemoResult(0, payload=rows)


def cmd_store_demo(args: argparse.Namespace) -> DemoResult:
    del args
    store = ArtifactStore()
    v1 = store.put_original(
        b"\x89PNG\r\n\x1a\n" + b"synthetic-clean-png-v1",
        run_id="run_demo",
        producer_id="agent-a",
    )
    store.register_verdict("vrd_demo", v1.artifact_version_id)
    v2 = store.put_original(
        b"\x89PNG\r\n\x1a\n" + b"synthetic-changed-png-v2",
        run_id="run_demo",
        producer_id="agent-a",
        artifact_id=v1.artifact_id,
    )
    payload = {
        "v1": store.export_record(v1.artifact_version_id),
        "v2": store.export_record(v2.artifact_version_id),
        "vrd_demo_status": store.verdict_status("vrd_demo"),
        "verify_all": store.verify_all(),
        "stats": store.stats(),
    }
    return DemoResult(0, payload=payload)


def cmd_build_fixtures(args: argparse.Namespace) -> DemoResult:
    out_dir = Path(args.out_dir) if args.out_dir else Path("fixtures-out")
    fixtures = build_dataset()
    write_dataset(out_dir, fixtures)
    doc = fixture_manifest(fixtures)
    roles: dict[str, int] = {}
    for row in doc["fixtures"]:
        roles[row["role"]] = roles.get(row["role"], 0) + 1
    summary = (
        f"wrote {len(fixtures)} fixtures to {out_dir}: {roles}\n"
        f"verified payloads: {sum(f.verify_payload() for f in fixtures)}/{len(fixtures)}"
    )
    return DemoResult(0, payload=doc, summary=summary)


def cmd_split_dataset(args: argparse.Namespace) -> DemoResult:
    out_dir = Path(args.out_dir) if args.out_dir else Path("split-out")
    fixtures = build_dataset()
    assignments = assign_splits(fixtures)
    errors = validate_no_leakage(fixtures, assignments)
    if errors:
        summary = "\n".join(f"ERROR: {error}" for error in errors)
        return DemoResult(1, payload=None, summary=summary)
    write_split_dataset(out_dir, fixtures, assignments)
    counts: dict[str, int] = {}
    for split in assignments.values():
        counts[split] = counts.get(split, 0) + 1
    report = verify_recovery(fixtures)
    summary = (
        f"wrote split dataset to {out_dir}: {counts}\n"
        f"recovery checks: {report.passed}/{report.checked} passed"
    )
    return DemoResult(0, payload=split_manifest(fixtures, assignments), summary=summary)


def cmd_validate_runtime(args: argparse.Namespace) -> DemoResult:
    path = Path(args.path) if args.path else None
    policy = load_runtime_policy(path)
    errors = validate_runtime_policy(policy)
    if errors:
        summary = "\n".join(f"ERROR: {error}" for error in errors)
        return DemoResult(1, payload=policy, summary=summary)
    summary = f"runtime policy {policy['policy_id']} v{policy['policy_version']}: valid"
    return DemoResult(0, payload=policy, summary=summary)


def cmd_runtime_demo(args: argparse.Namespace) -> DemoResult:
    del args
    audit = AuditLog()
    store = ArtifactStore()
    version = store.put_original(
        b"\x89PNG\r\n\x1a\n" + b"runtime-demo-original",
        run_id="run_demo",
        producer_id="agent-a",
    )
    gateway = EvidenceGateway(store, audit)
    researcher = Principal(
        "researcher-1",
        roles=frozenset({"researcher"}),
        datasets=frozenset({"dataset-a"}),
    )
    agent = Principal(
        "agent-1", roles=frozenset({"agent"}), datasets=frozenset({"dataset-a"})
    )
    served = gateway.read_original(researcher, "dataset-a", version.artifact_version_id)
    denied = False
    try:
        gateway.read_original(agent, "dataset-a", version.artifact_version_id)
    except PermissionError:
        denied = True
    payload = {
        "served_bytes": len(served),
        "agent_denied": denied,
        "audit_entries": len(audit.entries),
        "audit_chain_valid": audit.verify_chain(),
    }
    return DemoResult(0, payload=payload)


def cmd_gate_demo(args: argparse.Namespace) -> DemoResult:
    del args
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id="run_demo", episode_id="ep_1", sender_id="agent-a")
    handle = gate.intercept_bytes(
        "R-01", b"\x89PNG\r\n\x1a\n" + b"gate-demo-image", ctx
    )
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    pending_blocked = False
    try:
        gate.recipient_access(delivery.delivery_id)
    except PendingDeliveryError:
        pending_blocked = True
    gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
    served = gate.recipient_access(delivery.delivery_id)
    summary_payload = {
        "artifact_version_id": handle.artifact_version_id,
        "content_hash": handle.content_hash,
        "delivery_id": delivery.delivery_id,
        "pending_blocked": pending_blocked,
        "served_bytes_after_verdict": len(served),
        "coverage_missing": gate.coverage_report()["missing"],
        "events": [e.event_type.value for e in gate.events("run_demo")],
    }
    delivery_record = {
        "delivery_id": delivery.delivery_id,
        "run_id": delivery.run_id,
        "artifact_id": delivery.artifact_id,
        "artifact_version_id": delivery.artifact_version_id,
        "content_hash": delivery.content_hash,
        "sender_id": delivery.sender_id,
        "recipient_id": delivery.recipient_id,
        "attempt": delivery.attempt,
        "episode_id": delivery.episode_id,
        "state": delivery.state,
        "verdict_id": delivery.verdict_id,
        "verdict": delivery.verdict.value if delivery.verdict else None,
        "infrastructure_error": delivery.infrastructure_error,
    }
    payload = {**summary_payload, "delivery": delivery_record}
    return DemoResult(0, payload=payload, summary=_dump(summary_payload))


def cmd_parse_demo(args: argparse.Namespace) -> DemoResult:
    del args
    store = ArtifactStore()
    results = []
    for family in ("spatial_lsb", "jpeg_dct"):
        clean, _ = build_pair(family, width=32, height=24, payload_bytes=8)
        version = store.put_original(
            clean.data, run_id="run_demo", producer_id="agent-a"
        )
        results.append(
            analyze_version(
                store, version.artifact_version_id, actor_id="detector"
            ).to_dict()
        )
    good, _ = build_pair("spatial_lsb", width=32, height=24, payload_bytes=8)
    results.append(analyze_bytes(good.data[: len(good.data) // 2]).to_dict())
    results.append(
        analyze_bytes(good.data, limits=ParserLimits(max_input_bytes=16)).to_dict()
    )
    summary = _dump(
        [
            {
                "status": r["status"],
                "media_kind": r["media_kind"],
                "content_hash": r["content_hash"],
                "coverage": r["coverage"],
                "errors": r["errors"],
            }
            for r in results
        ]
    )
    return DemoResult(0, payload=results, summary=summary)


def _detector_rows(results: list[Any], fixtures: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for fixture, result in zip(fixtures, results, strict=True):
        finding = result.findings[0] if result.findings else None
        rows.append(
            {
                "role": fixture.role,
                "payload_band": fixture.payload_band,
                "status": result.status.value,
                "score": finding.score if finding else None,
                "coverage": finding.coverage if finding else None,
            }
        )
    return rows


def cmd_lsb_demo(args: argparse.Namespace) -> DemoResult:
    del args
    clean, medium = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    _, high = build_pair("spatial_lsb", width=64, height=48, payload_bytes=192)
    fixtures = [clean, medium, high]
    results = [analyze_lsb_bytes(f.data) for f in fixtures]
    return DemoResult(
        0,
        payload=[r.to_dict() for r in results],
        summary=_dump(_detector_rows(results, fixtures)),
    )


def cmd_benchmark_lsb(args: argparse.Namespace) -> DemoResult:
    del args
    report = benchmark_lsb(build_dataset())
    summary = _dump(
        {
            "detector": report["detector"],
            "positive_count": report["positive_count"],
            "negative_count": report["negative_count"],
            "roc_auc": report["roc_auc"],
            "pr_auc": report["pr_auc"],
            "by_payload_band": report["by_payload_band"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_dct_demo(args: argparse.Namespace) -> DemoResult:
    del args
    clean, medium = build_pair("jpeg_dct", width=64, height=48, payload_bytes=64)
    _, high = build_pair("jpeg_dct", width=64, height=48, payload_bytes=192)
    fixtures = [clean, medium, high]
    results = [analyze_dct_bytes(f.data) for f in fixtures]
    return DemoResult(
        0,
        payload=[r.to_dict() for r in results],
        summary=_dump(_detector_rows(results, fixtures)),
    )


def cmd_benchmark_dct(args: argparse.Namespace) -> DemoResult:
    del args
    report = benchmark_dct(build_dataset())
    summary = _dump(
        {
            "detector": report["detector"],
            "positive_count": report["positive_count"],
            "negative_count": report["negative_count"],
            "roc_auc": report["roc_auc"],
            "pr_auc": report["pr_auc"],
            "by_payload_band": report["by_payload_band"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_trace_demo(args: argparse.Namespace) -> DemoResult:
    del args
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id="run_demo", episode_id="ep_1", sender_id="agent-a")
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    results = []
    deliveries = []
    for fixture in (clean, encoded):
        handle = gate.intercept_bytes("R-01", fixture.data, ctx)
        results.append(
            analyze_lsb_version(
                gate.store, handle.artifact_version_id, actor_id="detector"
            )
        )
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
        gate.recipient_access(delivery.delivery_id)
        deliveries.append(delivery)
    gate.record_parse(deliveries[0].delivery_id, ParseStatus.PARSED)
    events = gate.events("run_demo")
    events.append(
        Event(
            EventType.RECIPIENT_ACTION,
            "run_demo",
            len(events),
            datetime.now(UTC).isoformat(),
            recipient_id="agent-b",
            payload={"action": "answer"},
        )
    )
    report = join_trace(events, results)
    summary = _dump(
        {
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
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_metadata_demo(args: argparse.Namespace) -> DemoResult:
    del args
    fixtures = build_metadata_dataset()
    rows = []
    for fixture in fixtures:
        if fixture.role not in ("encoded", "negative"):
            continue
        result = analyze_all_bytes(fixture.data)
        rows.append(
            {
                "role": fixture.role,
                "media_kind": fixture.media_kind,
                "findings": {f.family: f.score for f in result.findings},
            }
        )
    report = benchmark_metadata(fixtures)
    summary = _dump(
        {
            "rows": rows[:4],
            "roc_auc": report["roc_auc"],
            "by_payload_band": report["by_payload_band"],
        }
    )
    payload = {"rows": rows, "benchmark": report}
    return DemoResult(0, payload=payload, summary=summary)


def cmd_report_demo(args: argparse.Namespace) -> DemoResult:
    del args
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id="run_demo", episode_id="ep_1", sender_id="agent-a")
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    results = []
    for fixture in (clean, encoded):
        handle = gate.intercept_bytes("R-01", fixture.data, ctx)
        results.append(
            analyze_lsb_version(
                gate.store, handle.artifact_version_id, actor_id="detector"
            )
        )
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
        gate.recipient_access(delivery.delivery_id)
        gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
    report = build_run_report(gate.events("run_demo"), results, report_id="rpt_demo")
    summary = _dump(
        {
            "run_id": report["run_id"],
            "originals": len(report["originals"]),
            "triage_queue": report["triage_queue"],
            "disposition_counts": report["disposition_counts"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_pinning_demo(args: argparse.Namespace) -> DemoResult:
    del args
    fixtures = build_dataset()
    pin = build_pin(fixtures, seeds={"replay": 20261028})
    repro = verify_reproducibility(fixtures[:4], repetitions=2)
    summary = _dump(
        {
            "pin_hash": pin["pin_hash"],
            "dataset_hash": pin["dataset"]["dataset_hash"],
            "detectors": pin["detectors"],
            "reproducibility": repro,
        }
    )
    return DemoResult(
        0, payload={"pin": pin, "reproducibility": repro}, summary=summary
    )


def cmd_calibrate_demo(args: argparse.Namespace) -> DemoResult:
    del args
    fixtures, assignments = development_calibration_data()
    report = calibrate_thresholds(fixtures, assignments)
    summary = _dump(
        {
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
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_frozen_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_frozen_evaluation()
    summary = _dump(
        {
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
            "clean_false_failure_rate": report["clean_run_stability"][
                "false_failure_rate"
            ]["value"],
            "assessment": report["assessment"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_latency_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_reliability_report()
    summary = _dump(
        {
            "proposal": report["proposal"],
            "classes": {
                f"{row['class']}/{row['media']}": {
                    "p95_s": row["p95_s"],
                    "meets": row["meets_proposal"],
                    "statuses": row["statuses"],
                }
                for row in report["classes"]
            },
            "concurrent_p95_s": report["concurrent"]["p95_s"],
            "limits": report["limit_behavior"],
            "assessment": report["assessment"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_pilot_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_pilot(
        adjudications={
            "uns-1": {
                "disposition": "suspected",
                "note": "strong DCT evidence; no independent basis yet",
            },
            "uns-5": {"disposition": "benign", "note": "clean control pattern"},
        }
    )
    summary = _dump(
        {
            "pin_hash": report["pin_hash"],
            "seeded": {
                "traces": report["seeded"]["traces"],
                "log_flag": report["seeded"]["log_flag"],
                "enforcement": report["seeded"]["enforcement"],
            },
            "disagreements": report["disagreements"],
            "review_volume": report["review_volume"],
            "repeated_weak_signals": report["repeated_weak_signals"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_ablation_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_ablations()
    summary = _dump(
        {
            "frozen_config_version": report["frozen_config_version"],
            "traces": report["traces"],
            "arms": report["arms"],
            "prevention": {
                "attempts": report["prevention"]["attempts"],
                "clean_controls": report["prevention"]["clean_controls"],
            },
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_route_audit_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_route_audit()
    summary = _dump(
        {
            "routes": {r["route_id"]: r["status"] for r in report["routes"]},
            "coverage": report["coverage"],
            "trace_missing_reasons": report["trace"]["missing_link_reasons"],
            "gaps": report["gaps"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_export_demo(args: argparse.Namespace) -> DemoResult:
    del args
    result = run_export_verification()
    package = result["package"]
    summary = _dump(
        {
            "package_hash": package["package_hash"],
            "package_valid": result["package_valid"],
            "originals": len(package["originals"]),
            "decisions": len(package["decisions"]),
            "disposition_counts": package["disposition_counts"],
            "researcher_read_ok": result["researcher_read_ok"],
            "denials": result["denials"],
            "verification": result["verification"],
        }
    )
    return DemoResult(0, payload=result, summary=summary)


def cmd_robustness_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_robustness()
    summary = _dump(
        {
            "frozen_config_version": report["frozen_config_version"],
            "separate_from_frozen_benchmark": report["separate_from_frozen_benchmark"],
            "outcomes": report["outcomes"],
            "unresolved": report["unresolved"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_scorecard_demo(args: argparse.Namespace) -> DemoResult:
    del args
    card = load_scorecard()
    summary = _dump(
        {
            "release": card["release"],
            "frozen_config_version": card["frozen_config_version"],
            "decision": card["decision"]["value"],
            "limitations": len(card["decision"]["limitations"]),
            "target_revisions": len(card["decision"]["target_revisions"]),
            "detection": {
                family: {
                    "recall": block["recall_at_triage"],
                    "precision": block["enforcement_precision"],
                }
                for family, block in card["sections"]["detection_frozen_benchmark"][
                    "per_family"
                ].items()
            },
            "clean_run_failure_rate": card["sections"]["detection_frozen_benchmark"][
                "clean_run_failure_rate"
            ],
        }
    )
    return DemoResult(0, payload=card, summary=summary)


def cmd_handoff_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_handoff_verification()
    summary = _dump(
        {
            "runbook": report["runbook"],
            "release_decision": report["release_decision"],
            "threshold_operations": report["threshold_operations"],
            "quarantine_handling": report["quarantine_handling"],
            "reruns": report["reruns"],
            "dataset_retirement": report["dataset_retirement"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_geo_fixtures_demo(args: argparse.Namespace) -> DemoResult:
    del args
    fixtures = build_geo_dataset()
    manifest = geo_manifest(fixtures)
    assignments = assign_geo_splits(fixtures)
    summary = _dump(
        {
            "fixtures": len(fixtures),
            "subfamilies": manifest["subfamilies"],
            "roles": sorted({f.role for f in fixtures}),
            "verified": sum(1 for f in fixtures if verify_geo_fixture(f)),
            "splits": {
                s: sum(1 for v in assignments.values() if v == s)
                for s in sorted(set(assignments.values()))
            },
            "split_errors": validate_geo_splits(fixtures, assignments),
        }
    )
    return DemoResult(0, payload=manifest, summary=summary)


def cmd_segmentation_demo(args: argparse.Namespace) -> DemoResult:
    del args
    fixtures = build_geo_dataset()
    out: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    for subfamily in (
        "height_position",
        "gap_timing",
        "lit_dark",
        "colour_code",
        "angle_tilt",
    ):
        fixture = next(
            f for f in fixtures if f.subfamily == subfamily and f.role == "encoded"
        )
        result = segment_image(fixture.data)
        out[subfamily] = {
            "status": result.status,
            "elements": len(result.elements),
            "heights": result.sequence("height"),
        }
        payload[subfamily] = result.to_dict()
    return DemoResult(0, payload=payload, summary=_dump(out))


def cmd_geometric_demo(args: argparse.Namespace) -> DemoResult:
    del args
    fixtures = build_geo_dataset()
    out: dict[str, Any] = {}
    findings: dict[str, Any] = {}
    for fixture in fixtures:
        if fixture.role not in ("encoded", "clean"):
            if fixture.negative_kind != "legitimate_chart":
                continue
        key = f"{fixture.subfamily}/{fixture.role}"
        if key in out:
            continue
        report = analyze_geometric_bytes(fixture.data)
        out[key] = {
            "classification": report["classification"],
            "primary_channel": report.get("primary_channel"),
            "score": report["finding"].score if report["finding"] else None,
        }
        findings[key] = report["finding"].to_dict() if report["finding"] else None
    payload = {"classifications": out, "findings": findings}
    return DemoResult(0, payload=payload, summary=_dump(out))


def cmd_vector_demo(args: argparse.Namespace) -> DemoResult:
    del args
    pair = build_geo_pair("height_position")
    encoded = next(f for f in pair if f.role == "encoded")
    clean = next(f for f in pair if f.role == "clean")
    payload = {
        "bound": analyze_with_source(
            encoded, build_vector_source(encoded), store=ArtifactStore()
        ),
        "c10_refusal": analyze_with_source(
            clean, build_vector_source(clean), source_intercepted=False
        )["clearance"],
        "raster_fallback": analyze_with_source(encoded, None)["vector_status"],
    }
    return DemoResult(0, payload=payload)


def cmd_geo_benchmark_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_geo_benchmark()
    errors = validate_geo_benchmark(report)
    summary = json.dumps(
        {
            "benchmark_passed": report["benchmark_passed"],
            "validation_errors": errors,
            "prevalence": report["prevalence"],
            "recall_any_signal_by_subfamily": {
                name: block["encoded"]["recall_any_signal"]["rate"]
                for name, block in report["subfamilies"].items()
            },
            "benign_false_structure_claims": report["overall_context_only"][
                "benign_false_structure_claims"
            ],
            "controls_false_claims": {
                kind: block["false_structure_claims"]["successes"]
                for kind, block in report["benign_controls"].items()
            },
            "general_geometric_coverage_claimed": report["coverage"][
                "general_geometric_coverage_claimed"
            ],
        },
        indent=2,
        default=str,
    )
    exit_code = 0 if (report["benchmark_passed"] and not errors) else 1
    return DemoResult(exit_code, payload=report, summary=summary)


def cmd_sequence_demo(args: argparse.Namespace) -> DemoResult:
    del args

    def feats(n: int, actions: int, peak: float) -> dict[str, Any]:
        return {
            "prior_deliveries": n,
            "prior_delivered": n,
            "prior_actions": actions,
            "prior_max_score": peak,
            "prior_mean_score": peak,
        }

    cases = [
        SequenceCase("sig-1", 1, 0.25, feats(4, 3, 0.25)),
        SequenceCase("sig-2", 1, 0.22, feats(3, 2, 0.24)),
        SequenceCase("ben-1", 0, 0.26, feats(0, 0, 0.0)),
        SequenceCase("ben-2", 0, 0.21, feats(1, 0, 0.2)),
    ]
    return DemoResult(0, payload=benchmark_sequences(cases))


def cmd_replay_demo(args: argparse.Namespace) -> DemoResult:
    del args
    report = run_replay(build_dataset())
    summary = _dump(
        {
            "config": report["config"],
            "by_condition": report["by_condition"],
            "by_payload_band": report["by_payload_band"],
        }
    )
    return DemoResult(0, payload=report, summary=summary)


def cmd_verdict_demo(args: argparse.Namespace) -> DemoResult:
    del args
    rows = []
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=192)
    for fixture in (clean, encoded):
        result = analyze_lsb_bytes(fixture.data)
        decision = decide_verdict(result.findings)
        rows.append(
            {
                "role": fixture.role,
                "payload_band": fixture.payload_band,
                "score": result.findings[0].score if result.findings else None,
                "decision": decision.to_dict(),
            }
        )
    return DemoResult(0, payload=rows)
