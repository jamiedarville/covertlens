"""CL-56: audit bugs propagate and conclusions follow evidence."""

from copy import deepcopy

import pytest

from covertlens import handoff, latency, pilot, route_audit
from covertlens.calibration import load_frozen_thresholds
from covertlens.fixtures import build_pair
from covertlens.gate import InterceptionGate
from covertlens.integrity import AnalysisCache
from covertlens.lsb import detect_lsb
from covertlens.parsing import analyze_bytes
from covertlens.robustness import _experiment
from covertlens.scorecard import load_scorecard, validate_scorecard


def test_default_cache_lookup_hits_and_ambiguous_config_misses():
    from dataclasses import replace

    clean, _ = build_pair("spatial_lsb")
    result = analyze_bytes(clean.data)
    finding = detect_lsb(result)
    cache = AnalysisCache()
    cache.put_score(result, finding)
    kwargs = dict(
        detector_name=finding.detector_name, detector_version=finding.detector_version
    )
    assert cache.get_score(result, **kwargs) is finding
    assert (
        cache.get_or_score(
            result, lambda _: pytest.fail("unexpected compute"), **kwargs
        )
        is finding
    )
    cache.put_score(
        result, replace(finding, evidence={"detector_config_version": "other"})
    )
    assert cache.get_score(result, **kwargs) is None
    assert cache.get_score(result, config_version="1.0.0", **kwargs) is finding


@pytest.mark.parametrize(
    "audit",
    [
        route_audit.run_route_audit,
        latency.limit_behavior_checks,
        lambda: latency.gate_reliability_check(deliveries=3),
        handoff._quarantine_handling,
        lambda: pilot.run_pilot(),
    ],
)
def test_programming_errors_are_not_successful_denials(monkeypatch, audit):
    def broken(*args, **kwargs):
        raise TypeError("planted gate regression")

    monkeypatch.setattr(InterceptionGate, "recipient_access", broken)
    with pytest.raises(TypeError, match="planted gate regression"):
        audit()


def test_confounded_is_computed_from_clean_control(monkeypatch):
    from covertlens import robustness

    config, _ = load_frozen_thresholds()
    monkeypatch.setattr(
        robustness,
        "_verdict",
        lambda data, cfg: ("quarantine" if data == b"bad" else "log", {}),
    )
    clear = _experiment(
        "probe", "adaptive", {}, [("attempt", b"bad")], [("clean", b"good")], config
    )
    confounded = _experiment(
        "probe", "adaptive", {}, [("attempt", b"bad")], [("clean", b"bad")], config
    )
    assert clear["outcome"] == "detected"
    assert confounded["outcome"] == "confounded_unresolved"


def test_scorecard_release_refuses_a_missed_section_target():
    card = deepcopy(load_scorecard())
    card["decision"].update(value="release", limitations=[])
    card["sections"]["detection_frozen_benchmark"]["per_family"]["spatial_lsb"][
        "recall_at_triage"
    ] = 0.0
    assert any("every section target" in error for error in validate_scorecard(card))
    card["decision"]["value"] = "release_with_limitations"
    assert any("limitations" in error for error in validate_scorecard(card))
