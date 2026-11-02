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

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


class ReviewerAccessError(PermissionError):
    """Quarantined evidence requested by a non-reviewer (CL-18)."""


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
    infrastructure_error: str | None = None  # CL-19: withheld without a verdict


def _now() -> str:
    return datetime.now(UTC).isoformat()


class InterceptionGate:
    """One gate for every inventoried image path, over the CL-8 store.

    When the store is file-backed, gate state (deliveries, access
    attempts, trace events, references, cached links) persists to
    SQLite under the store root (``gate.sqlite3``, CL-53) and is
    restored on construction, so a restart mid-run leaves the run,
    deliveries and trace intact. In-memory stores keep the gate
    purely in memory.
    """

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
        # CL-18: one lock serialises verdict/access so no concurrent
        # attempt can observe a half-decided delivery; every access
        # attempt is recorded for the zero-unauthorized-access audit.
        self._lock = threading.RLock()
        self._access_attempts: list[dict[str, Any]] = []
        self._cached_links: dict[str, str] = {}
        self._db: sqlite3.Connection | None = None
        store_root = getattr(store, "root", None)
        if store_root is not None:
            self._init_db(Path(store_root))
            self._load_state()

    @property
    def store(self) -> ArtifactStore:
        return self._store

    # -- persistence (CL-53) ---------------------------------------------

    def _init_db(self, root: Path) -> None:
        db_path = root / "gate.sqlite3"
        self._db = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None
        )
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS gate_deliveries (
                delivery_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                artifact_version_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                episode_id TEXT,
                state TEXT NOT NULL,
                verdict_id TEXT,
                verdict TEXT,
                infrastructure_error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_gate_deliveries_run
                ON gate_deliveries(run_id);
            CREATE TABLE IF NOT EXISTS gate_access_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id TEXT NOT NULL,
                via_route TEXT,
                outcome TEXT NOT NULL,
                delivery_state TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_gate_attempts_delivery
                ON gate_access_attempts(delivery_id);
            CREATE TABLE IF NOT EXISTS gate_trace_events (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                episode_id TEXT,
                artifact_id TEXT,
                artifact_version_id TEXT,
                content_hash TEXT,
                delivery_id TEXT,
                verdict_id TEXT,
                sender_id TEXT,
                recipient_id TEXT,
                parse_status TEXT,
                verdict TEXT,
                idempotency_key TEXT,
                payload_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                PRIMARY KEY (run_id, seq)
            );
            CREATE TABLE IF NOT EXISTS gate_references (
                route_id TEXT NOT NULL,
                reference TEXT NOT NULL,
                artifact_version_id TEXT NOT NULL,
                PRIMARY KEY (route_id, reference)
            );
            CREATE TABLE IF NOT EXISTS gate_cached_links (
                token TEXT PRIMARY KEY,
                delivery_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gate_version_context (
                artifact_version_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                episode_id TEXT,
                artifact_id TEXT
            );
            CREATE TABLE IF NOT EXISTS gate_covered (
                route_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS gate_known_versions (
                artifact_version_id TEXT PRIMARY KEY
            );
            """
        )

    def _load_state(self) -> None:
        if self._db is None:
            return
        db = self._db
        for row in db.execute(
            "SELECT delivery_id, run_id, artifact_id, artifact_version_id,"
            " content_hash, sender_id, recipient_id, attempt, episode_id,"
            " state, verdict_id, verdict, infrastructure_error"
            " FROM gate_deliveries"
        ).fetchall():
            verdict = Verdict(row[11]) if row[11] else None
            self._deliveries[row[0]] = DeliveryRecord(
                delivery_id=row[0],
                run_id=row[1],
                artifact_id=row[2],
                artifact_version_id=row[3],
                content_hash=row[4],
                sender_id=row[5],
                recipient_id=row[6],
                attempt=row[7],
                episode_id=row[8],
                state=row[9],
                verdict_id=row[10],
                verdict=verdict,
                infrastructure_error=row[12],
            )
        self._access_attempts = [
            {
                "delivery_id": r[0],
                "via_route": r[1],
                "outcome": r[2],
                "delivery_state": r[3],
            }
            for r in db.execute(
                "SELECT delivery_id, via_route, outcome, delivery_state"
                " FROM gate_access_attempts ORDER BY id"
            ).fetchall()
        ]
        # Trace events grouped by run, in seq order.
        events_by_run: dict[str, list[Event]] = {}
        for r in db.execute(
            "SELECT run_id, seq, event_type, occurred_at, episode_id,"
            " artifact_id, artifact_version_id, content_hash, delivery_id,"
            " verdict_id, sender_id, recipient_id, parse_status, verdict,"
            " idempotency_key, payload_json, schema_version"
            " FROM gate_trace_events ORDER BY run_id, seq"
        ).fetchall():
            try:
                payload = json.loads(r[15]) if r[15] else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            event = Event(
                event_type=EventType(r[2]),
                run_id=r[0],
                seq=r[1],
                occurred_at=r[3],
                episode_id=r[4],
                artifact_id=r[5],
                artifact_version_id=r[6],
                content_hash=r[7],
                delivery_id=r[8],
                verdict_id=r[9],
                sender_id=r[10],
                recipient_id=r[11],
                parse_status=ParseStatus(r[12]) if r[12] else None,
                verdict=Verdict(r[13]) if r[13] else None,
                idempotency_key=r[14],
                payload=payload,
                schema_version=r[16],
            )
            events_by_run.setdefault(r[0], []).append(event)
        for run_id, events in events_by_run.items():
            log = TraceLog(run_id)
            log._events = list(events)  # noqa: SLF001 - restore persisted log
            log._seen_ids = {e.event_id for e in events}  # noqa: SLF001
            log._finalized = any(  # noqa: SLF001
                e.event_type is EventType.RUN_FINALIZED for e in events
            )
            self._logs[run_id] = log
        self._references = {
            (r[0], r[1]): r[2]
            for r in db.execute(
                "SELECT route_id, reference, artifact_version_id FROM gate_references"
            ).fetchall()
        }
        self._cached_links = {
            r[0]: r[1]
            for r in db.execute(
                "SELECT token, delivery_id FROM gate_cached_links"
            ).fetchall()
        }
        for r in db.execute(
            "SELECT artifact_version_id, run_id, sender_id, episode_id,"
            " artifact_id FROM gate_version_context"
        ).fetchall():
            self._version_context[r[0]] = InterceptionContext(
                run_id=r[1],
                sender_id=r[2],
                episode_id=r[3],
                artifact_id=r[4],
            )
        self._covered = {
            r[0] for r in db.execute("SELECT route_id FROM gate_covered").fetchall()
        }
        self._known_versions = {
            r[0]
            for r in db.execute(
                "SELECT artifact_version_id FROM gate_known_versions"
            ).fetchall()
        }
        # Rebuild handles from the store's persisted versions.
        for version_id in self._known_versions:
            try:
                self._handles[version_id] = self._store.get_version(version_id)
            except Exception:
                continue
        for version_id in self._version_context:
            if version_id not in self._handles:
                try:
                    self._handles[version_id] = self._store.get_version(version_id)
                except Exception:
                    continue

    def _persist_delivery(self, record: DeliveryRecord) -> None:
        if self._db is None:
            return
        self._db.execute(
            "INSERT OR REPLACE INTO gate_deliveries"
            " (delivery_id, run_id, artifact_id, artifact_version_id,"
            " content_hash, sender_id, recipient_id, attempt, episode_id,"
            " state, verdict_id, verdict, infrastructure_error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.delivery_id,
                record.run_id,
                record.artifact_id,
                record.artifact_version_id,
                record.content_hash,
                record.sender_id,
                record.recipient_id,
                record.attempt,
                record.episode_id,
                record.state,
                record.verdict_id,
                record.verdict.value if record.verdict else None,
                record.infrastructure_error,
            ),
        )

    def _persist_attempt_row(
        self, delivery_id: str, via_route: str | None, outcome: str, state: str | None
    ) -> None:
        if self._db is None:
            return
        self._db.execute(
            "INSERT INTO gate_access_attempts"
            " (delivery_id, via_route, outcome, delivery_state)"
            " VALUES (?, ?, ?, ?)",
            (delivery_id, via_route, outcome, state),
        )

    def _persist_event(self, event: Event) -> None:
        if self._db is None:
            return
        self._db.execute(
            "INSERT OR REPLACE INTO gate_trace_events"
            " (run_id, seq, event_type, occurred_at, episode_id, artifact_id,"
            " artifact_version_id, content_hash, delivery_id, verdict_id,"
            " sender_id, recipient_id, parse_status, verdict,"
            " idempotency_key, payload_json, schema_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.run_id,
                event.seq,
                event.event_type.value,
                event.occurred_at,
                event.episode_id,
                event.artifact_id,
                event.artifact_version_id,
                event.content_hash,
                event.delivery_id,
                event.verdict_id,
                event.sender_id,
                event.recipient_id,
                event.parse_status.value if event.parse_status else None,
                event.verdict.value if event.verdict else None,
                event.idempotency_key,
                json.dumps(event.payload, sort_keys=True, default=str),
                event.schema_version,
            ),
        )

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
        with self._lock:
            return self._intercept_bytes(route_id, data, ctx)

    def _intercept_bytes(
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
        if self._db is not None:
            self._db.execute(
                "INSERT OR IGNORE INTO gate_covered (route_id) VALUES (?)",
                (route_id,),
            )
            self._db.execute(
                "INSERT OR REPLACE INTO gate_version_context"
                " (artifact_version_id, run_id, sender_id, episode_id, artifact_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    version.artifact_version_id,
                    ctx.run_id,
                    ctx.sender_id,
                    ctx.episode_id,
                    ctx.artifact_id,
                ),
            )
        if version.artifact_version_id not in self._known_versions:
            self._known_versions.add(version.artifact_version_id)
            if self._db is not None:
                self._db.execute(
                    "INSERT OR IGNORE INTO gate_known_versions"
                    " (artifact_version_id) VALUES (?)",
                    (version.artifact_version_id,),
                )
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
        with self._lock:
            return self._intercept_reference(route_id, reference, resolver, ctx)

    def _intercept_reference(
        self,
        route_id: str,
        reference: str,
        resolver: Callable[[str], bytes],
        ctx: InterceptionContext,
    ) -> ArtifactVersion:
        self._route(route_id)
        key = (route_id, reference)
        known = self._references.get(key)
        if known is not None:
            # Handle may need rebuilding after a restart.
            handle = self._handles.get(known)
            if handle is None:
                handle = self._store.get_version(known)
                self._handles[known] = handle
            return handle
        version = self._intercept_bytes(route_id, resolver(reference), ctx)
        self._references[key] = version.artifact_version_id
        if self._db is not None:
            self._db.execute(
                "INSERT OR REPLACE INTO gate_references"
                " (route_id, reference, artifact_version_id) VALUES (?, ?, ?)",
                (route_id, reference, version.artifact_version_id),
            )
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
        with self._lock:
            return self._attempt_delivery(
                handle, recipient_id=recipient_id, attempt=attempt
            )

    def _attempt_delivery(
        self,
        handle: ArtifactVersion,
        *,
        recipient_id: str,
        attempt: int = 1,
    ) -> DeliveryRecord:
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
        self._persist_delivery(record)
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
        with self._lock:
            return self._record_verdict(delivery_id, verdict)

    def _record_verdict(self, delivery_id: str, verdict: Verdict) -> DeliveryRecord:
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
        self._persist_delivery(record)
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

    def recipient_access(
        self, delivery_id: str, *, via_route: str | None = None
    ) -> bytes:
        """Serve original bytes only after a permitting verdict (CL-18).

        Every gated route funnels here: `via_route` is recorded on the
        attempt so direct, cached-link, tool-output and parse-input
        access are audited identically. The check and the serve are
        one locked step, so concurrent attempts cannot race a verdict.
        """
        with self._lock:
            return self._recipient_access(delivery_id, via_route=via_route)

    def _recipient_access(
        self, delivery_id: str, *, via_route: str | None = None
    ) -> bytes:
        record = self._delivery(delivery_id)
        if record.state == "pending":
            self._record_attempt(delivery_id, via_route, "pending_denied")
            raise PendingDeliveryError(
                f"delivery {delivery_id} awaits a verdict; no bytes served"
            )
        if record.state == "withheld":
            self._record_attempt(delivery_id, via_route, "withheld_denied")
            raise WithheldError(f"delivery {delivery_id} was withheld; no bytes served")
        self._record_attempt(delivery_id, via_route, "served")
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
        with self._lock:
            return self._record_parse(delivery_id, parse_status)

    def _record_parse(self, delivery_id: str, parse_status: ParseStatus) -> Event:
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

    def withhold_for_infrastructure(
        self, delivery_id: str, error_class: str
    ) -> DeliveryRecord:
        """Withhold a pending delivery for an infrastructure reason (CL-19).

        No verdict is recorded and no clean outcome is implied: the
        delivery is withheld, the manifest error class is stored on
        the record, and recipient access raises `WithheldError`.
        """
        with self._lock:
            record = self._delivery(delivery_id)
            if record.state != "pending":
                raise ValueError(
                    f"delivery {delivery_id} already decided ({record.state})"
                )
            record.state = "withheld"
            record.infrastructure_error = error_class
            self._persist_delivery(record)
            return record

    # -- CL-18: uniform enforcement on every access path -------------------

    def _record_attempt(
        self, delivery_id: str, via_route: str | None, outcome: str
    ) -> None:
        record = self._deliveries.get(delivery_id)
        state = record.state if record is not None else None
        self._access_attempts.append(
            {
                "delivery_id": delivery_id,
                "via_route": via_route,
                "outcome": outcome,
                "delivery_state": state,
            }
        )
        self._persist_attempt_row(delivery_id, via_route, outcome, state)

    def serve_via_route(self, route_id: str, delivery_id: str) -> bytes:
        """Serve a decided delivery through any gated route (R-01..R-07).

        The route is validated, then the identical verdict check in
        `recipient_access` runs: a cached link, direct fetch, tool
        output or parse hand-off can never bypass quarantine.
        """
        self._route(route_id)
        return self.recipient_access(delivery_id, via_route=route_id)

    def issue_cached_link(self, delivery_id: str) -> str:
        """Issue an opaque cached-link token for a delivery (R-05).

        Issuing a link grants nothing: redemption re-checks the
        delivery's current verdict, so a link minted while pending
        (or before quarantine) never serves withheld bytes.
        """
        with self._lock:
            self._delivery(delivery_id)
            token = "lnk_" + hashlib.sha256(delivery_id.encode()).hexdigest()[:32]
            self._cached_links[token] = delivery_id
            if self._db is not None:
                self._db.execute(
                    "INSERT OR REPLACE INTO gate_cached_links"
                    " (token, delivery_id) VALUES (?, ?)",
                    (token, delivery_id),
                )
            return token

    def redeem_cached_link(self, token: str) -> bytes:
        """Redeem a cached link through the same gate as a direct fetch."""
        with self._lock:
            delivery_id = self._cached_links.get(token)
            if delivery_id is None:
                raise UnknownDeliveryError(token)
            return self.recipient_access(delivery_id, via_route="R-05")

    def reviewer_access(
        self,
        delivery_id: str,
        *,
        actor_id: str,
        reviewer_ids: set[str] | frozenset[str],
    ) -> bytes:
        """Read a (possibly quarantined) original as an authorized reviewer.

        This is the R-08 evidence path, not a delivery: only actors in
        `reviewer_ids` may use it, recipients never gain bytes through
        it, and the read is audited by the store's access history.
        """
        with self._lock:
            record = self._delivery(delivery_id)
            if actor_id not in reviewer_ids:
                self._record_attempt(delivery_id, "R-08", "reviewer_denied")
                raise ReviewerAccessError(
                    f"{actor_id} is not an authorized reviewer for quarantined evidence"
                )
            self._record_attempt(delivery_id, "R-08", "reviewer_served")
            return self._store.get_original(
                record.artifact_version_id, actor_id=actor_id, purpose="review"
            )

    def access_attempt_report(self) -> dict[str, Any]:
        """Zero-unauthorized-access audit over every recorded attempt.

        ``unauthorized_served`` is computed (CL-53): a recipient serve
        counts as unauthorized when the delivery's state at serve time
        was not ``permitted``. Reviewer serves (R-08) are evidence
        reads, not recipient deliveries, and never count here.
        """
        with self._lock:
            attempts = list(self._access_attempts)
            deliveries = dict(self._deliveries)
        served = [a for a in attempts if a["outcome"] == "served"]
        unauthorized = 0
        for attempt in served:
            state = attempt.get("delivery_state")
            if state is None:
                record = deliveries.get(str(attempt.get("delivery_id")))
                state = record.state if record is not None else None
            if state != "permitted":
                unauthorized += 1
        return {
            "attempts": len(attempts),
            "served": len(served),
            "pending_denied": sum(
                1 for a in attempts if a["outcome"] == "pending_denied"
            ),
            "withheld_denied": sum(
                1 for a in attempts if a["outcome"] == "withheld_denied"
            ),
            "reviewer_served": sum(
                1 for a in attempts if a["outcome"] == "reviewer_served"
            ),
            "reviewer_denied": sum(
                1 for a in attempts if a["outcome"] == "reviewer_denied"
            ),
            "unauthorized_served": unauthorized,
            "by_route": sorted(
                {str(a["via_route"]) for a in attempts if a["via_route"]}
            ),
        }

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

    def get_delivery(self, delivery_id: str) -> DeliveryRecord:
        with self._lock:
            return self._delivery(delivery_id)

    def deliveries(self, run_id: str | None = None) -> list[DeliveryRecord]:
        with self._lock:
            rows = list(self._deliveries.values())
        if run_id is not None:
            rows = [r for r in rows if r.run_id == run_id]
        return sorted(rows, key=lambda r: r.delivery_id)

    def runs(self) -> list[str]:
        with self._lock:
            run_ids = {r.run_id for r in self._deliveries.values()}
            run_ids.update(self._logs.keys())
        return sorted(run_ids)

    def access_attempts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in self._access_attempts]

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
        appended = log.append(event)
        self._persist_event(appended)
        return appended
