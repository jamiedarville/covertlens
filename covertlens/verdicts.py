"""Versioned verdict ladder and threshold configuration (CL-17, ENF-01/02).

Findings become a gate verdict here, and only here. The ladder is the
CL-7 manifest's: `log` and `flag` permit delivery, `quarantine`
withholds it, and `fail_run` withholds it and halts execution. Each
channel family is scored against two separately configured operating
points (C-06): the triage point (`flag_at`, high-recall) decides
log-vs-flag, and the enforcement points (`quarantine_at`,
`fail_run_at`, high-precision) decide withholding. The most severe
family verdict wins for the artifact.

Threshold values are not invented here. The shipped configuration is
built from the allowed-channel manifest and stays
`unfrozen_placeholder` with null points until CL-27 freezes them;
while a family is unfrozen its findings can only produce `log` and
the decision is marked not enforceable. A frozen configuration must
carry ordered points (flag <= quarantine <= fail_run) or it is
rejected.

Pre-delivery decisions use only evidence available at decision time
(C-03, ENF-02): the decision API takes detector findings plus an
optional list of already-observed events, and rejects any recipient
action in that evidence, or any event after the caller's evidence
cutoff, with `LookaheadError`. A verdict is a gate outcome, never
proof of collusion (C-02).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import ids
from .events import Event, EventType, Verdict
from .gate import InterceptionGate
from .manifest import FAMILIES, load_manifest
from .parsing import Finding, validate_finding

LADDER_VERSION = "1.0.0"
CONFIG_VERSION = "1.0.0"
DECISION_SCHEMA = "covertlens.verdict-decision"
DECISION_SCHEMA_VERSION = 1

_SEVERITY = {Verdict.LOG: 0, Verdict.FLAG: 1, Verdict.QUARANTINE: 2, Verdict.FAIL_RUN: 3}
_DELIVERY = {
    Verdict.LOG: "permit",
    Verdict.FLAG: "permit",
    Verdict.QUARANTINE: "withhold",
    Verdict.FAIL_RUN: "withhold",
}


class LookaheadError(ValueError):
    """Decision evidence includes future or recipient-action input (C-03)."""


def delivery_for_verdict(verdict: Verdict) -> str:
    """Manifest ladder mapping: log/flag permit, quarantine/fail withhold."""
    return _DELIVERY[verdict]


@dataclass(frozen=True)
class FamilyThresholds:
    """One family's two operating points (triage vs enforcement)."""

    family: str
    status: str = "unfrozen_placeholder"  # or "frozen" (CL-27)
    triage_flag_at: float | None = None
    enforcement_quarantine_at: float | None = None
    enforcement_fail_run_at: float | None = None

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"family must be one of {FAMILIES}")
        if self.status not in ("unfrozen_placeholder", "frozen"):
            raise ValueError("status must be unfrozen_placeholder or frozen")
        points = (
            self.triage_flag_at,
            self.enforcement_quarantine_at,
            self.enforcement_fail_run_at,
        )
        if self.status == "unfrozen_placeholder":
            if any(p is not None for p in points):
                raise ValueError(
                    "unfrozen thresholds carry no invented numbers (CL-27 freezes)"
                )
            return
        if any(p is None for p in points):
            raise ValueError("frozen thresholds need all three operating points")
        for point in points:
            if not 0.0 <= float(point) <= 1.0:  # type: ignore[arg-type]
                raise ValueError("operating points must lie in [0, 1]")
        if not (
            float(self.triage_flag_at)  # type: ignore[arg-type]
            <= float(self.enforcement_quarantine_at)  # type: ignore[arg-type]
            <= float(self.enforcement_fail_run_at)  # type: ignore[arg-type]
        ):
            raise ValueError(
                "operating points must satisfy flag_at <= quarantine_at <= fail_run_at"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "status": self.status,
            "triage": {
                "operating_point": "high_recall",
                "flag_at": self.triage_flag_at,
            },
            "enforcement": {
                "operating_point": "high_precision",
                "quarantine_at": self.enforcement_quarantine_at,
                "fail_run_at": self.enforcement_fail_run_at,
            },
        }


@dataclass(frozen=True)
class ThresholdConfig:
    """Versioned per-family threshold configuration (separate points, C-06)."""

    version: str = CONFIG_VERSION
    ladder_version: str = LADDER_VERSION
    families: dict[str, FamilyThresholds] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        for family, thresholds in self.families.items():
            if thresholds.family != family:
                raise ValueError(f"families[{family!r}] holds {thresholds.family!r}")

    def for_family(self, family: str) -> FamilyThresholds:
        """Points for one family; unknown families are unfrozen/log-only."""
        return self.families.get(family, FamilyThresholds(family=family))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ladder_version": self.ladder_version,
            "families": {
                family: self.families[family].to_dict()
                for family in FAMILIES
                if family in self.families
            },
        }


def threshold_config_from_manifest(
    manifest: dict[str, Any] | None = None,
) -> ThresholdConfig:
    """Build the shipped (unfrozen) config from the CL-7 manifest."""
    doc = manifest if manifest is not None else load_manifest()
    families: dict[str, FamilyThresholds] = {}
    for channel in doc.get("channels") or []:
        thresholds = channel.get("thresholds") or {}
        triage = thresholds.get("triage") or {}
        enforcement = thresholds.get("enforcement") or {}
        families[channel["family"]] = FamilyThresholds(
            family=channel["family"],
            status=thresholds.get("status") or "unfrozen_placeholder",
            triage_flag_at=triage.get("flag_at"),
            enforcement_quarantine_at=enforcement.get("quarantine_at"),
            enforcement_fail_run_at=enforcement.get("fail_run_at"),
        )
    return ThresholdConfig(families=families)


DEFAULT_CONFIG = threshold_config_from_manifest()


def validate_threshold_config(config: ThresholdConfig | dict[str, Any]) -> list[str]:
    """Return validation errors for a threshold config; empty is valid."""
    data = config.to_dict() if isinstance(config, ThresholdConfig) else dict(config)
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(bool(data.get("version")), "version is required")
    families = data.get("families") or {}
    for family in FAMILIES:
        need(family in families, f"families.{family} is required")
    for family, block in families.items():
        prefix = f"families[{family}]"
        try:
            FamilyThresholds(
                family=family,
                status=block.get("status"),
                triage_flag_at=(block.get("triage") or {}).get("flag_at"),
                enforcement_quarantine_at=(block.get("enforcement") or {}).get("quarantine_at"),
                enforcement_fail_run_at=(block.get("enforcement") or {}).get("fail_run_at"),
            )
        except (ValueError, AttributeError) as exc:
            errors.append(f"{prefix}: {exc}")
        need(
            (block.get("triage") or {}).get("operating_point") == "high_recall",
            f"{prefix}.triage must be the high_recall point (C-06)",
        )
        need(
            (block.get("enforcement") or {}).get("operating_point") == "high_precision",
            f"{prefix}.enforcement must be the high_precision point (C-06)",
        )
    return errors


@dataclass(frozen=True)
class DecisionContext:
    """Pre-delivery evidence binding for one decision (C-03)."""

    artifact_version_id: str | None = None
    content_hash: str | None = None
    delivery_id: str | None = None
    evidence_through_seq: int | None = None


@dataclass(frozen=True)
class VerdictDecision:
    """One ladder decision; JSON shape is the verdict-decision schema."""

    verdict: Verdict
    delivery: str  # permit | withhold (manifest ladder)
    halt_execution: bool
    enforceable: bool
    config_version: str
    ladder_version: str
    artifact_version_id: str | None
    content_hash: str | None
    delivery_id: str | None
    per_family: tuple[dict[str, Any], ...] = ()
    findings_count: int = 0
    families_without_findings: tuple[str, ...] = ()

    @property
    def equated_with_collusion(self) -> bool:
        """A verdict is a gate outcome, never demonstrated collusion (C-02)."""
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DECISION_SCHEMA,
            "schema_version": DECISION_SCHEMA_VERSION,
            "verdict": self.verdict.value,
            "delivery": self.delivery,
            "halt_execution": self.halt_execution,
            "enforceable": self.enforceable,
            "equated_with_collusion": False,
            "config_version": self.config_version,
            "ladder_version": self.ladder_version,
            "artifact_version_id": self.artifact_version_id,
            "content_hash": self.content_hash,
            "delivery_id": self.delivery_id,
            "per_family": [dict(row) for row in self.per_family],
            "findings_count": self.findings_count,
            "families_without_findings": list(self.families_without_findings),
        }


def _family_verdict(score: float, thresholds: FamilyThresholds) -> Verdict:
    if thresholds.status != "frozen":
        return Verdict.LOG
    if score >= float(thresholds.enforcement_fail_run_at):  # type: ignore[arg-type]
        return Verdict.FAIL_RUN
    if score >= float(thresholds.enforcement_quarantine_at):  # type: ignore[arg-type]
        return Verdict.QUARANTINE
    if score >= float(thresholds.triage_flag_at):  # type: ignore[arg-type]
        return Verdict.FLAG
    return Verdict.LOG


def decide_verdict(
    findings: Iterable[Finding | dict[str, Any]],
    config: ThresholdConfig | None = None,
    *,
    context: DecisionContext | None = None,
    observed_events: Iterable[Event] = (),
) -> VerdictDecision:
    """Map detector findings to one ladder verdict (pre-delivery only).

    `observed_events` is evidence the caller claims was available at
    decision time: any recipient action in it, or any event after
    `context.evidence_through_seq`, raises `LookaheadError` instead
    of being silently ignored (C-03). Findings are validated against
    the DET-02 schema; the most severe family verdict wins.
    """
    active = config or DEFAULT_CONFIG
    ctx = context or DecisionContext()
    if ctx.content_hash is not None and not ids.is_content_hash(ctx.content_hash):
        raise ValueError("content_hash must be sha256:<hex> of the original bytes")
    for event in observed_events:
        if event.event_type is EventType.RECIPIENT_ACTION:
            raise LookaheadError(
                "recipient actions are post-delivery evidence and can never "
                "decide a pre-delivery verdict (C-03)"
            )
        if (
            ctx.evidence_through_seq is not None
            and event.seq > ctx.evidence_through_seq
        ):
            raise LookaheadError(
                f"event seq {event.seq} is after the decision cutoff "
                f"{ctx.evidence_through_seq} (lookahead, C-03)"
            )

    rows: list[Finding] = []
    for item in findings:
        problems = validate_finding(item)
        if problems:
            raise ValueError(f"invalid finding: {'; '.join(problems)}")
        rows.append(
            item
            if isinstance(item, Finding)
            else Finding(
                family=item["family"],
                detector_name=item["detector_name"],
                detector_version=item["detector_version"],
                score=float(item["score"]),
                coverage=dict(item.get("coverage") or {}),
                evidence=dict(item.get("evidence") or {}),
                limitations=tuple(item.get("limitations") or ()),
                schema_version=item.get("schema_version") or "1.0.0",
            )
        )

    per_family: list[dict[str, Any]] = []
    worst = Verdict.LOG
    enforceable = True
    seen: set[str] = set()
    for family in FAMILIES:
        family_rows = [r for r in rows if r.family == family]
        if not family_rows:
            continue
        seen.add(family)
        thresholds = active.for_family(family)
        if thresholds.status != "frozen":
            enforceable = False
        max_score = max(r.score for r in family_rows)
        verdict = _family_verdict(max_score, thresholds)
        worst = max(worst, verdict, key=lambda v: _SEVERITY[v])
        per_family.append(
            {
                "family": family,
                "max_score": round(max_score, 6),
                "findings": len(family_rows),
                "detectors": sorted(
                    {f"{r.detector_name}@{r.detector_version}" for r in family_rows}
                ),
                "thresholds_status": thresholds.status,
                "triage_flag_at": thresholds.triage_flag_at,
                "enforcement_quarantine_at": thresholds.enforcement_quarantine_at,
                "enforcement_fail_run_at": thresholds.enforcement_fail_run_at,
                "verdict": verdict.value,
            }
        )
    return VerdictDecision(
        verdict=worst,
        delivery=delivery_for_verdict(worst),
        halt_execution=worst is Verdict.FAIL_RUN,
        enforceable=enforceable,
        config_version=active.version,
        ladder_version=active.ladder_version,
        artifact_version_id=ctx.artifact_version_id,
        content_hash=ctx.content_hash,
        delivery_id=ctx.delivery_id,
        per_family=tuple(per_family),
        findings_count=len(rows),
        families_without_findings=tuple(f for f in FAMILIES if f not in seen),
    )


def decide_and_record(
    gate: InterceptionGate,
    delivery_id: str,
    findings: Iterable[Finding | dict[str, Any]],
    config: ThresholdConfig | None = None,
    *,
    context: DecisionContext | None = None,
    observed_events: Iterable[Event] = (),
) -> VerdictDecision:
    """Decide and bind the verdict to a pending CL-12 gate delivery."""
    ctx = context or DecisionContext(delivery_id=delivery_id)
    if ctx.delivery_id is not None and ctx.delivery_id != delivery_id:
        raise ValueError("context delivery_id does not match the gate delivery")
    decision = decide_verdict(
        findings,
        config,
        context=DecisionContext(
            artifact_version_id=ctx.artifact_version_id,
            content_hash=ctx.content_hash,
            delivery_id=delivery_id,
            evidence_through_seq=ctx.evidence_through_seq,
        ),
        observed_events=observed_events,
    )
    gate.record_verdict(delivery_id, decision.verdict)
    return decision


def validate_decision(decision: VerdictDecision | dict[str, Any]) -> list[str]:
    """Return validation errors for one verdict decision; empty is valid."""
    data = decision.to_dict() if isinstance(decision, VerdictDecision) else dict(decision)
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(data.get("schema") == DECISION_SCHEMA, f"schema must be {DECISION_SCHEMA}")
    need(
        data.get("schema_version") == DECISION_SCHEMA_VERSION,
        f"schema_version must be {DECISION_SCHEMA_VERSION}",
    )
    verdict = data.get("verdict")
    need(verdict in {v.value for v in Verdict}, "verdict must be a ladder value")
    if verdict in {v.value for v in Verdict}:
        value = Verdict(verdict)
        need(
            data.get("delivery") == delivery_for_verdict(value),
            "delivery must follow the ladder (log/flag permit, quarantine/fail withhold)",
        )
        need(
            data.get("halt_execution") is (value is Verdict.FAIL_RUN),
            "halt_execution must be true exactly for fail_run",
        )
    need(
        data.get("equated_with_collusion") is False,
        "a verdict is never equated with collusion (C-02)",
    )
    need(bool(data.get("config_version")), "config_version is required")
    need(bool(data.get("ladder_version")), "ladder_version is required")
    digest = data.get("content_hash")
    if digest is not None:
        need(ids.is_content_hash(digest), "content_hash must be sha256:<hex>")
    return errors
