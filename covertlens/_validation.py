"""Shared validation and misc internal helpers (CL-63).

One home for the `need()` error-collector closure that used to be
copied into about twenty validator functions, the UTC timestamp
helper that existed in three copies, and the canonical JSON form
shared by the pin and the audit log.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


def need(errors: list[str], cond: bool, msg: str) -> None:
    """Append `msg` to `errors` when `cond` is false."""
    if not cond:
        errors.append(msg)


def make_need(errors: list[str]) -> Callable[[bool, str], None]:
    """Return the `need(cond, msg)` closure bound to `errors`."""

    def _need(cond: bool, msg: str) -> None:
        need(errors, cond, msg)

    return _need


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the single `_now`)."""
    return datetime.now(UTC).isoformat()


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys, `str` fallback for exotic values."""
    return json.dumps(value, sort_keys=True, default=str)


def canonical_hash(value: Any) -> str:
    """`sha256:<hex>` of the canonical JSON form of `value`."""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()
