"""Artifact-store interception and pending delivery (CL-12, EV-06/EV-07).

The single authoritative hook for inter-agent image transfers. Every
gated route in the CL-7 inventory (R-01…R-07) funnels bytes or
references through ``InterceptionGate`` into the CL-8 immutable store
before any recipient access; reviewer evidence access (R-08) is not a
delivery route and is rejected here (it belongs to the CL-11 gateway).

Deliveries are pending — no recipient bytes — until a verdict from the
CL-7 ladder permits them: ``log``/``flag`` permit, ``quarantine`` /
``fail_run`` withhold for that delivery. Verdicts bind to the exact
artifact version in the store, so changed bytes invalidate them and
need a fresh verdict. Repeated references resolve to the same
immutable version with one creation event, and delivery retries reuse
the deterministic ``delivery_id`` with one attempted event. Every step
emits CL-7 events into the per-run ``TraceLog`` with stable run,
episode, sender, recipient, artifact-version and content-hash
identities. Pre-delivery decisions use no future recipient actions
(C-03); a verdict is a gate outcome, never proof of collusion (C-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import ids
from .events import Event, EventType, ParseStatus, TraceLog, Verdict
from .manifest import load_manifest
from .routes import ROUTES, Route
from .store import ArtifactStore, ArtifactVersion


class PendingDeliveryError(PermissionError):
    """Recipient access attempted before a permitting verdict."""


class WithheldError(PermissionError):
    """Recipient access attempted on a quarantined/failed delivery."""


class UnknownDeliveryError(KeyError):
    """The delivery ID is not known to this gate."""


@dataclass(frozen=True)
class InterceptionContext:
    run_id: str
    sender_id: str
    episode_id: str | None = None
    artifact_id: str | None = None


@dataclass
class DeliveryRecord:
    delivery_id: str
    run_id: str
    artifact_id: str
    artifact_version_id: str
    content_hash: str
    sender_id: str
    recipient_id: str
    attempt: int
    episode_id: str | None = None
    state: str = "pending"  # pending | permitted | withheld
    verdict_id: str | None = None
    verdict: Verdict | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InterceptionGate:
    """One gate for every inventoried image path, over the CL-8 store."""

    def __init__(
        self, store: ArtifactStore, manifest: dict[str, Any] | None = None
    ) -> None:
        self._store = store
        doc = manifest if manifest is not None else load_manifest()
        self._ladder = {
            row["verdict"]: row["delivery"]
            for row in doc.get("verdict_ladder") or []
            if isinstance(row, dict)
        }
        self._routes: dict[str, Route] = {r.route_id: r for r in ROUTES}
        self._logs: dict[str, TraceLog] = {}
        self._handles: dict[str, ArtifactVersion] = {}
        self._version_context: dict[str, InterceptionContext] = {}
        self._known_versions: set[str] = set()
        self._references: dict[tuple[str, str], str] = {}
        self._deliveries: dict[str, DeliveryRecord] = {}
        self._covered: set[str] = set()

    @property
    def store(self) -> ArtifactStore:
        return self._store

    # -- interception ----------------------------------------------------

    def _route(self, route_id: str) -> Route:
        route = self._routes.get(route_id)
        if route is None:
            raise ValueError(f"unknown route: {route_id}")
        if not route.gate_required:
            raise ValueError(
                f"{route_id} is review-only evidence access, not a delivery route"
            )
        return route

    def intercept_bytes(
        self, route_id: str, data: bytes, ctx: InterceptionContext
    ) -> ArtifactVersion:
        """Ingest exact bytes for one route; emit ``artifact.created`` once."""
        self._route(route_id)
        version = self._store.put_original(
            data,
            run_id=ctx.run_id,
            producer_id=ctx.sender_id,
            episode_id=ctx.episode_id,
            artifact_id=ctx.artifact_id,
            source_route=route_id,
        )
        self._covered.add(route_id)
        self._handles[version.artifact_version_id] = version
        self._version_context[version.artifact_version_id] = ctx
        if version.artifact_version_id not in self._known_versions:
            self._known_versions.add(version.artifact_version_id)
            self._emit(
                ctx.run_id,
                EventType.ARTIFACT_CREATED,
                episode_id=ctx.episode_id,
                artifact_id=version.artifact_id,
                artifact_version_id=version.artifact_version_id,
                content_hash=version.content_hash,
                sender_id=ctx.sender_id,
            )
        return version

    def intercept_reference(
        self,
        route_id: str,
        reference: str,
        resolver: Callable[[str], bytes],
        ctx: InterceptionContext,
    ) -> ArtifactVersion:
        """Resolve a file/tool-output reference once; repeats are idempotent."""
        self._route(route_id)
        key = (route_id, reference)
        known = self._references.get(key)
        if known is not None:
            return self._handles[known]
        version = self.intercept_bytes(route_id, resolver(reference), ctx)
        self._references[key] = version.artifact_version_id
        return version

    # -- delivery lifecycle ------------------------------------------------

    def attempt_delivery(
        self,
        handle: ArtifactVersion,
        *,
        recipient_id: str,
        attempt: int = 1,
    ) -> DeliveryRecord:
        """Create (or reuse, on retry) a pending delivery for one version."""
        ctx = self._version_context[handle.artifact_version_id]
        delivery_id = ids.delivery_id(
            ctx.run_id, handle.artifact_version_id, recipient_id, attempt
        )
        existing = self._deliveries.get(delivery_id)
        if existing is not None:
            return existing
        record = DeliveryRecord(
            delivery_id=delivery_id,
            run_id=ctx.run_id,
            episode_id=ctx.episode_id,
            artifact_id=handle.artifact_id,
            artifact_version_id=handle.artifact_version_id,
            content_hash=handle.content_hash,
            sender_id=ctx.sender_id,
            recipient_id=recipient_id,
            attempt=attempt,
        )
        self._deliveries[delivery_id] = record
        self._emit(
            ctx.run_id,
            EventType.DELIVERY_ATTEMPTED,
            episode_id=ctx.episode_id,
            artifact_id=handle.artifact_id,
            artifact_version_id=handle.artifact_version_id,
            content_hash=handle.content_hash,
            delivery_id=delivery_id,
            sender_id=ctx.sender_id,
            recipient_id=recipient_id,
        )
        return record

    def record_verdict(self, delivery_id: str, verdict: Verdict) -> DeliveryRecord:
        """Bind a ladder verdict to the delivery's exact artifact version."""
        record = self._delivery(delivery_id)
        if record.state != "pending":
            raise ValueError(f"delivery {delivery_id} already decided ({record.state})")
        verdict_id = ids.new_verdict_id()
        self._store.register_verdict(verdict_id, record.artifact_version_id)
        record.verdict_id = verdict_id
        record.verdict = verdict
        record.state = (
            "permitted" if self._ladder.get(verdict.value) == "permit" else "withheld"
        )
        self._emit(
            record.run_id,
            EventType.GATE_VERDICT,
            episode_id=record.episode_id,
            artifact_id=record.artifact_id,
            artifact_version_id=record.artifact_version_id,
            content_hash=record.content_hash,
            delivery_id=delivery_id,
            verdict_id=verdict_id,
            verdict=verdict,
            sender_id=record.sender_id,
            recipient_id=record.recipient_id,
        )
        return record

    def recipient_access(self, delivery_id: str) -> bytes:
        """Serve original bytes only after a permitting verdict."""
        record = self._delivery(delivery_id)
        if record.state == "pending":
            raise PendingDeliveryError(
                f"delivery {delivery_id} awaits a verdict; no bytes served"
            )
        if record.state == "withheld":
            raise WithheldError(
                f"delivery {delivery_id} was withheld; no bytes served"
            )
        data = self._store.get_original(
            record.artifact_version_id, actor_id=record.recipient_id, purpose="delivery"
        )
        self._emit(
            record.run_id,
            EventType.ARTIFACT_ACCESSED,
            episode_id=record.episode_id,
            artifact_id=record.artifact_id,
            artifact_version_id=record.artifact_version_id,
            content_hash=record.content_hash,
            delivery_id=delivery_id,
            sender_id=record.sender_id,
            recipient_id=record.recipient_id,
        )
        return data

    def record_parse(self, delivery_id: str, parse_status: ParseStatus) -> Event:
        """Record recipient parse; withheld deliveries only ``not_observed``."""
        record = self._delivery(delivery_id)
        return self._emit(
            record.run_id,
            EventType.ARTIFACT_PARSED,
            episode_id=record.episode_id,
            artifact_id=record.artifact_id,
            artifact_version_id=record.artifact_version_id,
            content_hash=record.content_hash,
            delivery_id=delivery_id,
            parse_status=parse_status,
            sender_id=record.sender_id,
            recipient_id=record.recipient_id,
        )

    # -- reporting ---------------------------------------------------------

    def coverage_report(self) -> dict[str, Any]:
        gated = {r.route_id for r in ROUTES if r.gate_required}
        return {
            "covered": sorted(self._covered & gated),
            "missing": sorted(gated - self._covered),
            "exempt": sorted(r.route_id for r in ROUTES if not r.gate_required),
        }

    def events(self, run_id: str) -> list[Event]:
        log = self._logs.get(run_id)
        return list(log.events) if log is not None else []

    # -- internals -----------------------------------------------------------

    def _delivery(self, delivery_id: str) -> DeliveryRecord:
        try:
            return self._deliveries[delivery_id]
        except KeyError:
            raise UnknownDeliveryError(delivery_id) from None

    def _emit(self, run_id: str, event_type: EventType, **kw: Any) -> Event:
        log = self._logs.setdefault(run_id, TraceLog(run_id))
        event = Event(
            event_type=event_type,
            run_id=run_id,
            seq=len(log.events),
            occurred_at=_now(),
            **kw,
        )
        return log.append(event)
