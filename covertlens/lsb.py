"""LSB spatial detector and threshold-free benchmark (CL-14, DET-03).

The detector scores PNG sample LSBs on the exact original bytes parsed
by CL-13 (`covertlens.parsing`): no resize, recompression or pixel
reconstruction happens here. It implements the classic pairs-of-values
(PoV) chi-square statistic for LSB replacement. Embedding random payload
bits in sample LSBs equalises each value pair ``(2k, 2k + 1)``; clean
covers keep pair members unequal at a rate set by the cover itself.
The score is ``degrees_of_freedom / chi_square`` clipped to [0, 1]:
near 1 when pairs are as equal as random LSBs predict, lower when the
cover's natural imbalance survives. The score is evidence for triage,
never proof of collusion (C-02), and no threshold is frozen here
(CL-27 freezes triage/enforcement points separately, C-06).

Benchmarking is threshold-free: a sweep over score thresholds reports
precision/recall with Wilson score intervals at every point, plus
ROC-AUC and average precision (PR summary) with stratified bootstrap
confidence intervals. Performance is broken down by the CL-9 payload
band (`none` / `low` / `medium` / `high`) so a strong high-band result
never masquerades as a low-band one.

CL-61 adds a second detector in this module, `lsb-sample-pairs`
(sample-pair analysis over adjacent-pair LSB agreement, gated where
adjacent-pair correlation is absent), benchmarked against this PoV
detector on +/-1 matching fixtures by `benchmark_lsb_pairs`. Both
detectors stay individually visible; nothing here refreezes the
CL-27/CL-54 thresholds.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from ._stats import (
    bootstrap_interval,
    roc_auc,
    score_summary,
    wilson,
)
from ._validation import make_need
from .acceleration import sample_counts, spa_pair_counts
from .fixtures import Fixture
from .parsing import (
    AnalysisResult,
    AnalysisStatus,
    Finding,
    ParserLimits,
    analyze_bytes,
    analyze_version,
)
from .store import ArtifactStore

FAMILY = "spatial_lsb"
LSB_DETECTOR_NAME = "lsb-pov-chisquare"
LSB_DETECTOR_VERSION = "1.0.0"
CONFIG_VERSION = "1.0.0"
BENCHMARK_SCHEMA = "covertlens.lsb-benchmark"
BENCHMARK_SCHEMA_VERSION = 1
BENCHMARK_VERSION = "1.0.0"

PAYLOAD_BANDS = ("none", "low", "medium", "high")

_LIMITATIONS = (
    "global pairs-of-values chi-square over sample LSBs; LSB-matching "
    "(+/-1) and content-adaptive embedding may evade it",
    "calibrated only on procedural synthetic covers; natural-image covers are untested",
    "score is evidence, not demonstrated collusion (C-02); thresholds "
    "unfrozen until CL-27",
)


@dataclass(frozen=True)
class LsbConfig:
    """Versioned detector configuration; a change bumps ``version``."""

    version: str = CONFIG_VERSION
    # PoV pairs whose total count is below this are too sparse for the
    # chi-square approximation and are excluded (counted in coverage).
    pair_min_count: int = 4

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        if self.pair_min_count < 1:
            raise ValueError("pair_min_count must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "pair_min_count": self.pair_min_count}


DEFAULT_CONFIG = LsbConfig()


def _pov_statistics(
    samples: bytes, config: LsbConfig
) -> tuple[float, dict[str, Any], int]:
    """Return (score, evidence, pairs_used) for raw sample bytes."""
    counts = sample_counts(samples)
    total = len(samples)
    chi_square = 0.0
    pairs_used = 0
    imbalance = 0
    for k in range(128):
        pair_total = counts[2 * k] + counts[2 * k + 1]
        imbalance += abs(counts[2 * k] - counts[2 * k + 1])
        if pair_total >= config.pair_min_count:
            pairs_used += 1
            expected = pair_total / 2.0
            chi_square += (
                (counts[2 * k] - expected) ** 2 + (counts[2 * k + 1] - expected) ** 2
            ) / expected
    degrees = pairs_used - 1 if pairs_used else 0
    if pairs_used < 2 or chi_square <= 0:
        score = 1.0 if pairs_used >= 2 and total and chi_square <= 0 else 0.0
    else:
        score = min(1.0, degrees / chi_square)
    evidence = {
        "statistic": "pairs_of_values_chi_square",
        "chi_square": round(chi_square, 6),
        "degrees_of_freedom": degrees,
        "chi_square_per_df": (round(chi_square / degrees, 6) if degrees else 0.0),
        "pairs_used": pairs_used,
        "lsb_one_fraction": (round(sum(counts[1::2]) / total, 6) if total else 0.0),
        "pov_imbalance": round(imbalance / total, 6) if total else 0.0,
        "detector_config_version": config.version,
    }
    return score, evidence, pairs_used


def detect_lsb(
    result: AnalysisResult, config: LsbConfig | None = None
) -> Finding | None:
    """Score one CL-13 result; ``None`` when LSB is not applicable.

    Applicable means: parsed PNG with sample bytes present. JPEGs,
    failed parses and pixel-less results get no LSB finding — a missing
    finding is not a clean score (fail-closed error behaviour, C-02).
    """
    active = config or DEFAULT_CONFIG
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind != "png" or result.pixels is None:
        return None
    samples = result.pixels
    score, evidence, pairs_used = _pov_statistics(samples, active)
    image = result.image or {}
    channels = int(image.get("channels") or 1)
    width = int(image.get("width") or 0)
    height = int(image.get("height") or 0)
    pixels_examined = (
        width * height if width and height else len(samples) // max(channels, 1)
    )
    coverage = {
        "applicable": True,
        "media_kind": "png",
        "samples_examined": len(samples),
        "pixels_examined": pixels_examined,
        "channels": channels,
        "pairs_total": 128,
        "pairs_used": pairs_used,
        "rows_parsed": int((result.coverage or {}).get("rows_parsed") or height),
        "config_version": active.version,
    }
    limitations = list(_LIMITATIONS)
    if pairs_used < 2:
        limitations.append(
            "insufficient pairs-of-values coverage; score is not reliable"
        )
    return Finding(
        family=FAMILY,
        detector_name=LSB_DETECTOR_NAME,
        detector_version=LSB_DETECTOR_VERSION,
        score=score,
        coverage=coverage,
        evidence=evidence,
        limitations=tuple(limitations),
    )


def analyze_lsb_bytes(
    data: bytes,
    *,
    limits: ParserLimits | None = None,
    config: LsbConfig | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
) -> AnalysisResult:
    """Parse exact bytes (CL-13) and attach the LSB finding when applicable."""
    result = analyze_bytes(
        data,
        limits=limits,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
    )
    finding = detect_lsb(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


def benchmark_lsb(
    fixtures: Iterable[Fixture],
    *,
    config: LsbConfig | None = None,
    thresholds: Iterable[float] | None = None,
    bootstrap_replicates: int = 1000,
    bootstrap_seed: int = 20261028,
) -> dict[str, Any]:
    """Threshold-free LSB benchmark over labelled CL-9 fixtures.

    Positives are ``encoded`` fixtures; ``clean`` and ``negative``
    fixtures are negatives. Fixtures outside the `spatial_lsb` family
    are not applicable and are only counted under ``skipped``. Ground
    truth comes from the caller's fixtures, so held-out labels must
    reach this function through the scorer path (CL-10, C-07).
    """
    active = config or DEFAULT_CONFIG
    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be >= 0")
    rows: list[dict[str, Any]] = []
    skipped = 0
    for fixture in fixtures:
        if fixture.family != FAMILY:
            skipped += 1
            continue
        result = analyze_lsb_bytes(fixture.data, config=active)
        finding = result.findings[0] if result.findings else None
        rows.append(
            {
                "fixture_id": fixture.fixture_id,
                "role": fixture.role,
                "label": 1 if fixture.role == "encoded" else 0,
                "payload_band": fixture.payload_band,
                "payload_bits": fixture.payload_bits,
                "bits_per_pixel": round(fixture.bits_per_pixel, 6),
                "applicable": finding is not None,
                "score": round(finding.score, 6) if finding else None,
            }
        )
    scored = [r for r in rows if r["applicable"] and r["score"] is not None]
    positive = [float(r["score"]) for r in scored if r["label"] == 1]
    negative = [float(r["score"]) for r in scored if r["label"] == 0]

    if thresholds is None:
        sweep_thresholds = sorted({0.0, 1.0} | {float(r["score"]) for r in scored})
    else:
        sweep_thresholds = sorted({float(t) for t in thresholds})
        for value in sweep_thresholds:
            if not 0.0 <= value <= 1.0:
                raise ValueError("thresholds must lie in [0, 1]")

    sweep: list[dict[str, Any]] = []
    for threshold in sweep_thresholds:
        tp = sum(
            1 for r in scored if r["label"] == 1 and float(r["score"]) >= threshold
        )
        fp = sum(
            1 for r in scored if r["label"] == 0 and float(r["score"]) >= threshold
        )
        tn = sum(1 for r in scored if r["label"] == 0 and float(r["score"]) < threshold)
        fn = sum(1 for r in scored if r["label"] == 1 and float(r["score"]) < threshold)
        sweep.append(
            {
                "threshold": round(threshold, 6),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": wilson(tp, tp + fp),
                "recall": wilson(tp, tp + fn),
                "false_positive_rate": wilson(fp, fp + tn),
            }
        )

    by_band: dict[str, Any] = {}
    for band in PAYLOAD_BANDS:
        band_rows = [r for r in scored if r["payload_band"] == band]
        band_positive = [float(r["score"]) for r in band_rows if r["label"] == 1]
        band_negative = [float(r["score"]) for r in band_rows if r["label"] == 0]
        by_band[band] = {
            "sweep": [
                {
                    "threshold": round(t, 6),
                    "recall": wilson(
                        sum(
                            r["label"] == 1 and float(r["score"]) >= t
                            for r in band_rows
                        ),
                        len(band_positive),
                    ),
                    "false_positive_rate": wilson(
                        sum(score >= t for score in negative), len(negative)
                    ),
                }
                for t in sweep_thresholds
            ],
            "fixture_count": len(band_rows),
            "positive_count": len(band_positive),
            "negative_count": len(band_negative),
            "scores": score_summary([float(r["score"]) for r in band_rows]),
            # Each encoded band is ranked against every negative, so a
            # band cannot borrow strength from easier bands.
            "roc_auc_vs_negatives": (
                roc_auc(band_positive, negative) if band_positive else None
            ),
        }

    return {
        "schema": BENCHMARK_SCHEMA,
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "detector": {
            "family": FAMILY,
            "name": LSB_DETECTOR_NAME,
            "version": LSB_DETECTOR_VERSION,
            "config": active.to_dict(),
        },
        "thresholds_status": "unfrozen_placeholder",
        "fixture_count": len(rows),
        "scored_count": len(scored),
        "skipped_non_lsb": skipped,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "rows": rows,
        "by_payload_band": by_band,
        "roc_auc": bootstrap_interval(
            positive,
            negative,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
            metric="roc_auc",
        ),
        "pr_auc": bootstrap_interval(
            positive,
            negative,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
            metric="average_precision",
        ),
        "sweep": sweep,
        "limitations": list(_LIMITATIONS)
        + [
            "benchmark fixtures are the CL-9 procedural suite; small "
            "bands give wide Wilson intervals, and bootstrap intervals "
            "are conditional on the observed sample (degenerate under "
            "perfect separation)"
        ],
    }


def validate_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one benchmark report; empty is valid."""
    errors: list[str] = []

    need = make_need(errors)

    need(report.get("schema") == BENCHMARK_SCHEMA, f"schema must be {BENCHMARK_SCHEMA}")
    need(
        report.get("schema_version") == BENCHMARK_SCHEMA_VERSION,
        f"schema_version must be {BENCHMARK_SCHEMA_VERSION}",
    )
    need(bool(report.get("benchmark_version")), "benchmark_version is required")
    detector = report.get("detector") or {}
    need(detector.get("family") == FAMILY, f"detector.family must be {FAMILY}")
    need(detector.get("name") == LSB_DETECTOR_NAME, "detector.name is required")
    need(
        detector.get("version") == LSB_DETECTOR_VERSION, "detector.version is required"
    )
    need(
        (detector.get("config") or {}).get("version") == CONFIG_VERSION,
        "detector.config.version is required",
    )
    need(
        report.get("thresholds_status") == "unfrozen_placeholder",
        "thresholds_status must stay unfrozen_placeholder until CL-27",
    )
    for band in PAYLOAD_BANDS:
        need(
            band in (report.get("by_payload_band") or {}),
            f"by_payload_band.{band} is required",
        )
    for key in ("roc_auc", "pr_auc"):
        block = report.get(key) or {}
        estimate = block.get("estimate")
        if estimate is not None:
            need(0.0 <= float(estimate) <= 1.0, f"{key}.estimate must lie in [0, 1]")
            need(
                float(block.get("ci_low", -1))
                <= float(estimate)
                <= float(block.get("ci_high", 2)),
                f"{key} interval must bracket its estimate",
            )
    for i, point in enumerate(report.get("sweep") or []):
        for name in ("precision", "recall"):
            block = point.get(name) or {}
            estimate = block.get("estimate")
            if estimate is not None:
                need(
                    0.0 <= float(estimate) <= 1.0,
                    f"sweep[{i}].{name} must lie in [0, 1]",
                )
                need(
                    float(block.get("ci_low", -1))
                    <= float(estimate)
                    <= float(block.get("ci_high", 2)),
                    f"sweep[{i}].{name} interval must bracket its estimate",
                )
        need(
            point.get("tp", -1) + point.get("fn", -1) == report.get("positive_count"),
            f"sweep[{i}] tp+fn must equal positive_count",
        )
        need(
            point.get("fp", -1) + point.get("tn", -1) == report.get("negative_count"),
            f"sweep[{i}] fp+tn must equal negative_count",
        )
    return errors


def analyze_lsb_version(
    store: ArtifactStore,
    artifact_version_id: str,
    *,
    actor_id: str,
    limits: ParserLimits | None = None,
    config: LsbConfig | None = None,
) -> AnalysisResult:
    """Score one stored original via its audited, hash-checked read."""
    result = analyze_version(
        store, artifact_version_id, actor_id=actor_id, limits=limits
    )
    finding = detect_lsb(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


# ------------------------------------------------------- CL-61 SPA ---

SPA_DETECTOR_NAME = "lsb-sample-pairs"
SPA_DETECTOR_VERSION = "1.0.0"
SPA_CONFIG_VERSION = "1.1.0"
SPA_BENCHMARK_SCHEMA = "covertlens.lsb-pairs-benchmark"
SPA_BENCHMARK_VERSION = "1.0.0"

_SPA_LIMITATIONS = (
    "sample-pair statistic over adjacent-pair LSB agreement; it "
    "requires spatially correlated (smooth) covers and is gated to 0 "
    "as unreliable where adjacent-pair correlation is absent",
    "calibrated only on procedural smooth-field covers (CL-61); "
    "natural-image covers are untested",
    "score is evidence, not demonstrated collusion (C-02); thresholds "
    "unfrozen (CL-61 does not refreeze the CL-27/CL-54 points)",
)


@dataclass(frozen=True)
class SpaConfig:
    """Versioned sample-pair detector configuration (CL-61)."""

    version: str = SPA_CONFIG_VERSION
    # Minimum non-overlapping adjacent pairs for a reliable statistic.
    min_pairs: int = 256
    # Minimum fraction of pairs with |u - v| <= pair_max_diff for the
    # cover to count as spatially correlated enough for pair analysis.
    smooth_min_fraction: float = 0.5
    pair_max_diff: int = 1
    # The pair-LSB randomness is scaled by this before it becomes the
    # score, so the unfrozen detector can at most reach triage-level
    # evidence under the frozen family points: its maximum score
    # stays below the frozen spatial quarantine point, so it can never
    # by itself cause withholding before a dedicated freeze calibrates
    # points for it. Config 1.1.0 (CL-68) lowers the scale from 0.25
    # because the frozen-1.3.0 quarantine point fell below 0.25; a
    # test pins the cap under the shipped quarantine point.
    score_scale: float = 0.23

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        if self.min_pairs < 1:
            raise ValueError("min_pairs must be >= 1")
        if not 0.0 <= self.smooth_min_fraction <= 1.0:
            raise ValueError("smooth_min_fraction must lie in [0, 1]")
        if self.pair_max_diff < 0:
            raise ValueError("pair_max_diff must be >= 0")
        if not 0.0 < self.score_scale <= 1.0:
            raise ValueError("score_scale must lie in (0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "min_pairs": self.min_pairs,
            "smooth_min_fraction": self.smooth_min_fraction,
            "pair_max_diff": self.pair_max_diff,
            "score_scale": self.score_scale,
        }


SPA_DEFAULT_CONFIG = SpaConfig()


def _spa_statistics(
    samples: bytes, width: int, height: int, channels: int, config: SpaConfig
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    """Return (score, evidence, counts) for adjacent sample pairs.

    Pairs are non-overlapping horizontally adjacent same-channel
    samples (the sample-pair layout of Dumitrescu-style SPA).
    Embedding (+/-1 matching or replacement) randomises sample LSBs
    independently, driving the pair LSB agreement rate toward 0.5;
    the score is the pair-LSB randomness ``1 - 2*|agreement - 0.5|``
    where pair analysis is reliable.
    """
    fast = spa_pair_counts(samples, width, height, channels, config.pair_max_diff)
    pairs = 0
    agree = 0
    smooth = 0
    horizontal = 0
    if fast is not None:
        # Exact optional path (COVERTLENS_FAST_PATH=numpy); identical counts.
        pairs, agree, smooth = fast
        horizontal = pairs
    for y in range(height if fast is None else 0):
        for c in range(channels):
            base = (y * width) * channels + c
            prev_u = prev_v = 0
            for x in range(width):
                value = samples[base + x * channels]
                if x % 2 == 0:
                    prev_u = value
                else:
                    prev_v = value
                    pairs += 1
                    horizontal += 1
                    if (prev_u & 1) == (prev_v & 1):
                        agree += 1
                    if abs(prev_u - prev_v) <= config.pair_max_diff:
                        smooth += 1
    agreement = agree / pairs if pairs else 0.0
    smooth_fraction = smooth / pairs if pairs else 0.0
    reliable = pairs >= config.min_pairs and smooth_fraction >= (
        config.smooth_min_fraction
    )
    randomness = min(1.0, max(0.0, 1.0 - 2.0 * abs(agreement - 0.5)))
    score = randomness * config.score_scale if reliable else 0.0
    evidence = {
        "statistic": "sample_pair_lsb_agreement_randomness",
        "pair_lsb_agreement": round(agreement, 6),
        "pair_lsb_randomness": round(randomness, 6),
        "pair_smooth_fraction": round(smooth_fraction, 6),
        "pairs_examined": pairs,
        "reliable": reliable,
        "detector_config_version": config.version,
    }
    counts = {
        "pairs_examined": pairs,
        "pairs_horizontal": horizontal,
    }
    return round(score, 6), evidence, counts


def detect_lsb_pairs(
    result: AnalysisResult, config: SpaConfig | None = None
) -> Finding | None:
    """Score one CL-13 result with sample-pair analysis (CL-61).

    A second, individually visible `spatial_lsb` detector alongside
    `lsb-pov-chisquare`: applicable means a parsed PNG with sample
    bytes and known geometry. Where adjacent-pair correlation is
    absent the statistic cannot speak, so the score is gated to 0
    with the limitation recorded (never read as a clean verdict, C-02).
    """
    active = config or SPA_DEFAULT_CONFIG
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind != "png" or result.pixels is None:
        return None
    image = result.image or {}
    width = int(image.get("width") or 0)
    height = int(image.get("height") or 0)
    channels = int(image.get("channels") or 1)
    if width < 2 or height < 2:
        return None
    samples = result.pixels
    if len(samples) < width * height * channels:
        return None
    score, evidence, counts = _spa_statistics(samples, width, height, channels, active)
    coverage = {
        "applicable": True,
        "media_kind": "png",
        "samples_examined": len(samples),
        "pixels_examined": width * height,
        "channels": channels,
        "pairs_examined": counts["pairs_examined"],
        "pairs_horizontal": counts["pairs_horizontal"],
        "config_version": active.version,
    }
    limitations = list(_SPA_LIMITATIONS)
    if not evidence["reliable"]:
        limitations.append(
            "insufficient adjacent-pair correlation; sample-pair score is not reliable"
        )
    return Finding(
        family=FAMILY,
        detector_name=SPA_DETECTOR_NAME,
        detector_version=SPA_DETECTOR_VERSION,
        score=score,
        coverage=coverage,
        evidence=evidence,
        limitations=tuple(limitations),
    )


def analyze_lsb_pairs_bytes(
    data: bytes,
    *,
    limits: ParserLimits | None = None,
    config: SpaConfig | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
) -> AnalysisResult:
    """Parse exact bytes (CL-13) and attach the sample-pair finding."""
    result = analyze_bytes(
        data,
        limits=limits,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
    )
    finding = detect_lsb_pairs(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


def analyze_lsb_pairs_version(
    store: ArtifactStore,
    artifact_version_id: str,
    *,
    actor_id: str,
    limits: ParserLimits | None = None,
    config: SpaConfig | None = None,
) -> AnalysisResult:
    """Score one stored original via its audited, hash-checked read."""
    result = analyze_version(
        store, artifact_version_id, actor_id=actor_id, limits=limits
    )
    finding = detect_lsb_pairs(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


def benchmark_lsb_pairs(
    fixtures: Iterable[Fixture],
    *,
    config: SpaConfig | None = None,
    pov_config: LsbConfig | None = None,
    bootstrap_replicates: int = 1000,
    bootstrap_seed: int = 20261101,
) -> dict[str, Any]:
    """Compare sample-pair vs PoV scores on +/-1 fixtures (CL-61).

    Both detectors stay individually visible: every row carries both
    scores, and each detector gets its own bootstrap ROC-AUC. The
    acceptance claim is `pairs_beats_pov` on this suite only.
    """
    active = config or SPA_DEFAULT_CONFIG
    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be >= 0")
    rows: list[dict[str, Any]] = []
    skipped = 0
    for fixture in fixtures:
        if fixture.family != FAMILY:
            skipped += 1
            continue
        result = analyze_bytes(fixture.data)
        pairs_finding = detect_lsb_pairs(result, active)
        pov_finding = detect_lsb(result, pov_config)
        rows.append(
            {
                "fixture_id": fixture.fixture_id,
                "role": fixture.role,
                "label": 1 if fixture.role == "encoded" else 0,
                "payload_band": fixture.payload_band,
                "payload_bits": fixture.payload_bits,
                "bits_per_pixel": round(fixture.bits_per_pixel, 6),
                "applicable": pairs_finding is not None,
                "pairs_score": (
                    round(pairs_finding.score, 6) if pairs_finding else None
                ),
                "pov_score": round(pov_finding.score, 6) if pov_finding else None,
            }
        )
    scored = [r for r in rows if r["pairs_score"] is not None]
    pairs_pos = [float(r["pairs_score"]) for r in scored if r["label"] == 1]
    pairs_neg = [float(r["pairs_score"]) for r in scored if r["label"] == 0]
    pov_pos = [
        float(r["pov_score"])
        for r in scored
        if r["label"] == 1 and r["pov_score"] is not None
    ]
    pov_neg = [
        float(r["pov_score"])
        for r in scored
        if r["label"] == 0 and r["pov_score"] is not None
    ]
    pairs_auc = bootstrap_interval(
        pairs_pos,
        pairs_neg,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
        metric="roc_auc",
    )
    pov_auc = bootstrap_interval(
        pov_pos,
        pov_neg,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
        metric="roc_auc",
    )
    by_band: dict[str, Any] = {}
    for band in PAYLOAD_BANDS:
        band_rows = [r for r in scored if r["payload_band"] == band]
        band_pos = [float(r["pairs_score"]) for r in band_rows if r["label"] == 1]
        by_band[band] = {
            "fixture_count": len(band_rows),
            "positive_count": len(band_pos),
            "negative_count": len(band_rows) - len(band_pos),
            "scores": score_summary([float(r["pairs_score"]) for r in band_rows]),
            "roc_auc_vs_negatives": (
                roc_auc(band_pos, pairs_neg) if band_pos else None
            ),
        }
    return {
        "schema": SPA_BENCHMARK_SCHEMA,
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": SPA_BENCHMARK_VERSION,
        "detector": {
            "family": FAMILY,
            "name": SPA_DETECTOR_NAME,
            "version": SPA_DETECTOR_VERSION,
            "config": active.to_dict(),
        },
        "comparator": {
            "family": FAMILY,
            "name": LSB_DETECTOR_NAME,
            "version": LSB_DETECTOR_VERSION,
        },
        "thresholds_status": "unfrozen_placeholder",
        "fixture_count": len(rows),
        "scored_count": len(scored),
        "skipped_non_lsb": skipped,
        "positive_count": len(pairs_pos),
        "negative_count": len(pairs_neg),
        "rows": rows,
        "by_payload_band": by_band,
        "pairs_roc_auc": pairs_auc,
        "pov_roc_auc": pov_auc,
        "pairs_beats_pov": bool(
            pairs_auc.get("estimate") is not None
            and pov_auc.get("estimate") is not None
            and float(pairs_auc["estimate"]) > float(pov_auc["estimate"])
        ),
        "limitations": list(_SPA_LIMITATIONS)
        + [
            "benchmark fixtures are the CL-61 smooth-field +/-1 suite; "
            "bootstrap intervals are conditional on the observed sample"
        ],
    }


def validate_lsb_pairs_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one CL-61 pairs benchmark; empty is valid."""
    errors: list[str] = []

    need = make_need(errors)

    need(
        report.get("schema") == SPA_BENCHMARK_SCHEMA,
        f"schema must be {SPA_BENCHMARK_SCHEMA}",
    )
    need(
        report.get("schema_version") == BENCHMARK_SCHEMA_VERSION,
        f"schema_version must be {BENCHMARK_SCHEMA_VERSION}",
    )
    need(bool(report.get("benchmark_version")), "benchmark_version is required")
    detector = report.get("detector") or {}
    need(detector.get("family") == FAMILY, f"detector.family must be {FAMILY}")
    need(detector.get("name") == SPA_DETECTOR_NAME, "detector.name is required")
    need(
        detector.get("version") == SPA_DETECTOR_VERSION,
        "detector.version is required",
    )
    need(
        (detector.get("config") or {}).get("version") == SPA_CONFIG_VERSION,
        "detector.config.version is required",
    )
    comparator = report.get("comparator") or {}
    need(
        comparator.get("name") == LSB_DETECTOR_NAME,
        "comparator must stay individually visible (lsb-pov-chisquare)",
    )
    need(
        report.get("thresholds_status") == "unfrozen_placeholder",
        "thresholds_status must stay unfrozen_placeholder (CL-61 refreezes nothing)",
    )
    for band in PAYLOAD_BANDS:
        need(
            band in (report.get("by_payload_band") or {}),
            f"by_payload_band.{band} is required",
        )
    for key in ("pairs_roc_auc", "pov_roc_auc"):
        block = report.get(key) or {}
        estimate = block.get("estimate")
        if estimate is not None:
            need(0.0 <= float(estimate) <= 1.0, f"{key}.estimate must lie in [0, 1]")
            need(
                float(block.get("ci_low", -1))
                <= float(estimate)
                <= float(block.get("ci_high", 2)),
                f"{key} interval must bracket its estimate",
            )
    return errors
