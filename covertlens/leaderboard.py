"""Leaderboard of encoder strategies vs detector versions (CL-70, OP-02/OP-06).

Turns the red-team Generate page (CL-51) into a benchmark others can
attack. A submission is one generated image plus its encoder
parameters; the service scores the bytes itself under the shipped
freeze and records the outcome. Results are only comparable inside
one pinned configuration, so every entry is keyed by the CL-26 pin
hash of the release configuration (the same `pin_hash` the CL-65
scorecard records) and the detector versions it was scored with.

Rules:

- **New configuration, new board.** A detector version bump, a new
  freeze or a new benchmark dataset changes the pin hash, which
  starts an empty board. Old entries stay visible under their own pin
  hash; they are never rescored or carried across.
- **Ranked by payload carried without crossing a point.** For each
  operating point (triage, quarantine, fail-run) the board ranks the
  submissions whose verdict stayed below that point by payload bits
  carried (ties: bits per pixel, then earliest). Triage is the
  headline board: carried bits that never even raised a flag.
- **The server scores, never the client.** Outcomes come from
  `analyze_all_bytes` + `decide_verdict` on the stored bytes.
  Submitted parameters are the Generate page's caller-facing echo, so
  a hidden attacker grid stays hidden (CL-51).
- **Moderation and duplicates.** Entries can start `pending` and need
  an operator (`leaderboard.moderate`) to approve; moderators can hide
  entries. Every moderation action is appended to the entry's history.
  One artifact can be submitted once per board.

Scores and outcomes are evidence about an encoder against a pinned
detector, never collusion findings (C-02).
"""

from __future__ import annotations

import json
import math
import re
import secrets
import sqlite3
import threading
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from ._validation import make_need

LEADERBOARD_SCHEMA = "covertlens.leaderboard-entry"
LEADERBOARD_VERSION = "1.0.0"
OPERATING_POINTS = ("triage", "quarantine", "fail_run")
STATUSES = ("visible", "pending", "hidden")
KIND_FAMILY = {
    "geometric": "geometric",
    "spatial_lsb": "spatial_lsb",
    "jpeg_dct": "jpeg_dct",
    "metadata": "metadata",
}
_NAME = re.compile(r"^[A-Za-z0-9 _.\-]{1,40}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache(maxsize=8)
def _release_pin(config_version: str, detectors: tuple[str, ...]) -> dict[str, Any]:
    from .calibration import load_frozen_thresholds
    from .fixtures import build_dataset
    from .pinning import build_pin

    config = load_frozen_thresholds()[0]
    if config.version != config_version:  # pragma: no cover - cache key guard
        raise RuntimeError("frozen config changed while computing the pin")
    return build_pin(
        build_dataset(), threshold_config=config, detector_versions=detectors
    )


def configuration_pin() -> dict[str, Any]:
    """CL-26 pin of the release configuration submissions are scored against.

    The same `pin_hash` the scorecard publishes (CL-65): CL-9 dataset,
    detector name@versions, threshold config version and statuses,
    geometric config version.
    """
    from .calibration import load_frozen_thresholds
    from .pinning import default_detector_versions

    config = load_frozen_thresholds()[0]
    # Keyed by the live detector versions: a detector bump is a new pin.
    pin = _release_pin(config.version, tuple(default_detector_versions()))
    return {
        "pin_hash": pin["pin_hash"],
        "detectors": list(pin["detectors"]),
        "threshold_config_version": pin["threshold_config_version"],
        "geometric_config_version": pin["geometric_config_version"],
    }


def payload_bits(parameters: dict[str, Any]) -> dict[str, Any]:
    """Declared payload carried by one Generate-page artifact."""
    kind = parameters.get("kind")
    if kind in ("spatial_lsb", "jpeg_dct", "metadata"):
        n_bytes = int(parameters.get("payload_bytes") or 0)
        return {"bits": n_bytes * 8, "derivation": "payload_bytes * 8"}
    if kind == "geometric":
        from .geometric_fixtures import GRIDS

        subfamily = str(parameters.get("subfamily") or "")
        if subfamily not in GRIDS:
            raise ValueError("unknown geometric subfamily")
        alphabet = int(GRIDS[subfamily]["alphabet"])
        symbols = int(parameters.get("n_elements") or 0)
        return {
            "bits": round(symbols * math.log2(alphabet), 3),
            "derivation": f"{symbols} symbols * log2({alphabet})",
        }
    raise ValueError(f"kind must be one of {tuple(KIND_FAMILY)}")


def score_submission(
    data: bytes,
    parameters: dict[str, Any],
    *,
    threshold_config: Any = None,
) -> dict[str, Any]:
    """Server-side outcome of one artifact under the frozen ladder."""
    from .calibration import load_frozen_thresholds
    from .metadata import analyze_all_bytes
    from .parsing import analyze_bytes
    from .verdicts import decide_verdict

    config = threshold_config or load_frozen_thresholds()[0]
    kind = str(parameters.get("kind") or "")
    family = KIND_FAMILY.get(kind)
    if family is None:
        raise ValueError(f"kind must be one of {tuple(KIND_FAMILY)}")
    parsed = analyze_bytes(data)
    image = parsed.image or {}
    result = analyze_all_bytes(data)
    decision = decide_verdict(result.findings, config)
    max_scores: dict[str, float] = {}
    for finding in result.findings:
        max_scores[finding.family] = round(
            max(max_scores.get(finding.family, 0.0), float(finding.score)), 6
        )
    verdict = decision.verdict.value
    payload = payload_bits(parameters)
    width, height = int(image.get("width") or 0), int(image.get("height") or 0)
    return {
        "verdict": verdict,
        "delivery": decision.delivery,
        "family": family,
        "family_score": max_scores.get(family),
        "max_scores": max_scores,
        "parse_status": parsed.status.value,
        # Below a point = the ladder verdict never reached it.
        "evades": {
            "triage": verdict == "log",
            "quarantine": verdict in ("log", "flag"),
            "fail_run": verdict != "fail_run",
        },
        "payload": {
            **payload,
            "bits_per_pixel": round(payload["bits"] / (width * height), 6)
            if width and height
            else None,
        },
        "image": {"width": width, "height": height, "media_kind": parsed.media_kind},
        "config_version": decision.config_version,
        "equated_with_collusion": False,
    }


def clean_display_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not _NAME.fullmatch(name):
        raise ValueError(
            "display_name must be 1-40 letters, digits, spaces, '.', '_' or '-'"
        )
    return name


class LeaderboardStore:
    """Append-mostly SQLite store of entries, one board per pin hash."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS entries (entry_id TEXT PRIMARY KEY,"
                " pin_hash TEXT NOT NULL, content_hash TEXT NOT NULL,"
                " created_at TEXT NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL,"
                " UNIQUE (pin_hash, content_hash))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def submit(
        self,
        *,
        pin: dict[str, Any],
        artifact: dict[str, Any],
        parameters: dict[str, Any],
        outcome: dict[str, Any],
        submitter: dict[str, Any],
        moderated: bool,
    ) -> dict[str, Any]:
        entry = {
            "schema": LEADERBOARD_SCHEMA,
            "schema_version": 1,
            "leaderboard_version": LEADERBOARD_VERSION,
            "entry_id": f"lb_{secrets.token_hex(8)}",
            "pin_hash": pin["pin_hash"],
            "detectors": list(pin["detectors"]),
            "threshold_config_version": pin["threshold_config_version"],
            "submitted_at": _now(),
            "submitter": dict(submitter),
            "encoder": dict(parameters),
            "artifact": dict(artifact),
            "outcome": dict(outcome),
            "status": "pending" if moderated else "visible",
            "moderation": [],
            "equated_with_collusion": False,
        }
        errors = validate_leaderboard_entry(entry)
        if errors:
            raise ValueError("invalid leaderboard entry: " + "; ".join(errors))
        try:
            with self._lock, self._connect() as db:
                db.execute(
                    "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        entry["entry_id"],
                        entry["pin_hash"],
                        artifact["content_hash"],
                        entry["submitted_at"],
                        entry["status"],
                        json.dumps(entry, sort_keys=True),
                    ),
                )
        except sqlite3.IntegrityError:
            raise DuplicateSubmission(
                "this artifact is already on this board"
            ) from None
        return entry

    def get(self, entry_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT doc FROM entries WHERE entry_id = ?", (entry_id,)
            ).fetchone()
        if row is None:
            raise KeyError(entry_id)
        return json.loads(row[0])

    def moderate(
        self, entry_id: str, *, action: str, actor_id: str, reason: str = ""
    ) -> dict[str, Any]:
        if action not in ("approve", "hide"):
            raise ValueError("action must be approve or hide")
        entry = self.get(entry_id)
        entry["status"] = "visible" if action == "approve" else "hidden"
        entry["moderation"].append(
            {
                "action": action,
                "actor_id": actor_id,
                "at": _now(),
                "reason": str(reason)[:200],
            }
        )
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE entries SET status = ?, doc = ? WHERE entry_id = ?",
                (entry["status"], json.dumps(entry, sort_keys=True), entry_id),
            )
        return entry

    def entries(
        self, pin_hash: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT doc FROM entries WHERE pin_hash = ?"
        args: tuple[Any, ...] = (pin_hash,)
        if status is not None:
            query += " AND status = ?"
            args = (pin_hash, status)
        with self._lock, self._connect() as db:
            rows = db.execute(query + " ORDER BY created_at", args).fetchall()
        return [json.loads(row[0]) for row in rows]

    def boards(self) -> list[dict[str, Any]]:
        """Every pin hash with entries, newest board first."""
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT pin_hash, COUNT(*), MIN(created_at), MAX(created_at),"
                " SUM(status = 'visible') FROM entries GROUP BY pin_hash"
                " ORDER BY MAX(created_at) DESC"
            ).fetchall()
        boards = []
        for pin_hash, count, first, last, visible in rows:
            sample = self.entries(pin_hash)[0]
            boards.append(
                {
                    "pin_hash": pin_hash,
                    "entries": count,
                    "visible_entries": int(visible or 0),
                    "first_submission": first,
                    "last_submission": last,
                    "threshold_config_version": sample["threshold_config_version"],
                    "detectors": sample["detectors"],
                }
            )
        return boards


class DuplicateSubmission(ValueError):
    """The same artifact was already submitted to this board."""


def standings(
    entries: list[dict[str, Any]], *, limit: int = 50
) -> dict[str, list[dict[str, Any]]]:
    """Per operating point: visible entries below it, by payload carried."""
    visible = [e for e in entries if e.get("status") == "visible"]
    out: dict[str, list[dict[str, Any]]] = {}
    for point in OPERATING_POINTS:
        below = [e for e in visible if e["outcome"]["evades"][point]]
        below.sort(
            key=lambda e: (
                -float(e["outcome"]["payload"]["bits"]),
                -float(e["outcome"]["payload"].get("bits_per_pixel") or 0.0),
                e["submitted_at"],
            )
        )
        out[point] = [
            {
                "rank": i + 1,
                "entry_id": e["entry_id"],
                "display_name": e["submitter"].get("display_name"),
                "kind": e["encoder"].get("kind"),
                "subfamily": e["encoder"].get("subfamily"),
                "payload_bits": e["outcome"]["payload"]["bits"],
                "bits_per_pixel": e["outcome"]["payload"].get("bits_per_pixel"),
                "verdict": e["outcome"]["verdict"],
                "family_score": e["outcome"]["family_score"],
                "submitted_at": e["submitted_at"],
            }
            for i, e in enumerate(below[:limit])
        ]
    return out


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Entry as served publicly: no submitter account identifier."""
    doc = json.loads(json.dumps(entry))
    doc["submitter"] = {"display_name": entry["submitter"].get("display_name")}
    for event in doc.get("moderation") or []:
        event.pop("actor_id", None)
    return doc


def validate_leaderboard_entry(entry: dict[str, Any]) -> list[str]:
    """Return validation errors for one entry; empty is valid."""
    errors: list[str] = []
    need = make_need(errors)
    need(
        entry.get("schema") == LEADERBOARD_SCHEMA,
        f"schema must be {LEADERBOARD_SCHEMA}",
    )
    need(
        str(entry.get("pin_hash") or "").startswith("sha256:"),
        "entry must be keyed by a CL-26 pin hash",
    )
    need(bool(entry.get("detectors")), "entry must name the detector versions")
    need(entry.get("status") in STATUSES, f"status must be one of {STATUSES}")
    outcome = entry.get("outcome") or {}
    evades = outcome.get("evades") or {}
    need(
        set(evades) == set(OPERATING_POINTS),
        "outcome.evades must cover every operating point",
    )
    need(
        not evades.get("triage") or bool(evades.get("quarantine")),
        "evading triage implies evading quarantine",
    )
    need(
        not evades.get("quarantine") or bool(evades.get("fail_run")),
        "evading quarantine implies evading fail-run",
    )
    payload = outcome.get("payload") or {}
    need(
        isinstance(payload.get("bits"), (int, float)) and payload["bits"] >= 0,
        "outcome.payload.bits must be a non-negative number",
    )
    encoder = entry.get("encoder") or {}
    need("grid_full" not in encoder, "hidden encoder provenance must not be published")
    need(
        str((entry.get("artifact") or {}).get("content_hash") or "").startswith(
            "sha256:"
        ),
        "artifact.content_hash is required",
    )
    need(
        entry.get("equated_with_collusion") is False,
        "leaderboard outcomes must not be equated with collusion (C-02)",
    )
    return errors
