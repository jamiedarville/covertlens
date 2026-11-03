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

CL-61 adds a second detector in this module, `dct-calibrated-histogram`
(a neighbor-calibrated histogram total-variation test, gated where
neighbor calibration is unreliable), benchmarked against this PoV
detector on +/-1 matching fixtures by `benchmark_dct_calibrated`.
Both detectors stay individually visible; nothing here refreezes the
CL-27/CL-54 thresholds.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from .acceleration import numpy_backend
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
    "4:4:4 / 4:2:2 / 4:2:0 or grayscale JPEG); no IDCT or pixel-domain evidence is used",
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
    np = numpy_backend()
    carrier_fraction = None
    if np is not None and coefficients:
        ac = np.abs(np.asarray(coefficients, dtype=np.int64)[:, 1:])
        ac_examined = int(ac.size)
        selected = ac[ac >= config.carrier_min_magnitude]
        carriers = int(selected.size)
        values, counts = np.unique(selected, return_counts=True)
        magnitudes = dict(zip(values.tolist(), counts.tolist(), strict=True))
        carrier_fraction = (
            round(int((selected & 1).sum()) / carriers, 6) if carriers else 0.0
        )
    else:
        for block in coefficients:
            for value in block[1:]:  # DC is never a carrier
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
        "chi_square_per_df": (round(chi_square / degrees, 6) if degrees else 0.0),
        "pairs_used": pairs_used,
        "carrier_lsb_one_fraction": carrier_fraction
        if carrier_fraction is not None
        else _carrier_lsb_fraction(coefficients, config),
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
            hits = sum(1 for r in band_rows if float(r["score"]) >= threshold)
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
            positive,
            negative,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed,
            metric="roc_auc",
        ),
        "pr_auc": _bootstrap_interval(
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


CAL_DETECTOR_NAME = "dct-calibrated-histogram"
CAL_DETECTOR_VERSION = "1.0.0"
CAL_CONFIG_VERSION = "1.0.0"
CAL_BENCHMARK_SCHEMA = "covertlens.dct-calibrated-benchmark"
CAL_BENCHMARK_VERSION = "1.0.0"

_CAL_LIMITATIONS = (
    "calibrated histogram estimated in the coefficient domain from "
    "same-frequency adjacent-block coefficients (no IDCT, pixel "
    "reconstruction or recompression is performed)",
    "neighbor calibration requires spatially correlated blocks in a "
    "4:4:4 or grayscale block layout; subsampled or uncorrelated "
    "JPEGs are gated to 0 as unreliable",
    "calibrated only on procedural smooth-field covers (CL-61) at "
    "the recorded encoder configuration; other quality factors and "
    "natural-image covers are untested",
    "score is evidence, not demonstrated collusion (C-02); thresholds "
    "unfrozen (CL-61 does not refreeze the CL-27/CL-54 points)",
)


@dataclass(frozen=True)
class DctCalibratedConfig:
    """Versioned calibrated-histogram configuration (CL-61)."""

    version: str = CAL_CONFIG_VERSION
    # Total-variation reference: score = TV distance / this, capped.
    tv_reference: float = 0.1
    # Minimum adjacent-block coefficient agreement for calibration
    # to count as reliable.
    neighbor_agreement_min: float = 0.8
    # Hard score cap: this unfrozen detector stays below the frozen
    # quarantine point (0.122108), so it can never by itself cause
    # withholding before a dedicated freeze calibrates points for it.
    score_cap: float = 0.09

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("version is required")
        if self.tv_reference <= 0:
            raise ValueError("tv_reference must be > 0")
        if not 0.0 <= self.neighbor_agreement_min <= 1.0:
            raise ValueError("neighbor_agreement_min must lie in [0, 1]")
        if not 0.0 < self.score_cap <= 1.0:
            raise ValueError("score_cap must lie in (0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tv_reference": self.tv_reference,
            "neighbor_agreement_min": self.neighbor_agreement_min,
            "score_cap": self.score_cap,
        }


CAL_DEFAULT_CONFIG = DctCalibratedConfig()


def _calibrated_statistics(
    coefficients: tuple[tuple[int, ...], ...],
    *,
    blocks_x: int,
    stride: int,
    config: DctCalibratedConfig,
) -> tuple[float, dict[str, Any], dict[str, int]]:
    """Return (score, evidence, counts) for the calibrated histogram test.

    The calibrated histogram predicts each AC coefficient as the rounded
    mean of the same-frequency coefficients in its left/right neighbor
    blocks (same component slot); embedding noise breaks that spatial
    prediction, so the total-variation distance between the observed
    AC magnitude histogram and the calibrated histogram grows.
    """
    rows = len(coefficients) // (blocks_x * stride) if blocks_x and stride else 0

    def block_at(mx: int, my: int, slot: int) -> tuple[int, ...]:
        return coefficients[(my * blocks_x + mx) * stride + slot]

    observed: dict[int, int] = {}
    calibrated: dict[int, int] = {}
    neighbor_pairs = 0
    neighbor_equal = 0
    for my in range(rows):
        for mx in range(blocks_x):
            for slot in range(stride):
                block = block_at(mx, my, slot)
                neighbors = []
                if mx > 0:
                    neighbors.append(block_at(mx - 1, my, slot))
                if mx < blocks_x - 1:
                    neighbors.append(block_at(mx + 1, my, slot))
                if my > 0:
                    neighbors.append(block_at(mx, my - 1, slot))
                if my < rows - 1:
                    neighbors.append(block_at(mx, my + 1, slot))
                if not neighbors:
                    neighbors = [block]
                if mx < blocks_x - 1:
                    other = block_at(mx + 1, my, slot)
                    for k in range(1, 64):
                        neighbor_pairs += 1
                        if block[k] == other[k]:
                            neighbor_equal += 1
                for k in range(1, 64):
                    magnitude = abs(int(block[k]))
                    observed[magnitude] = observed.get(magnitude, 0) + 1
                    estimate = int(
                        round(sum(int(nb[k]) for nb in neighbors) / len(neighbors))
                    )
                    cal_mag = abs(estimate)
                    calibrated[cal_mag] = calibrated.get(cal_mag, 0) + 1
    total = sum(observed.values())
    tv = 0.0
    if total:
        keys = set(observed) | set(calibrated)
        tv = (
            0.5
            * sum(abs(observed.get(k, 0) - calibrated.get(k, 0)) for k in keys)
            / total
        )
    agreement = neighbor_equal / neighbor_pairs if neighbor_pairs else 0.0
    reliable = (
        rows >= 2
        and blocks_x >= 2
        and neighbor_pairs > 0
        and agreement >= config.neighbor_agreement_min
    )
    score = min(config.score_cap, tv / config.tv_reference) if reliable else 0.0
    evidence = {
        "statistic": "calibrated_histogram_total_variation",
        "tv_distance": round(tv, 6),
        "neighbor_agreement": round(agreement, 6),
        "neighbor_pairs": neighbor_pairs,
        "reliable": reliable,
        "detector_config_version": config.version,
    }
    counts = {
        "blocks_examined": len(coefficients),
        "ac_coefficients_examined": total,
        "neighbor_pairs": neighbor_pairs,
    }
    return round(score, 6), evidence, counts


def detect_dct_calibrated(
    result: AnalysisResult, config: DctCalibratedConfig | None = None
) -> Finding | None:
    """Score one CL-13 result with the calibrated histogram test (CL-61).

    A second, individually visible `jpeg_dct` detector alongside
    `dct-coefficient-pov-chisquare`. Applicable means a parsed JPEG
    with coefficient blocks in a 4:4:4 or grayscale layout; other
    layouts and uncorrelated blocks are gated to 0 with the limitation
    recorded (never read as a clean verdict, C-02).
    """
    active = config or CAL_DEFAULT_CONFIG
    if result.status is not AnalysisStatus.PARSED:
        return None
    if result.media_kind != "jpeg" or result.coefficients is None:
        return None
    image = result.image or {}
    width = int(image.get("width") or 0)
    height = int(image.get("height") or 0)
    components = int(image.get("components") or 3)
    sampling = str(image.get("sampling") or "")
    stride = components if components in (1, 3) else 3
    blocks_x = (width + 7) // 8 if width else 0
    layout_ok = sampling in ("4:4:4", "grayscale") and blocks_x >= 2
    if layout_ok and len(result.coefficients) % (blocks_x * stride) != 0:
        layout_ok = False
    if layout_ok:
        score, evidence, counts = _calibrated_statistics(
            result.coefficients, blocks_x=blocks_x, stride=stride, config=active
        )
    else:
        score = 0.0
        evidence = {
            "statistic": "calibrated_histogram_total_variation",
            "tv_distance": 0.0,
            "neighbor_agreement": 0.0,
            "neighbor_pairs": 0,
            "reliable": False,
            "detector_config_version": active.version,
        }
        counts = {
            "blocks_examined": len(result.coefficients),
            "ac_coefficients_examined": len(result.coefficients) * 63,
            "neighbor_pairs": 0,
        }
    coverage = {
        "applicable": True,
        "media_kind": "jpeg",
        "domain": "quantized_coefficients",
        "blocks_examined": counts["blocks_examined"],
        "coefficients_examined": counts["blocks_examined"] * 64,
        "ac_coefficients_examined": counts["ac_coefficients_examined"],
        "neighbor_pairs": counts["neighbor_pairs"],
        "width": width,
        "height": height,
        "components": components,
        "sampling": sampling,
        "config_version": active.version,
    }
    limitations = list(_CAL_LIMITATIONS)
    if not evidence["reliable"]:
        limitations.append(
            "insufficient neighbor calibration; calibrated score is not reliable"
        )
    return Finding(
        family=FAMILY,
        detector_name=CAL_DETECTOR_NAME,
        detector_version=CAL_DETECTOR_VERSION,
        score=score,
        coverage=coverage,
        evidence=evidence,
        limitations=tuple(limitations),
    )


def analyze_dct_calibrated_bytes(
    data: bytes,
    *,
    limits: ParserLimits | None = None,
    config: DctCalibratedConfig | None = None,
    artifact_id: str | None = None,
    artifact_version_id: str | None = None,
) -> AnalysisResult:
    """Parse exact bytes (CL-13) and attach the calibrated finding."""
    result = analyze_bytes(
        data,
        limits=limits,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
    )
    finding = detect_dct_calibrated(result, config)
    if finding is None:
        return result
    return replace(result, findings=(finding,))


def benchmark_dct_calibrated(
    fixtures: Iterable[Fixture],
    *,
    config: DctCalibratedConfig | None = None,
    pov_config: DctConfig | None = None,
    bootstrap_replicates: int = 1000,
    bootstrap_seed: int = 20261101,
) -> dict[str, Any]:
    """Compare calibrated-histogram vs PoV scores on +/-1 fixtures (CL-61).

    Both detectors stay individually visible: every row carries both
    scores, and each detector gets its own bootstrap ROC-AUC.
    """
    from .lsb import _bootstrap_interval, _roc_auc, _score_summary

    active = config or CAL_DEFAULT_CONFIG
    if bootstrap_replicates < 0:
        raise ValueError("bootstrap_replicates must be >= 0")
    rows: list[dict[str, Any]] = []
    skipped = 0
    for fixture in fixtures:
        if fixture.family != FAMILY:
            skipped += 1
            continue
        result = analyze_bytes(fixture.data)
        cal_finding = detect_dct_calibrated(result, active)
        pov_finding = detect_dct(result, pov_config)
        rows.append(
            {
                "fixture_id": fixture.fixture_id,
                "role": fixture.role,
                "label": 1 if fixture.role == "encoded" else 0,
                "payload_band": fixture.payload_band,
                "payload_bits": fixture.payload_bits,
                "bits_per_pixel": round(fixture.bits_per_pixel, 6),
                "applicable": cal_finding is not None,
                "calibrated_score": (
                    round(cal_finding.score, 6) if cal_finding else None
                ),
                "pov_score": round(pov_finding.score, 6) if pov_finding else None,
            }
        )
    scored = [r for r in rows if r["calibrated_score"] is not None]
    cal_pos = [float(r["calibrated_score"]) for r in scored if r["label"] == 1]
    cal_neg = [float(r["calibrated_score"]) for r in scored if r["label"] == 0]
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
    cal_auc = _bootstrap_interval(
        cal_pos,
        cal_neg,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
        metric="roc_auc",
    )
    pov_auc = _bootstrap_interval(
        pov_pos,
        pov_neg,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
        metric="roc_auc",
    )
    by_band: dict[str, Any] = {}
    for band in PAYLOAD_BANDS:
        band_rows = [r for r in scored if r["payload_band"] == band]
        band_pos = [float(r["calibrated_score"]) for r in band_rows if r["label"] == 1]
        by_band[band] = {
            "fixture_count": len(band_rows),
            "positive_count": len(band_pos),
            "negative_count": len(band_rows) - len(band_pos),
            "scores": _score_summary([float(r["calibrated_score"]) for r in band_rows]),
            "roc_auc_vs_negatives": (_roc_auc(band_pos, cal_neg) if band_pos else None),
        }
    return {
        "schema": CAL_BENCHMARK_SCHEMA,
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": CAL_BENCHMARK_VERSION,
        "detector": {
            "family": FAMILY,
            "name": CAL_DETECTOR_NAME,
            "version": CAL_DETECTOR_VERSION,
            "config": active.to_dict(),
        },
        "comparator": {
            "family": FAMILY,
            "name": DCT_DETECTOR_NAME,
            "version": DCT_DETECTOR_VERSION,
        },
        "thresholds_status": "unfrozen_placeholder",
        "fixture_count": len(rows),
        "scored_count": len(scored),
        "skipped_non_dct": skipped,
        "positive_count": len(cal_pos),
        "negative_count": len(cal_neg),
        "rows": rows,
        "by_payload_band": by_band,
        "calibrated_roc_auc": cal_auc,
        "pov_roc_auc": pov_auc,
        "calibrated_beats_pov": bool(
            cal_auc.get("estimate") is not None
            and pov_auc.get("estimate") is not None
            and float(cal_auc["estimate"]) > float(pov_auc["estimate"])
        ),
        "limitations": list(_CAL_LIMITATIONS)
        + [
            "benchmark fixtures are the CL-61 smooth-field +/-1 suite; "
            "bootstrap intervals are conditional on the observed sample"
        ],
    }


def validate_dct_calibrated_benchmark(report: dict[str, Any]) -> list[str]:
    """Return validation errors for one CL-61 calibrated benchmark."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(
        report.get("schema") == CAL_BENCHMARK_SCHEMA,
        f"schema must be {CAL_BENCHMARK_SCHEMA}",
    )
    need(
        report.get("schema_version") == BENCHMARK_SCHEMA_VERSION,
        f"schema_version must be {BENCHMARK_SCHEMA_VERSION}",
    )
    need(bool(report.get("benchmark_version")), "benchmark_version is required")
    detector = report.get("detector") or {}
    need(detector.get("family") == FAMILY, f"detector.family must be {FAMILY}")
    need(detector.get("name") == CAL_DETECTOR_NAME, "detector.name is required")
    need(
        detector.get("version") == CAL_DETECTOR_VERSION,
        "detector.version is required",
    )
    need(
        (detector.get("config") or {}).get("version") == CAL_CONFIG_VERSION,
        "detector.config.version is required",
    )
    comparator = report.get("comparator") or {}
    need(
        comparator.get("name") == DCT_DETECTOR_NAME,
        "comparator must stay individually visible (dct-coefficient-pov-chisquare)",
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
    for key in ("calibrated_roc_auc", "pov_roc_auc"):
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
    need(
        detector.get("version") == DCT_DETECTOR_VERSION, "detector.version is required"
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
                float(block.get("ci_low", -1))
                <= float(estimate)
                <= float(block.get("ci_high", 2)),
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
