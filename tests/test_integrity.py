"""CL-20 acceptance tests: gate races, retries, cache invalidation (ENF-05).

AC1 concurrency/retry/alternate-reference tests show zero unauthorized byte access
AC2 byte, detector or configuration changes invalidate cached results
AC3 run-context changes recompute verdicts while allowing safe image-score reuse
"""

from concurrent.futures import ThreadPoolExecutor

from covertlens.events import Verdict
from covertlens.fixtures import build_pair
from covertlens.gate import (
    InterceptionContext,
    InterceptionGate,
    PendingDeliveryError,
    WithheldError,
)
from covertlens.integrity import AnalysisCache, context_fingerprint
from covertlens.lsb import LSB_DETECTOR_NAME, LSB_DETECTOR_VERSION, detect_lsb
from covertlens.parsing import analyze_bytes
from covertlens.store import ArtifactStore
from covertlens.verdicts import FamilyThresholds, ThresholdConfig

CTX = InterceptionContext(run_id="run_i", sender_id="agent-a")
FROZEN = ThresholdConfig(
    families={"spatial_lsb": FamilyThresholds("spatial_lsb", "frozen", 0.25, 0.6, 0.9)}
)
FROZEN_V2 = ThresholdConfig(
    version="2.0.0",
    families={"spatial_lsb": FamilyThresholds("spatial_lsb", "frozen", 0.25, 0.6, 0.9)},
)


def lsb_result(payload=64):
    _, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=payload)
    return analyze_bytes(encoded.data), encoded


def test_changed_bytes_invalidate_cached_scores():
    cache = AnalysisCache()
    result, _ = lsb_result()
    calls = []

    def counting(res):
        calls.append(1)
        return detect_lsb(res)

    kw = dict(
        detector_name=LSB_DETECTOR_NAME,
        detector_version=LSB_DETECTOR_VERSION,
        config_version="1.0.0",
    )
    first = cache.get_or_score(result, counting, **kw)
    second = cache.get_or_score(result, counting, **kw)
    assert first is second and len(calls) == 1  # reuse for identical bytes
    other, _ = lsb_result(payload=65)
    assert other.content_hash != result.content_hash
    cache.get_or_score(other, counting, **kw)
    assert len(calls) == 2  # changed bytes recompute (C-05)


def test_detector_and_config_changes_invalidate_scores():
    cache = AnalysisCache()
    result, _ = lsb_result()
    finding = detect_lsb(result)
    cache.put_score(result, finding)
    assert (
        cache.get_score(
            result,
            detector_name=LSB_DETECTOR_NAME,
            detector_version=LSB_DETECTOR_VERSION,
            config_version="1.0.0",
        )
        is finding
    )
    # A detector version or config bump is a different key: a miss.
    assert (
        cache.get_score(
            result,
            detector_name=LSB_DETECTOR_NAME,
            detector_version="2.0.0",
            config_version="1.0.0",
        )
        is None
    )
    assert (
        cache.get_score(
            result,
            detector_name=LSB_DETECTOR_NAME,
            detector_version=LSB_DETECTOR_VERSION,
            config_version="2.0.0",
        )
        is None
    )
    stats = cache.stats()
    assert stats["scores"]["hits"] == 1 and stats["scores"]["misses"] == 2


def test_threshold_config_change_invalidates_verdicts():
    cache = AnalysisCache()
    result, _ = lsb_result()
    finding = detect_lsb(result)
    context = {"run_id": "run_i", "recipient_id": "agent-b"}
    first = cache.get_or_decide([finding], FROZEN, context=context)
    again = cache.get_or_decide([finding], FROZEN, context=context)
    assert again is first
    changed = cache.get_or_decide([finding], FROZEN_V2, context=context)
    assert changed is not first
    assert changed.config_version == "2.0.0"
    assert cache.stats()["verdicts"] == {"hits": 1, "misses": 2, "stores": 2}


def test_context_change_recomputes_verdict_but_reuses_score():
    cache = AnalysisCache()
    result, _ = lsb_result()
    calls = []

    def counting(res):
        calls.append(1)
        return detect_lsb(res)

    kw = dict(
        detector_name=LSB_DETECTOR_NAME,
        detector_version=LSB_DETECTOR_VERSION,
        config_version="1.0.0",
    )
    finding = cache.get_or_score(result, counting, **kw)
    ctx_a = {"run_id": "run_i", "episode_id": "ep_1", "recipient_id": "agent-b"}
    ctx_b = {"run_id": "run_i", "episode_id": "ep_2", "recipient_id": "agent-b"}
    assert context_fingerprint(ctx_a) != context_fingerprint(ctx_b)
    first = cache.get_or_decide([finding], FROZEN, context=ctx_a)
    second = cache.get_or_decide([finding], FROZEN, context=ctx_b)
    assert second is not first  # verdict recomputed for new context
    reused = cache.get_or_score(result, counting, **kw)
    assert reused is finding and len(calls) == 1  # score safely reused
    stats = cache.stats()
    assert stats["scores"]["hits"] >= 1 and stats["verdicts"]["misses"] == 2


def test_races_retries_and_alternate_references_serve_nothing_unauthorized():
    gate = InterceptionGate(ArtifactStore())
    _, encoded = build_pair("spatial_lsb", width=32, height=24, payload_bytes=16)
    handle = gate.intercept_reference(
        "R-03", "artifact://img", lambda r: encoded.data, CTX
    )
    # An alternate route/reference to the same bytes carries the same
    # original hash (a new logical artifact, the identical bytes).
    again = gate.intercept_reference(
        "R-02", "artifact://img", lambda r: encoded.data, CTX
    )
    assert again.content_hash == handle.content_hash
    delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
    retry = gate.attempt_delivery(handle, recipient_id="agent-b")
    assert retry.delivery_id == delivery.delivery_id
    token = gate.issue_cached_link(delivery.delivery_id)

    def try_everything(_):
        served = 0
        for attempt in (
            lambda: gate.recipient_access(delivery.delivery_id),
            lambda: gate.redeem_cached_link(token),
            lambda: gate.serve_via_route("R-04", delivery.delivery_id),
        ):
            try:
                attempt()
                served += 1
            except (PendingDeliveryError, WithheldError):
                pass
        return served

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(try_everything, range(16))) == 0
    gate.record_verdict(delivery.delivery_id, Verdict.QUARANTINE)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(try_everything, range(16))) == 0
    report = gate.access_attempt_report()
    assert report["unauthorized_served"] == 0 and report["served"] == 0
    attempted = [
        e for e in gate.events("run_i") if e.event_type.value == "delivery.attempted"
    ]
    assert len(attempted) == 1  # retry stayed idempotent under load
