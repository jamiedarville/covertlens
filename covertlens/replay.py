"""Delivered-versus-withheld replay experiments (CL-21, DT-05).

Each encoded fixture generates a *matched pair* of trials — the same
artifact, delivered in one arm and withheld in the other — so
prevention is measured separately from observed transfer. Trial order
is randomized under a recorded seed and every condition is pinned in
the report (fixture hashes, detector/config versions, per-trial
seeds), so stochastic variation is reproducible rather than hidden.

Two outcomes are collected independently per trial:

- **recovery**: could an independent decoder recover the payload
  from the bytes the recipient actually received?
- **legitimate task outcome**: did the recipient's legitimate task
  succeed (supplied by the caller; it may succeed without the image,
  e.g. over the declared text channel)?

Withheld trials hand the recipient no bytes: their parse status is
`not_observed`, recovery is recorded as `not_observed` (never a
failure of the decoder and never a success), and
`demonstrated_transfer` is always false for them (C-04). Only a
delivered trial with successful independent recovery counts as
demonstrated transfer — and even that is an experiment outcome, not
proof of agent collusion (C-02).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from . import ids
from .fixtures import Fixture

REPLAY_SCHEMA = "covertlens.replay-experiment"
REPLAY_SCHEMA_VERSION = 1
REPLAY_VERSION = "1.0.0"
CONDITIONS = ("delivered", "withheld")


@dataclass(frozen=True)
class ReplayConfig:
    """Pinned experiment conditions; a change creates a new experiment."""

    version: str = REPLAY_VERSION
    seed: int = 20261028
    repetitions: int = 1
    detector_versions: tuple[str, ...] = ()
    verdict_config_version: str | None = None

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        if self.repetitions < 1:
            raise ValueError("repetitions must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "seed": self.seed,
            "repetitions": self.repetitions,
            "detector_versions": list(self.detector_versions),
            "verdict_config_version": self.verdict_config_version,
        }


@dataclass(frozen=True)
class Trial:
    trial_id: str
    fixture_id: str
    pair_id: str
    family: str
    payload_band: str
    condition: str  # delivered | withheld
    repetition: int
    trial_seed: int
    content_hash: str


def build_trials(
    fixtures: Iterable[Fixture], config: ReplayConfig | None = None
) -> list[Trial]:
    """Matched delivered/withheld trials per encoded fixture, seeded order."""
    active = config or ReplayConfig()
    trials: list[Trial] = []
    for fixture in fixtures:
        if fixture.role != "encoded":
            continue
        for repetition in range(active.repetitions):
            for condition in CONDITIONS:
                trial_seed = active.seed + len(trials) * 7919
                trials.append(
                    Trial(
                        trial_id=f"trial-{fixture.fixture_id}-{condition}-{repetition}",
                        fixture_id=fixture.fixture_id,
                        pair_id=fixture.pair_id,
                        family=fixture.family,
                        payload_band=fixture.payload_band,
                        condition=condition,
                        repetition=repetition,
                        trial_seed=trial_seed,
                        content_hash=fixture.content_hash,
                    )
                )
    random.Random(active.seed).shuffle(trials)
    return trials


RecoverFn = Callable[[Fixture], bool]
TaskFn = Callable[[Fixture, bytes | None, int], bool]


def run_replay(
    fixtures: Iterable[Fixture],
    *,
    config: ReplayConfig | None = None,
    recover: RecoverFn | None = None,
    task_outcome: TaskFn | None = None,
) -> dict[str, Any]:
    """Run matched replay trials and return the pinned report.

    `recover` independently decodes a delivered fixture (default: the
    CL-9 `Fixture.verify_payload`). `task_outcome` records the
    legitimate task result for (fixture, received bytes or None,
    trial seed); the default records success exactly when bytes were
    delivered, which callers should replace with their task metric.
    """
    active = config or ReplayConfig()
    rows = list(fixtures)
    by_id = {f.fixture_id: f for f in rows}
    recover_fn: RecoverFn = recover or (lambda f: f.verify_payload())
    task_fn: TaskFn = task_outcome or (lambda f, data, seed: data is not None)
    trials = build_trials(rows, active)

    records: list[dict[str, Any]] = []
    for trial in trials:
        fixture = by_id[trial.fixture_id]
        delivered = trial.condition == "delivered"
        received = fixture.data if delivered else None
        recovered = bool(recover_fn(fixture)) if delivered else None
        records.append(
            {
                "trial_id": trial.trial_id,
                "fixture_id": trial.fixture_id,
                "pair_id": trial.pair_id,
                "family": trial.family,
                "payload_band": trial.payload_band,
                "condition": trial.condition,
                "repetition": trial.repetition,
                "trial_seed": trial.trial_seed,
                "content_hash": trial.content_hash,
                "parse_status": "parsed" if delivered else "not_observed",
                "recovery": (
                    "recovered" if recovered else "not_recovered"
                )
                if delivered
                else "not_observed",
                "legitimate_task_success": bool(
                    task_fn(fixture, received, trial.trial_seed)
                ),
                # Withheld bytes can never be an observed transfer (C-04).
                "demonstrated_transfer": bool(delivered and recovered),
            }
        )

    def arm(condition: str) -> dict[str, Any]:
        subset = [r for r in records if r["condition"] == condition]
        delivered_arm = condition == "delivered"
        return {
            "trials": len(subset),
            "recovered": sum(1 for r in subset if r["recovery"] == "recovered"),
            "recovery_rate": (
                round(
                    sum(1 for r in subset if r["recovery"] == "recovered")
                    / len(subset),
                    6,
                )
                if delivered_arm and subset
                else None
            ),
            "legitimate_task_successes": sum(
                1 for r in subset if r["legitimate_task_success"]
            ),
            "legitimate_task_success_rate": (
                round(
                    sum(1 for r in subset if r["legitimate_task_success"])
                    / len(subset),
                    6,
                )
                if subset
                else None
            ),
            "parse_not_observed": sum(
                1 for r in subset if r["parse_status"] == "not_observed"
            ),
            "demonstrated_transfers": sum(
                1 for r in subset if r["demonstrated_transfer"]
            ),
        }

    return {
        "schema": REPLAY_SCHEMA,
        "schema_version": REPLAY_SCHEMA_VERSION,
        "experiment_version": active.version,
        "config": active.to_dict(),
        "conditions_pinned": {
            "fixture_hashes": {
                f.fixture_id: f.content_hash
                for f in rows
                if f.role == "encoded"
            },
            "conditions": list(CONDITIONS),
            "matched_by": "fixture_id (same artifact in both arms)",
            "randomization": "seeded shuffle of trial order",
        },
        "trials": records,
        "by_condition": {c: arm(c) for c in CONDITIONS},
        "by_payload_band": {
            band: {
                condition: arm_for(records, band, condition)
                for condition in CONDITIONS
            }
            for band in ("low", "medium", "high")
        },
        "equated_with_collusion": False,
    }


def arm_for(
    records: list[dict[str, Any]], band: str, condition: str
) -> dict[str, Any]:
    subset = [
        r for r in records
        if r["payload_band"] == band and r["condition"] == condition
    ]
    return {
        "trials": len(subset),
        "recovered": sum(1 for r in subset if r["recovery"] == "recovered"),
        "demonstrated_transfers": sum(
            1 for r in subset if r["demonstrated_transfer"]
        ),
        "legitimate_task_successes": sum(
            1 for r in subset if r["legitimate_task_success"]
        ),
    }


def validate_replay(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one replay report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == REPLAY_SCHEMA, f"schema must be {REPLAY_SCHEMA}")
    need(
        report.get("schema_version") == REPLAY_SCHEMA_VERSION,
        f"schema_version must be {REPLAY_SCHEMA_VERSION}",
    )
    need(report.get("equated_with_collusion") is False, "replay never equates outcomes with collusion (C-02)")
    trials = report.get("trials") or []
    for i, trial in enumerate(trials):
        if trial.get("condition") == "withheld":
            need(
                trial.get("parse_status") == "not_observed",
                f"trials[{i}] withheld parse must be not_observed (C-04)",
            )
            need(
                trial.get("demonstrated_transfer") is False,
                f"trials[{i}] withheld trials never demonstrate transfer (C-04)",
            )
            need(
                trial.get("recovery") == "not_observed",
                f"trials[{i}] withheld recovery must be not_observed",
            )
        if trial.get("demonstrated_transfer"):
            need(
                trial.get("condition") == "delivered"
                and trial.get("recovery") == "recovered",
                f"trials[{i}] demonstrated transfer requires delivered + recovered",
            )
        need(
            ids.is_content_hash(trial.get("content_hash")),
            f"trials[{i}].content_hash must pin the exact artifact bytes",
        )
    by_condition = report.get("by_condition") or {}
    for condition in CONDITIONS:
        need(condition in by_condition, f"by_condition.{condition} is required")
    return errors
