"""Gate integrity: score/verdict caching and invalidation (CL-20, ENF-05).

Two caches with different keys, because they have different safety
rules:

- **Image scores** depend only on the exact bytes and the detector:
  key = (content_hash, detector name, detector version, detector
  config version). Changed bytes produce a different hash and can
  never reuse a score (C-05); a detector or config bump likewise
  misses. Scores carry no run context, so they are safe to reuse when
  only the context changes.
- **Verdicts** additionally depend on the threshold configuration
  and the run context: the verdict key includes the threshold-config
  version and a fingerprint of the caller-supplied context
  (identities, episode, declared exceptions). A context change
  therefore recomputes the verdict — while the underlying image
  score, keyed without context, is reused.

Both caches are thread-safe and count hits/misses/stores so tests and
audits can prove which path was taken. Nothing here serves bytes:
unauthorized-access properties come from the CL-18 gate, whose
attempt report the integrity tests assert under races, retries and
alternate references.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .parsing import AnalysisResult, Finding
from .verdicts import ThresholdConfig, VerdictDecision, decide_verdict

CACHE_VERSION = "1.0.0"


def context_fingerprint(context: dict[str, Any] | None) -> str:
    """Stable fingerprint of run-context inputs to a verdict."""
    canonical = json.dumps(context or {}, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def score_key(result: AnalysisResult, finding: Finding) -> tuple[str, str, str, str]:
    """Cache key for an image score: bytes + detector identity only."""
    config_version = str(
        (finding.evidence or {}).get("detector_config_version")
        or (finding.coverage or {}).get("config_version")
        or ""
    )
    return (
        result.content_hash,
        finding.detector_name,
        finding.detector_version,
        config_version,
    )


def verdict_key(
    findings: Iterable[Finding],
    config: ThresholdConfig,
    context: dict[str, Any] | None,
) -> tuple[Any, ...]:
    """Cache key for a verdict: scores + thresholds + run context."""
    rows = tuple(
        sorted(
            (f.family, f.detector_name, f.detector_version, round(float(f.score), 6))
            for f in findings
        )
    )
    return (rows, config.version, context_fingerprint(context))


@dataclass
class _Stats:
    hits: int = 0
    misses: int = 0
    stores: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "stores": self.stores}


@dataclass
class AnalysisCache:
    """Thread-safe score/verdict cache with ENF-05 invalidation keys."""

    version: str = CACHE_VERSION
    _scores: dict[tuple[str, str, str, str], Finding] = field(default_factory=dict)
    _verdicts: dict[tuple[Any, ...], VerdictDecision] = field(default_factory=dict)
    _score_stats: _Stats = field(default_factory=_Stats)
    _verdict_stats: _Stats = field(default_factory=_Stats)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- image scores ---------------------------------------------------

    def get_or_score(
        self,
        result: AnalysisResult,
        detector: Callable[[AnalysisResult], Finding | None],
        *,
        detector_name: str,
        detector_version: str,
        config_version: str = "",
    ) -> Finding | None:
        """Return the cached finding for these bytes/detector, or compute it.

        The detector callable is only invoked on a cache miss, so a
        hit is observable (and countable) as reuse of the image score.
        """
        cached = self.get_score(
            result,
            detector_name=detector_name,
            detector_version=detector_version,
            config_version=config_version,
        )
        if cached is not None:
            return cached
        computed = detector(result)
        if computed is None:
            return None
        if (computed.detector_name, computed.detector_version) != (
            detector_name,
            detector_version,
        ):
            raise ValueError("detector returned a finding under another identity")
        self.put_score(result, computed)
        return computed

    def put_score(self, result: AnalysisResult, finding: Finding) -> None:
        with self._lock:
            self._scores[score_key(result, finding)] = finding
            self._score_stats.stores += 1

    def get_score(
        self,
        result: AnalysisResult,
        *,
        detector_name: str,
        detector_version: str,
        config_version: str = "",
    ) -> Finding | None:
        key = (result.content_hash, detector_name, detector_version, config_version)
        with self._lock:
            cached = self._scores.get(key)
            if cached is None:
                self._score_stats.misses += 1
            else:
                self._score_stats.hits += 1
            return cached

    # -- verdicts ---------------------------------------------------------

    def get_or_decide(
        self,
        findings: Iterable[Finding],
        config: ThresholdConfig | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> VerdictDecision:
        """Return the cached verdict, recomputing on any key change.

        A run-context change changes the fingerprint, so the verdict
        is recomputed even though the findings (image scores) are the
        identical reused objects.
        """
        rows = list(findings)
        from .verdicts import DEFAULT_CONFIG

        active = config or DEFAULT_CONFIG
        key = verdict_key(rows, active, context)
        with self._lock:
            cached = self._verdicts.get(key)
            if cached is not None:
                self._verdict_stats.hits += 1
                return cached
            self._verdict_stats.misses += 1
        decision = decide_verdict(rows, active)
        with self._lock:
            self._verdicts[key] = decision
            self._verdict_stats.stores += 1
        return decision

    # -- reporting ----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cache_version": self.version,
                "scores": self._score_stats.to_dict(),
                "verdicts": self._verdict_stats.to_dict(),
                "score_entries": len(self._scores),
                "verdict_entries": len(self._verdicts),
            }

    def clear(self) -> None:
        with self._lock:
            self._scores.clear()
            self._verdicts.clear()
