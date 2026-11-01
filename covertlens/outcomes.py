"""Run failure and explicit infrastructure outcomes (CL-19, ENF-04).

Two kinds of negative outcome are kept strictly apart (C-02):

- **Detection failures.** A `fail_run` verdict from the CL-17 ladder
  emits a structured eval-failure reason naming the family, detector,
  score and enforcement point that produced it. This is an eval
  outcome about the artifact, still never proof of collusion.
- **Infrastructure outcomes.** Corrupt, unsupported, oversized and
  timed-out inputs, detector errors and gate errors follow the CL-7
  manifest error classes. They withhold delivery, record an
  infrastructure outcome, and produce *no* clean verdict — and are
  never equated with a detection failure.

`evaluate_delivery` is the enforcement pipeline for one pending gate
delivery: parse (CL-13) → detectors (CL-14/15/23 callables) → verdict
(CL-17), classifying every failure on the way.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .events import Verdict
from .gate import InterceptionGate
from .manifest import ERROR_CLASSES, load_manifest
from .parsing import AnalysisResult, AnalysisStatus, analyze_bytes
from .verdicts import DecisionContext, ThresholdConfig, VerdictDecision

OUTCOME_SCHEMA = "covertlens.run-outcome"
OUTCOME_SCHEMA_VERSION = 1
OUTCOME_VERSION = "1.0.0"

_STATUS_TO_ERROR_CLASS = {
    AnalysisStatus.CORRUPT: "corrupt_input",
    AnalysisStatus.UNSUPPORTED_FORMAT: "unsupported_format",
    AnalysisStatus.UNSUPPORTED_ENCODING: "unsupported_format",
    AnalysisStatus.OVERSIZED: "oversized_input",
    AnalysisStatus.TIMEOUT: "analysis_timeout",
}


def error_class_for_status(status: AnalysisStatus) -> str | None:
    """Manifest error class for a failed parse status (None when parsed)."""
    return _STATUS_TO_ERROR_CLASS.get(status)


def _base(kind: str, delivery_id: str | None) -> dict[str, Any]:
    return {
        "schema": OUTCOME_SCHEMA,
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "outcome_version": OUTCOME_VERSION,
        "kind": kind,
        "delivery_id": delivery_id,
        "delivery": "withhold",
        "clean_verdict": False,
        "equated_with_collusion": False,
    }


def analysis_outcome(
    result: AnalysisResult, *, delivery_id: str | None = None
) -> dict[str, Any] | None:
    """Infrastructure outcome for a failed parse; None when parsed."""
    error_class = error_class_for_status(result.status)
    if error_class is None:
        return None
    record = _base("infrastructure", delivery_id)
    record.update(
        {
            "error_class": error_class,
            "analysis_status": result.status.value,
            "content_hash": result.content_hash,
            "run_outcome": "failed_infrastructure",
            "detail": (
                result.errors[0]["detail"] if result.errors else result.status.value
            ),
        }
    )
    return record


def detector_error_outcome(
    exc: BaseException, *, delivery_id: str | None = None
) -> dict[str, Any]:
    """Infrastructure outcome for a detector (or gate) error."""
    record = _base("infrastructure", delivery_id)
    record.update(
        {
            "error_class": "detector_error",
            "analysis_status": None,
            "content_hash": None,
            "run_outcome": "failed_infrastructure",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    )
    return record


def failure_reason(decision: VerdictDecision) -> dict[str, Any] | None:
    """Structured eval-failure reason for a fail_run decision (else None)."""
    if decision.verdict is not Verdict.FAIL_RUN:
        return None
    record = _base("detection_failure", decision.delivery_id)
    record["delivery"] = "withhold"
    record["clean_verdict"] = False
    families = [
        row for row in decision.per_family if row["verdict"] == Verdict.FAIL_RUN.value
    ]
    record.update(
        {
            "error_class": None,
            "verdict": decision.verdict.value,
            "halt_execution": True,
            "run_outcome": "failed_detection",
            "reason": {
                "code": "enforcement_threshold_exceeded",
                "families": [
                    {
                        "family": row["family"],
                        "max_score": row["max_score"],
                        "fail_run_at": row["enforcement_fail_run_at"],
                        "detectors": row["detectors"],
                    }
                    for row in families
                ],
                "config_version": decision.config_version,
            },
        }
    )
    return record


def decision_outcome(decision: VerdictDecision) -> dict[str, Any]:
    """Outcome record for any completed ladder decision."""
    reason = failure_reason(decision)
    if reason is not None:
        return reason
    record = _base("decision", decision.delivery_id)
    record.update(
        {
            "delivery": decision.delivery,
            "clean_verdict": decision.verdict in (Verdict.LOG, Verdict.FLAG),
            "error_class": None,
            "verdict": decision.verdict.value,
            "halt_execution": decision.halt_execution,
            "run_outcome": (
                "failed_detection" if decision.halt_execution else "completed"
            ),
            "reason": None,
        }
    )
    return record


Detector = Callable[[AnalysisResult], Any]


def evaluate_delivery(
    gate: InterceptionGate,
    delivery_id: str,
    data: bytes,
    *,
    detectors: Iterable[Detector] = (),
    config: ThresholdConfig | None = None,
    artifact_version_id: str | None = None,
) -> dict[str, Any]:
    """Run parse → detectors → verdict for one pending delivery.

    Returns the outcome record. Parse failures and detector errors
    withhold the delivery as infrastructure outcomes (no verdict is
    recorded); completed decisions are recorded on the gate, with
    `fail_run` carrying its structured reason.
    """
    from .verdicts import decide_and_record  # local: avoids a cycle at import

    try:
        result = analyze_bytes(data, artifact_version_id=artifact_version_id)
    except Exception as exc:  # gate/analysis infrastructure, never a verdict
        gate.withhold_for_infrastructure(delivery_id, "gate_error")
        return detector_error_outcome(exc, delivery_id=delivery_id) | {
            "error_class": "gate_error"
        }
    infra = analysis_outcome(result, delivery_id=delivery_id)
    if infra is not None:
        gate.withhold_for_infrastructure(delivery_id, str(infra["error_class"]))
        return infra
    findings: list[Any] = []
    try:
        for detector in detectors:
            finding = detector(result)
            if finding is not None:
                findings.extend(
                    finding if isinstance(finding, (list, tuple)) else [finding]
                )
    except Exception as exc:
        gate.withhold_for_infrastructure(delivery_id, "detector_error")
        return detector_error_outcome(exc, delivery_id=delivery_id)
    try:
        decision = decide_and_record(
            gate,
            delivery_id,
            findings,
            config,
            context=DecisionContext(
                artifact_version_id=result.artifact_version_id,
                content_hash=result.content_hash,
                delivery_id=delivery_id,
            ),
        )
    except Exception as exc:
        # A decision that cannot be made must not become a clean verdict:
        # if the gate is still pending, withhold as a gate error.
        try:
            gate.withhold_for_infrastructure(delivery_id, "gate_error")
        except Exception:
            pass
        return detector_error_outcome(exc, delivery_id=delivery_id) | {
            "error_class": "gate_error"
        }
    return decision_outcome(decision)


def finalize_run_outcome(records: Iterable[dict[str, Any]]) -> str:
    """Map delivery outcomes to a CL-7 run-finalization outcome.

    Detection failure dominates infrastructure failure; both are
    distinct from completion (C-02)."""
    kinds = [r.get("run_outcome") for r in records]
    if "failed_detection" in kinds:
        return "failed_detection"
    if "failed_infrastructure" in kinds:
        return "failed_infrastructure"
    return "completed"


def validate_outcome(record: dict[str, Any]) -> list[str]:
    """Return validation errors for one outcome record; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(record.get("schema") == OUTCOME_SCHEMA, f"schema must be {OUTCOME_SCHEMA}")
    need(
        record.get("schema_version") == OUTCOME_SCHEMA_VERSION,
        f"schema_version must be {OUTCOME_SCHEMA_VERSION}",
    )
    kind = record.get("kind")
    need(
        kind in ("detection_failure", "infrastructure", "decision"),
        "kind must be detection_failure, infrastructure or decision",
    )
    need(
        record.get("equated_with_collusion") is False,
        "outcomes are never equated with collusion (C-02)",
    )
    if kind == "infrastructure":
        need(
            record.get("error_class") in ERROR_CLASSES,
            f"error_class must be one of {ERROR_CLASSES} (manifest)",
        )
        need(
            record.get("clean_verdict") is False,
            "infrastructure never yields a clean verdict",
        )
        need(record.get("delivery") == "withhold", "infrastructure withholds delivery")
        need(
            record.get("run_outcome") == "failed_infrastructure",
            "infrastructure maps to failed_infrastructure",
        )
    if kind == "detection_failure":
        need(record.get("verdict") == "fail_run", "detection_failure requires fail_run")
        need(record.get("halt_execution") is True, "detection_failure halts execution")
        need(
            bool((record.get("reason") or {}).get("code")),
            "detection_failure needs a structured reason code",
        )
    manifest = load_manifest()
    classes = (manifest.get("error_behavior") or {}).get("classes") or {}
    if record.get("error_class") is not None:
        need(
            classes.get(record["error_class"]) == "no_clean_verdict_withhold",
            "manifest requires no_clean_verdict_withhold for this error class",
        )
    return errors
