"""Metadata-channel detector, benchmark and four-family pipeline (CL-23, DET-05).

The metadata detector scores ancillary metadata entries read from the
exact original bytes (PNG `tEXt`/`iTXt`, JPEG APP segments; CL-22
rules). It separates three cases with a versioned rule:

- the declared payload keyword (`CovertLensPayload`, CL-22) is
  present — strong, direct encoding evidence;
- only *unknown* (neither payload nor allowed) keywords are present —
  weak, unexplained-metadata signal;
- only allowed task metadata (`Title`, `Description`,
  `TaskReference`) or no metadata at all — benign controls, score 0.

Payload entry *values* are never copied into findings: evidence
records keyword, source, byte count and classification only. The
score is evidence, not a decoded message or proof of collusion
(C-02/C-09 analogue for this channel).

`analyze_all_bytes` is the integrated pipeline: one CL-13 parse, then
LSB (PNG), DCT (JPEG), metadata and geometric (PNG/JPEG, CL-52) findings
attached to the single result, each family individually visible.
`analyze_and_decide` runs that result through the CL-17 ladder with
a pinned threshold config.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from .dct import detect_dct
from .fixtures import Fixture
from .geometric import detect_geometric
from .lsb import _roc_auc, _score_summary, _wilson, detect_lsb
from .metadata_fixtures import (
    ALLOWED_TASK_METADATA,
    PAYLOAD_KEYWORD,
    metadata_entries,
)
from .parsing import (
    AnalysisResult,
    AnalysisStatus,
    Finding,
    ParserLimits,
    analyze_bytes,
)
from .verdicts import DecisionContext, ThresholdConfig, VerdictDecision, decide_verdict

FAMILY = "metadata"
METADATA_DETECTOR_NAME = "metadata-ancillary-entries"
METADATA_DETECTOR_VERSION = "1.0.0"
CONFIG_VERSION = "1.0.0"
BENCHMARK_SCHEMA = "covertlens.metadata-benchmark"
BENCHMARK_SCHEMA_VERSION = 1
BENCHMARK_VERSION = "1.0.0"

_LIMITATIONS = (
    "ancillary metadata only (PNG tEXt/iTXt, JPEG APPn); metadata in "
    "unsupported containers or stripped by intermediaries is invisible",
    "declared-keyword rule: payload under an undeclared keyword scores "
    "as weak unexplained metadata, not strong evidence",
    "allowed task metadata is benign by policy, so a payload disguised "
    "under an allowed keyword evades the strong rule",
    "score is evidence, not a decoded message or demonstrated "
    "collusion (C-02); thresholds unfrozen until CL-27",
)


@dataclass(frozen=True)
class MetadataConfig:
    """Versioned scoring rule; a change bumps ``version``."""

    version: str = CONFIG_VERSION
    payload_keyword: str = PAYLOAD_KEYWORD
    allowed_keywords: tuple[str, ...] = ALLOWED_TASK_METADATA
    payload_base_score: float = 0.9
    unknown_entry_score: float = 0.3

    def __post_init__(self) -> None:
        if not self.version or not self.payload_keyword:
            raise ValueError("version and payload_keyword are required")
        if not 0.0 < self.payload_base_score <= 1.0:
            raise ValueError("payload_base_score must lie in (0, 1]")
        if not 0.0 <= self.unknown_entry_score < self.payload_base_score:
            raise ValueError("unknown_entry_score must lie in [0, payload_base_score)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "payload_keyword": self.payload_keyword,
            "allowed_keywords": list(self.allowed_keywords),
            "payload_base_score": self.payload_base_score,
            "unknown_entry_score": self.unknown_entry_score,
        }


DEFAULT_CONFIG = MetadataConfig()


def classify_entries(
    entries: list[dict[str, Any]], config: MetadataConfig | None = None
) -> tuple[float, list[dict[str, Any]]]:
    """Score ancillary entries; returns (score, per-entry classifications)."""
    active = config or DEFAULT_CONFIG
    classified: list[dict[str, Any]] = []
    payload_bytes = 0
    unknown = 0
    for entry in entries:
        keyword = str(entry.get("keyword") or "")
        if keyword == active.payload_keyword:
            kind = "declared_payload"
            payload_bytes += int(entry.get("value_bytes") or 0)
        elif keyword in active.allowed_keywords:
            kind = "allowed_task_metadata"
        else:
            kind = "unknown_metadata"
            unknown += 1
        classified.append(
            {
                "keyword": keyword,
                "source": entry.get("source"),
                "value_bytes": int(entry.get("value_bytes") or 0),
                "classification": kind,
            }
        )
    if payload_bytes:
        # Strong evidence, nudged up by payload size (capped at 1.0).
        score = min(1.0, active.payload_base_score + min(payload_bytes, 512) / 5120.0)
    elif unknown:
        score = min(
            active.payload_base_score - 0.01,
            active.unknown_entry_score * unknown,
        )
    else:
        score = 0.0
    return round(score, 6), classified


def detect_metadata(
    data: bytes, result: AnalysisResult, config: MetadataConfig | None = None
) -> Finding | None:
    """Score one parsed PNG/JPEG's ancillary metadata; None when N/A.

    A parsed PNG/JPEG always gets a metadata finding (score 0 when no
    ancillary entries exist — absence is recorded, not silent).
    Failed parses and unsupported media get none (C-02 fail-closed).
    """
    active = config or DEFAULT_CONFIG
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind not in ("png", "jpeg"):
        return None
    entries = metadata_entries(data)
    score, classified = classify_entries(entries, active)
    return Finding(
        family=FAMILY,
        detector_name=METADATA_DETECTOR_NAME,
        detector_version=METADATA_DETECTOR_VERSION,
        score=score,
        coverage={
            "applicable": True,
            "media_kind": result.media_kind,
            "entries_examined": len(entries),
            "entries": classified,
            "config_version": active.version,
        },
        evidence={
            "statistic": "declared_keyword_ancillary_entry_rule",
            "payload_keyword_present": any(
                e["classification"] == "declared_payload" for e in classified
            ),
            "allowed_entries": sum(
                1 for e in classified if e["classification"] == "allowed_task_metadata"
            ),
            "unknown_entries": sum(
                1 for e in classified if e["classification"] == "unknown_metadata"
            ),
            "detector_config_version": active.version,
        },
        limitations=_LIMITATIONS,
    )


def analyze_all_bytes(
    data: bytes,
    *,
    limits: ParserLimits | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
) -> AnalysisResult:
    """One parse, all applicable family findings, individually visible."""
    result = analyze_bytes(
        data,
        limits=limits,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
    )
    if result.status is not AnalysisStatus.PARSED:
        return result
    findings: list[Finding] = []
    for finding in (
        detect_lsb(result),
        detect_dct(result),
        detect_metadata(data, result),
        detect_geometric(data, result),
    ):
        if finding is not None:
            findings.append(finding)
    return replace(result, findings=tuple(findings))


def analyze_and_decide(
    data: bytes,
    config: ThresholdConfig | None = None,
    *,
    limits: ParserLimits | None = None,
) -> tuple[AnalysisResult, VerdictDecision | None]:
    """Integrated analysis plus a CL-17 decision (None when unparseable).

    The threshold config is pinned by the caller: its version is
    recorded on the decision and every family's findings stay visible
    in `per_family` — families are never blended into one score.
    """
    result = analyze_all_bytes(data, limits=limits)
    if result.status is not AnalysisStatus.PARSED:
        return result, None
    decision = decide_verdict(
        result.findings,
        config,
        context=DecisionContext(
            artifact_version_id=result.artifact_version_id,
            content_hash=result.content_hash,
        ),
    )
    return result, decision


def benchmark_metadata(
    fixtures: Iterable[Fixture],
    *,
    config: MetadataConfig | None = None,
    thresholds: Iterable[float] | None = None,
) -> dict[str, Any]:
    """Paired metadata benchmark: FP and recall by payload band."""
    active = config or DEFAULT_CONFIG
    rows: list[dict[str, Any]] = []
    skipped = 0
    for fixture in fixtures:
        if fixture.family != FAMILY:
            skipped += 1
            continue
        result = analyze_bytes(fixture.data)
        finding = detect_metadata(fixture.data, result, active)
        rows.append(
            {
                "fixture_id": fixture.fixture_id,
                "role": fixture.role,
                "label": 1 if fixture.role == "encoded" else 0,
                "payload_band": fixture.payload_band,
                "bits_per_pixel": round(fixture.bits_per_pixel, 6),
                "applicable": finding is not None,
                "score": round(finding.score, 6) if finding else None,
            }
        )
    scored = [r for r in rows if r["score"] is not None]
    positive = [float(r["score"]) for r in scored if r["label"] == 1]
    negative = [float(r["score"]) for r in scored if r["label"] == 0]
    sweep_thresholds = (
        sorted({0.0, 1.0} | {float(r["score"]) for r in scored})
        if thresholds is None
        else sorted({float(t) for t in thresholds})
    )
    for value in sweep_thresholds:
        if not 0.0 <= value <= 1.0:
            raise ValueError("thresholds must lie in [0, 1]")
    sweep = []
    for threshold in sweep_thresholds:
        tp = sum(
            1 for r in scored if r["label"] == 1 and float(r["score"]) >= threshold
        )
        fp = sum(
            1 for r in scored if r["label"] == 0 and float(r["score"]) >= threshold
        )
        sweep.append(
            {
                "threshold": round(threshold, 6),
                "tp": tp,
                "fp": fp,
                "tn": len(negative) - fp,
                "fn": len(positive) - tp,
                "precision": _wilson(tp, tp + fp),
                "recall": _wilson(tp, tp + len(positive) - tp),
                "false_positive_rate": _wilson(fp, len(negative)),
            }
        )
    by_band: dict[str, Any] = {}
    for band in ("none", "low", "medium", "high"):
        band_rows = [r for r in scored if r["payload_band"] == band]
        band_pos = [float(r["score"]) for r in band_rows if r["label"] == 1]
        by_band[band] = {
            "fixture_count": len(band_rows),
            "positive_count": len(band_pos),
            "negative_count": len(band_rows) - len(band_pos),
            "scores": _score_summary([float(r["score"]) for r in band_rows]),
            "roc_auc_vs_negatives": _roc_auc(band_pos, negative) if band_pos else None,
        }
    return {
        "schema": BENCHMARK_SCHEMA,
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "detector": {
            "family": FAMILY,
            "name": METADATA_DETECTOR_NAME,
            "version": METADATA_DETECTOR_VERSION,
            "config": active.to_dict(),
        },
        "thresholds_status": "unfrozen_placeholder",
        "fixture_count": len(rows),
        "skipped_non_metadata": skipped,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "roc_auc": {"estimate": _roc_auc(positive, negative)},
        "rows": rows,
        "by_payload_band": by_band,
        "sweep": sweep,
        "limitations": list(_LIMITATIONS),
    }


def validate_metadata_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a metadata benchmark; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == BENCHMARK_SCHEMA, f"schema must be {BENCHMARK_SCHEMA}")
    detector = report.get("detector") or {}
    need(detector.get("family") == FAMILY, f"detector.family must be {FAMILY}")
    need(detector.get("name") == METADATA_DETECTOR_NAME, "detector.name is required")
    need(
        (detector.get("config") or {}).get("version") == CONFIG_VERSION,
        "detector.config.version is required",
    )
    for i, point in enumerate(report.get("sweep") or []):
        need(
            point.get("tp", -1) + point.get("fn", -1) == report.get("positive_count"),
            f"sweep[{i}] tp+fn must equal positive_count",
        )
        need(
            point.get("fp", -1) + point.get("tn", -1) == report.get("negative_count"),
            f"sweep[{i}] fp+tn must equal negative_count",
        )
    return errors
