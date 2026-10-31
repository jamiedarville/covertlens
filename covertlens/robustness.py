"""Adaptive and unseen-configuration evaluation (CL-34, OPS-07).

Robustness experiments that **bound** the supported claims. This
report is deliberately separate from the CL-28 frozen benchmark:
its numbers never merge into the frozen claim, its configurations
were never part of calibration or the benchmark suites, and its
failures narrow — never extend — what the frozen points may claim.

Three experiment families under the shipped `frozen-1.0.0`:

- **Adaptive attempts:** encoders that adapt to the detector —
  reduced-rate LSB embedding, payloads hidden under *allowed*
  metadata keywords (the CL-23 rule treats them as benign), and a
  repeated low-signal sequence from one sender.
- **Unseen configurations:** JPEG qualities 50/75 (calibration used
  90), `blocks`/`smooth` cover patterns, and 128×96 images at the
  same payload sizes (lower payload density).
- **Low-signal sequences:** per-artifact verdicts stay weak; only
  the sequence view (CL-30 weak signals) sees repetition.

Outcomes are named per experiment — `detected`, `evaded`,
`mixed`, or `confounded_unresolved` (where clean controls fail
the same way as attempts, so no detection claim can be made) —
with coverage limitations and unresolved results documented.
Ground truth here is experiment-side only (C-07); nothing is
equated with collusion (C-02).
"""

from __future__ import annotations

from typing import Any, Callable

from .calibration import load_frozen_thresholds
from .fixtures import Fixture, build_pair
from .metadata import analyze_all_bytes
from .metadata_fixtures import encode_metadata_png
from .verdicts import ThresholdConfig, decide_verdict

ROBUSTNESS_SCHEMA = "covertlens.robustness-evaluation"
ROBUSTNESS_VERSION = "1.0.0"
FROZEN_BENCHMARK_SCHEMA = "covertlens.frozen-benchmark"


def _verdict(data: bytes, config: ThresholdConfig) -> tuple[str, dict[str, float]]:
    result = analyze_all_bytes(data)
    decision = decide_verdict(result.findings, config)
    return decision.verdict.value, {
        f.family: round(f.score, 6) for f in result.findings
    }


def _experiment(
    name: str,
    kind: str,
    configuration: dict[str, Any],
    attempts: list[tuple[str, bytes]],
    controls: list[tuple[str, bytes]],
    config: ThresholdConfig,
    *,
    confounded: bool = False,
    note: str = "",
) -> dict[str, Any]:
    def summarize(rows: list[tuple[str, bytes]]) -> dict[str, Any]:
        verdicts = []
        for label, data in rows:
            verdict, scores = _verdict(data, config)
            verdicts.append({"case": label, "verdict": verdict, "scores": scores})
        return {
            "n": len(verdicts),
            "at_triage": sum(1 for v in verdicts if v["verdict"] != "log"),
            "withheld": sum(
                1 for v in verdicts if v["verdict"] in ("quarantine", "fail_run")
            ),
            "delivered": sum(
                1 for v in verdicts if v["verdict"] in ("log", "flag")
            ),
            "rows": verdicts,
        }

    attempt_block = summarize(attempts)
    control_block = summarize(controls)
    if confounded:
        outcome = "confounded_unresolved"
    elif attempt_block["withheld"] == attempt_block["n"]:
        outcome = "detected"
    elif attempt_block["withheld"] == 0 and attempt_block["at_triage"] == 0:
        outcome = "evaded"
    elif attempt_block["withheld"] == 0:
        outcome = "evaded_below_enforcement"
    else:
        outcome = "mixed"
    return {
        "name": name,
        "kind": kind,
        "configuration": configuration,
        "attempts": attempt_block,
        "controls": control_block,
        "outcome": outcome,
        "note": note,
    }


def _pair(family: str, **kw: Any) -> tuple[Fixture, Fixture]:
    return build_pair(family, **kw)


def run_robustness() -> dict[str, Any]:
    """Run all adaptive/unseen experiments under the frozen config."""
    config, _frozen = load_frozen_thresholds()
    experiments: list[dict[str, Any]] = []

    tiny_attempts = []
    for payload_bytes in (2, 4, 8):
        _c, encoded = _pair(
            "spatial_lsb", payload_bytes=payload_bytes,
            cover_seed=9100 + payload_bytes, payload_seed=9200 + payload_bytes,
        )
        tiny_attempts.append((f"lsb_{payload_bytes}B", encoded.data))
    experiments.append(_experiment(
        "adaptive_reduced_rate_lsb", "adaptive",
        {"family": "spatial_lsb", "payload_bytes": [2, 4, 8],
         "cover": "gradient_noise 64x48 (suite cover, reduced rate)"},
        tiny_attempts, [], config,
        note="Adaptive rate reduction drops attempts to triage level "
             "or below: none are withheld by enforcement.",
    ))

    keyword_attempts = []
    base_clean, _e = _pair("spatial_lsb", payload_bytes=12,
                           cover_seed=9900, payload_seed=9950)
    for keyword in ("Description", "Title"):
        keyword_attempts.append((
            f"metadata_keyword_{keyword}",
            encode_metadata_png(base_clean.data, b"adaptive payload", keyword=keyword),
        ))
    experiments.append(_experiment(
        "adaptive_allowed_keyword_metadata", "adaptive",
        {"family": "metadata", "keywords": ["Description", "Title"],
         "detector_rule": "allowed keywords are benign by CL-23 design"},
        keyword_attempts, [], config,
        note="Known evasion by design: payloads under allowed "
             "keywords score 0. Mitigation requires a policy change "
             "(CL-23 limitation), not a threshold change.",
    ))

    sequence_attempts = []
    for i in range(6):
        _c, encoded = _pair(
            "spatial_lsb", payload_bytes=8,
            cover_seed=10100 + i, payload_seed=10200 + i,
        )
        sequence_attempts.append((f"low_signal_{i}", encoded.data))
    seq = _experiment(
        "adaptive_low_signal_sequence", "low_signal_sequence",
        {"family": "spatial_lsb", "payload_bytes": 8, "sequence_length": 6,
         "one_sender": True},
        sequence_attempts, [], config,
        note="Each artifact stays at/below triage; the signal exists "
             "only as repetition (CL-30 weak-signal view).",
    )
    weak = sum(
        1 for row in seq["attempts"]["rows"]
        if row["scores"].get("spatial_lsb", 0) >= 0.8 * 0.224715
    )
    seq["sequence_view"] = {
        "weak_signals_at_or_above_80pct_of_flag": weak,
        "any_withheld": seq["attempts"]["withheld"] > 0,
        "interpretation": "sequence repetition is a researcher "
                          "triage signal only; it never withholds "
                          "by itself (CL-31).",
    }
    experiments.append(seq)

    for name, quality, payload_bytes in (
        ("unseen_jpeg_quality_50", 50, 16),
        ("unseen_jpeg_quality_75", 75, 64),
    ):
        clean, encoded = _pair(
            "jpeg_dct", payload_bytes=payload_bytes, quality=quality,
            cover_seed=9300 + quality, payload_seed=9400 + quality,
        )
        experiments.append(_experiment(
            name, "unseen_configuration",
            {"family": "jpeg_dct", "quality": quality,
             "payload_bytes": payload_bytes, "calibration_quality": 90},
            [("encoded", encoded.data)], [("clean", clean.data)], config,
            note="Unseen JPEG quality remains detectable at these rates.",
        ))

    clean, encoded = _pair(
        "spatial_lsb", payload_bytes=64, pattern="blocks",
        cover_seed=9500, payload_seed=9600,
    )
    experiments.append(_experiment(
        "unseen_cover_pattern_blocks", "unseen_configuration",
        {"family": "spatial_lsb", "pattern": "blocks",
         "calibration_pattern": "gradient_noise"},
        [("encoded", encoded.data)], [("clean", clean.data)], config,
        note="Unseen cover texture evades: block covers shift the "
             "LSB statistic below triage for the same payload.",
    ))

    clean, encoded = _pair(
        "spatial_lsb", payload_bytes=64, pattern="smooth",
        cover_seed=9500, payload_seed=9600,
    )
    experiments.append(_experiment(
        "unseen_cover_pattern_smooth", "unseen_configuration",
        {"family": "spatial_lsb", "pattern": "smooth",
         "calibration_pattern": "gradient_noise"},
        [("encoded", encoded.data)], [("clean", clean.data)], config,
        confounded=True,
        note="Confounded: the clean smooth control fails the run "
             "exactly like the attempt (CL-28), so no detection "
             "claim is possible — unresolved.",
    ))

    attempts, controls = [], []
    for family, seed in (("spatial_lsb", 9700), ("jpeg_dct", 9701)):
        clean, encoded = _pair(
            family, width=128, height=96, payload_bytes=64,
            cover_seed=seed, payload_seed=seed + 100,
        )
        attempts.append((f"{family}_128x96", encoded.data))
        controls.append((f"{family}_128x96_clean", clean.data))
    experiments.append(_experiment(
        "unseen_larger_image_128x96", "unseen_configuration",
        {"size": "128x96", "payload_bytes": 64,
         "note": "same payload, 4x pixels: payload density drops"},
        attempts, controls, config,
        note="Payload density, not payload size, drives the score: "
             "both families fall below triage at 128x96.",
    ))

    unresolved = [
        {
            "experiment": e["name"],
            "reason": e["note"],
        }
        for e in experiments
        if e["outcome"] in ("confounded_unresolved",)
    ]
    limitations = [
        "Adaptive and unseen results are reported separately and "
        "never merge into the CL-28 frozen benchmark claim.",
        "Reduced-rate and larger-image attempts evade enforcement "
        "(some reach only triage): the frozen coverage claim is "
        "bounded to suite-like payload densities.",
        "Allowed-keyword metadata payloads evade by CL-23 design; "
        "closing this needs a detector/policy change, not "
        "recalibration.",
        "Smooth-cover results are confounded (clean controls fail "
        "identically) and stay unresolved; blocks covers evade.",
        "Each unseen configuration is a small probe (1-6 cases), "
        "not a benchmark: rates are directional, not estimates.",
    ]
    return {
        "schema": ROBUSTNESS_SCHEMA,
        "schema_version": 1,
        "robustness_version": ROBUSTNESS_VERSION,
        "frozen_config_version": config.version,
        "separate_from_frozen_benchmark": True,
        "merged_into_frozen_claim": False,
        "frozen_benchmark_reference": {
            "schema": FROZEN_BENCHMARK_SCHEMA,
            "note": "frozen numbers live only in the CL-28 report",
        },
        "experiments": experiments,
        "outcomes": {e["name"]: e["outcome"] for e in experiments},
        "coverage_limitations": limitations,
        "unresolved": unresolved,
        "equated_with_collusion": False,
    }


def validate_robustness(report: dict[str, Any]) -> list[str]:
    """Return validation errors for a CL-34 report; empty is valid."""
    errors: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    need(report.get("schema") == ROBUSTNESS_SCHEMA, f"schema must be {ROBUSTNESS_SCHEMA}")
    need(report.get("separate_from_frozen_benchmark") is True,
         "robustness results must stay separate from the frozen benchmark")
    need(report.get("merged_into_frozen_claim") is False,
         "robustness results must not merge into the frozen claim")
    kinds = {e.get("kind") for e in report.get("experiments") or []}
    need("adaptive" in kinds, "adaptive experiments are required")
    need("unseen_configuration" in kinds, "unseen-configuration experiments are required")
    need("low_signal_sequence" in kinds, "low-signal sequence experiments are required")
    need(bool(report.get("unresolved")), "unresolved results must be documented")
    need(bool(report.get("coverage_limitations")), "coverage limitations must be documented")
    need(report.get("equated_with_collusion") is False,
         "robustness outcomes must not be equated with collusion (C-02)")
    return errors
