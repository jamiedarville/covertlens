"""JPEG DCT detector and paired benchmark (CL-15, DET-04).

The detector scores the quantized DCT coefficients that CL-13 extracts
from the exact original JPEG bytes: no IDCT, no pixel reconstruction
and no recompression ever happens here. It applies the pairs-of-values
chi-square for coefficient-LSB embedding (the JSteg family) to AC
coefficient magnitudes. The CL-9 embedder writes payload bits into the
LSB of magnitudes >= 2 — a carrier set embedding cannot shrink — so
encoded images drive each magnitude pair ``(2k, 2k + 1)`` toward equal
counts while clean JPEGs keep the decaying imbalance of natural
quantized spectra. The score is ``degrees_of_freedom / chi_square``
clipped to [0, 1], as in CL-14. It is evidence for triage, never proof
of collusion (C-02), and no threshold is frozen here (CL-27).

The benchmark is a paired test over CL-9 fixtures: it reports false
positives (clean/benign fixtures scoring at or above a candidate
threshold) and recall broken down by payload band at every swept
threshold, with Wilson score intervals, plus threshold-free ROC-AUC /
average-precision summaries with bootstrap intervals (DET-04).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from .fixtures import Fixture
from .lsb import _bootstrap_interval, _roc_auc, _score_summary, _wilson
from .parsing import (
    AnalysisResult,
    AnalysisStatus,
    Finding,
    ParserLimits,
    analyze_bytes,
    analyze_version,
)
from .store import ArtifactStore

FAMILY = "jpeg_dct"
DCT_DETECTOR_NAME = "dct-coefficient-pov-chisquare"
DCT_DETECTOR_VERSION = "1.0.0"
CONFIG_VERSION = "1.0.0"
BENCHMARK_SCHEMA = "covertlens.dct-benchmark"
BENCHMARK_SCHEMA_VERSION = 1
BENCHMARK_VERSION = "1.0.0"

PAYLOAD_BANDS = ("none", "low", "medium", "high")

_LIMITATIONS = (
    "quantized coefficient domain only (parser subset: 8-bit baseline "
    "4:4:4 JPEG); no IDCT or pixel-domain evidence is used",
    "global magnitude pairs-of-values chi-square; embedding that "
    "preserves coefficient histograms (e.g. +/-1 matching, adaptive "
    "selection) may evade it",
    "calibrated only on procedural synthetic covers at the recorded "
    "encoder configuration; other quality factors are untested",
    "score is evidence, not demonstrated collusion (C-02); thresholds "
    "unfrozen until CL-27",
)


@dataclass(frozen=True)
class DctConfig:
    """Versioned detector configuration; a change bumps ``version``."""

    version: str = CONFIG_VERSION
    # AC magnitudes at or above this can carry coefficient-LSB payload.
    carrier_min_magnitude: int = 2
    # Magnitude pairs whose total count is below this are too sparse
    # for the chi-square approximation and are excluded (in coverage).
    pair_min_count: int = 4

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        if self.carrier_min_magnitude < 1:
            raise ValueError("carrier_min_magnitude must be >= 1")
        if self.pair_min_count < 1:
            raise ValueError("pair_min_count must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "carrier_min_magnitude": self.carrier_min_magnitude,
            "pair_min_count": self.pair_min_count,
        }


DEFAULT_CONFIG = DctConfig()


def _coefficient_statistics(
    coefficients: tuple[tuple[int, ...], ...], config: DctConfig
) -> tuple[float, dict[str, Any], dict[str, int]]:
    """Return (score, evidence, counts) for quantized coefficient blocks."""
    magnitudes: dict[int, int] = {}
    ac_examined = 0
    carriers = 0
    for block in coefficients:
        for value in block[1:]:  # index 0 is DC; payload lives in AC terms
            ac_examined += 1
            magnitude = abs(int(value))
            if magnitude >= config.carrier_min_magnitude:
                carriers += 1
                magnitudes[magnitude] = magnitudes.get(magnitude, 0) + 1
    chi_square = 0.0
    pairs_used = 0
    imbalance = 0
    if magnitudes:
        for base in range(0, max(magnitudes) + 1, 2):
            even = magnitudes.get(base, 0)
            odd = magnitudes.get(base + 1, 0)
            pair_total = even + odd
            imbalance += abs(even - odd)
            if pair_total >= config.pair_min_count:
                pairs_used += 1
                expected = pair_total / 2.0
                chi_square += (
                    (even - expected) ** 2 + (odd - expected) ** 2
                ) / expected
    degrees = pairs_used - 1 if pairs_used else 0
    if pairs_used < 2 or chi_square <= 0:
        score = 1.0 if pairs_used >= 2 and carriers and chi_square <= 0 else 0.0
    else:
        score = min(1.0, degrees / chi_square)
    evidence = {
        "statistic": "coefficient_magnitude_pairs_of_values_chi_square",
        "chi_square": round(chi_square, 6),
        "degrees_of_freedom": degrees,
        "chi_square_per_df": (
            round(chi_square / degrees, 6) if degrees else 0.0
        ),
        "pairs_used": pairs_used,
        "carrier_lsb_one_fraction": _carrier_lsb_fraction(coefficients, config),
        "magnitude_pov_imbalance": (
            round(imbalance / carriers, 6) if carriers else 0.0
        ),
        "detector_config_version": config.version,
    }
    counts = {
        "blocks_examined": len(coefficients),
        "coefficients_examined": len(coefficients) * 64,
        "ac_coefficients_examined": ac_examined,
        "carriers_examined": carriers,
        "pairs_used": pairs_used,
    }
    return score, evidence, counts


def _carrier_lsb_fraction(
    coefficients: tuple[tuple[int, ...], ...], config: DctConfig
) -> float:
    total = 0
    ones = 0
    for block in coefficients:
        for value in block[1:]:
            magnitude = abs(int(value))
            if magnitude >= config.carrier_min_magnitude:
                total += 1
                ones += magnitude & 1
    return round(ones / total, 6) if total else 0.0


def detect_dct(
    result: AnalysisResult, config: DctConfig | None = None
) -> Finding | None:
    """Score one CL-13 result; ``None`` when DCT is not applicable.

    Applicable means: parsed JPEG with coefficient blocks present.
    PNGs, failed parses and coefficient-less results get no DCT
    finding — a missing finding is not a clean score (C-02).
    """
    active = config or DEFAULT_CONFIG
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind != "jpeg" or result.coefficients is None:
        return None
    score, evidence, counts = _coefficient_statistics(result.coefficients, active)
    image = result.image or {}
    coverage = {
        "applicable": True,
        "media_kind": "jpeg",
        "domain": "quantized_coefficients",
        "blocks_examined": counts["blocks_examined"],
        "coefficients_examined": counts["coefficients_examined"],
        "ac_coefficients_examined": counts["ac_coefficients_examined"],
        "carriers_examined": counts["carriers_examined"],
        "pairs_used": counts["pairs_used"],
        "width": int(image.get("width") or 0),
        "height": int(image.get("height") or 0),
        "components": int(image.get("components") or 3),
        "config_version": active.version,
    }
    limitations = list(_LIMITATIONS)
    limitations.append(
        f"encoder configuration scored: carrier |AC| >= "
        f"{active.carrier_min_magnitude} LSB (CL-9 dct-jpeg rule)"
    )
    if counts["pairs_used"] < 2:
        limitations.append(
            "insufficient magnitude-pair coverage; score is not reliable"
        )
    return Finding(
        family=FAMILY,
        detector_name=DCT_DETECTOR_NAME,
        detector_version=DCT_DETECTOR_VERSION,
        score=score,
        coverage=coverage,
        evidence=evidence,
        limitations=tuple(limitations),
    )


def analyze_dct_bytes(
    data: bytes,
    *,
    limits: ParserLimits | None = None,
    config: DctConfig | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
) -> AnalysisResult:
    """Parse exact bytes (CL-13) and attach the DCT finding when applicable."""
    result = analyze_bytes(
        data,
        limits=limits,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
    )
    finding = detect_dct(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


def analyze_dct_version(
    store: ArtifactStore,
    artifact_version_id: str,
    *,
    actor_id: str,
    limits: ParserLimits | None = None,
    config: DctConfig | None = None,
) -> AnalysisResult:
    """Score one stored original via its audited, hash-checked read."""
    result = analyze_version(
        store, artifact_version_id, actor_id=actor_id, limits=limits
    )
    finding = detect_dct(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


def benchmark_dct(
    fixtures: Iterable[Fixture],
    *,
    config: DctConfig | None = None,
    thresholds: Iterable[float] | None = None,
    bootstrap_replicates: int = 1000,
    bootstrap_seed: int = 20261028,
) -> dict[str, Any]:
    """Paired DCT benchmark: false positives and recall by payload band.

    Positives are ``encoded`` fixtures; ``clean`` and ``negative``
    fixtures are negatives (false positives are negatives scoring at
    or above a candidate threshold). Fixtures outside the `jpeg_dct`
    family are counted under ``skipped_non_dct``, never scored as
    negatives. Each encoded band also carries its own recall sweep;
    the `none` band carries the false-positive sweep.
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
        result = analyze_dct_bytes(fixture.data, config=active)
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

    def band_sweep(band_rows: list[dict[str, Any]], *, positive_band: bool):
        points = []
        for threshold in sweep_thresholds:
            hits = sum(
                1 for r in band_rows if float(r["score"]) >= threshold
            )
            if positive_band:
                points.append(
                    {
                        "threshold": round(threshold, 6),
                        "tp": hits,
                        "fn": len(band_rows) - hits,
                        "recall": _wilson(hits, len(band_rows)),
                    }
                )
            else:
                points.append(
                    {
                        "threshold": round(threshold, 6),
                        "fp": hits,
                        "tn": len(band_rows) - hits,
                        "false_positive_rate": _wilson(hits, len(band_rows)),
                    }
                )
        return points

    sweep: list[dict[str, Any]] = []
    for threshold in sweep_thresholds:
        tp = sum(1 for r in scored if r["label"] == 1 and float(r["score"]) >= threshold)
        fp = sum(1 for r in scored if r["label"] == 0 and float(r["score"]) >= threshold)
        tn = sum(1 for r in scored if r["label"] == 0 and float(r["score"]) < threshold)
        fn = sum(1 for r in scored if r["label"] == 1 and float(r["score"]) < threshold)
        sweep.append(
            {
                "threshold": round(threshold, 6),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": _wilson(tp, tp + fp),
                "recall": _wilson(tp, tp + fn),
                "false_positive_rate": _wilson(fp, fp + tn),
            }
        )

    by_band: dict[str, Any] = {}
    for band in PAYLOAD_BANDS:
        band_rows = [r for r in scored if r["payload_band"] == band]
        band_positive = [float(r["score"]) for r in band_rows if r["label"] == 1]
        by_band[band] = {
            "fixture_count": len(band_rows),
            "positive_count": len(band_positive),
            "negative_count": len(band_rows) - len(band_positive),
            "scores": _score_summary([float(r["score"]) for r in band_rows]),
            "roc_auc_vs_negatives": (
                _roc_auc(band_positive, negative) if band_positive else None
            ),
            "sweep": band_sweep(band_rows, positive_band=bool(band_positive)),
        }

    return {
        "schema": BENCHMARK_SCHEMA,
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "detector": {
            "family": FAMILY,
            "name": DCT_DETECTOR_NAME,
            "version": DCT_DETECTOR_VERSION,
            "config": active.to_dict(),
        },
        "thresholds_status": "unfrozen_placeholder",
        "fixture_count": len(rows),
        "scored_count": len(scored),
        "skipped_non_dct": skipped,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "rows": rows,
        "by_payload_band": by_band,
        "roc_auc": _bootstrap_interval(
            positive, negative, replicates=bootstrap_replicates,
            seed=bootstrap_seed, metric="roc_auc",
        ),
        "pr_auc": _bootstrap_interval(
            positive, negative, replicates=bootstrap_replicates,
            seed=bootstrap_seed, metric="average_precision",
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


def validate_dct_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one DCT benchmark report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == BENCHMARK_SCHEMA, f"schema must be {BENCHMARK_SCHEMA}")
    need(
        report.get("schema_version") == BENCHMARK_SCHEMA_VERSION,
        f"schema_version must be {BENCHMARK_SCHEMA_VERSION}",
    )
    need(bool(report.get("benchmark_version")), "benchmark_version is required")
    detector = report.get("detector") or {}
    need(detector.get("family") == FAMILY, f"detector.family must be {FAMILY}")
    need(detector.get("name") == DCT_DETECTOR_NAME, "detector.name is required")
    need(detector.get("version") == DCT_DETECTOR_VERSION, "detector.version is required")
    need(
        (detector.get("config") or {}).get("version") == CONFIG_VERSION,
        "detector.config.version is required",
    )
    need(
        report.get("thresholds_status") == "unfrozen_placeholder",
        "thresholds_status must stay unfrozen_placeholder until CL-27",
    )
    for band in PAYLOAD_BANDS:
        block = (report.get("by_payload_band") or {}).get(band)
        need(block is not None, f"by_payload_band.{band} is required")
        if block is not None:
            need(
                block.get("fixture_count")
                == block.get("positive_count", -1) + block.get("negative_count", -1),
                f"by_payload_band.{band} counts must add up",
            )
    for key in ("roc_auc", "pr_auc"):
        block = report.get(key) or {}
        estimate = block.get("estimate")
        if estimate is not None:
            need(0.0 <= float(estimate) <= 1.0, f"{key}.estimate must lie in [0, 1]")
            need(
                float(block.get("ci_low", -1)) <= float(estimate) <= float(block.get("ci_high", 2)),
                f"{key} interval must bracket its estimate",
            )
    for i, point in enumerate(report.get("sweep") or []):
        need(
            point.get("tp", -1) + point.get("fn", -1) == report.get("positive_count"),
            f"sweep[{i}] tp+fn must equal positive_count",
        )
        need(
            point.get("fp", -1) + point.get("tn", -1) == report.get("negative_count"),
            f"sweep[{i}] fp+tn must equal negative_count (false positives + true negatives)",
        )
    return errors
