"""CL-25 acceptance tests: researcher run report and triage (REV-05).

AC1 report includes originals, component findings, prior context and action timeline
AC2 review supports the five dispositions
AC3 heatmaps/scores are labeled evidence aids rather than decoded messages
"""

import json

import pytest

from covertlens.events import Event, EventType, ParseStatus, Verdict
from covertlens.fixtures import build_pair
from covertlens.gate import InterceptionContext, InterceptionGate
from covertlens.lsb import analyze_lsb_version
from covertlens.report import (
    DISPOSITIONS,
    apply_review,
    build_run_report,
    validate_run_report,
)
from covertlens.store import ArtifactStore

TS = "2026-10-28T12:00:00Z"
RUN = "run_rep"


def sample_report():
    gate = InterceptionGate(ArtifactStore())
    ctx = InterceptionContext(run_id=RUN, episode_id="ep_1", sender_id="agent-a")
    clean, encoded = build_pair("spatial_lsb", width=64, height=48, payload_bytes=64)
    results, deliveries = [], []
    for fixture in (clean, encoded):
        handle = gate.intercept_bytes("R-01", fixture.data, ctx)
        results.append(
            analyze_lsb_version(
                gate.store, handle.artifact_version_id, actor_id="detector"
            )
        )
        delivery = gate.attempt_delivery(handle, recipient_id="agent-b")
        gate.record_verdict(delivery.delivery_id, Verdict.FLAG)
        gate.recipient_access(delivery.delivery_id)
        gate.record_parse(delivery.delivery_id, ParseStatus.PARSED)
        deliveries.append(delivery)
    events = gate.events(RUN)
    events.append(
        Event(
            EventType.RECIPIENT_ACTION,
            RUN,
            len(events),
            TS,
            delivery_id=deliveries[1].delivery_id,
            recipient_id="agent-b",
            payload={"action": "answer"},
        )
    )
    return build_run_report(events, results, report_id="rpt_1"), deliveries


def test_report_includes_originals_findings_context_and_timeline():
    report, deliveries = sample_report()
    assert validate_run_report(report) == []
    assert report["run_id"] == RUN and report["report_id"] == "rpt_1"
    assert len(report["originals"]) == 2
    for original in report["originals"]:
        assert original["content_hash"].startswith("sha256:")
        assert "data" not in original  # references, never embedded bytes
        assert original["findings"][0]["family"] == "spatial_lsb"
    seqs = [e["seq"] for e in report["timeline"]]
    assert seqs == sorted(seqs)
    assert report["timeline"][-1]["event_type"] == "recipient.action"
    assert report["prior_context"]["participants"]["agent-b"]["actions"]
    assert report["prior_context"]["episodes"]["ep_1"]["deliveries"]
    assert len(report["triage_queue"]) == 2
    assert (
        report["triage_queue"][0]["max_score"] >= report["triage_queue"][1]["max_score"]
    )
    assert all(r["disposition"] == "unresolved" for r in report["triage_queue"])
    json.dumps(report)


def test_review_supports_all_five_dispositions():
    report, deliveries = sample_report()
    target = deliveries[0].delivery_id
    for disposition in DISPOSITIONS:
        kwargs = (
            {
                "demonstrated_basis": "independent decode matched the recipient action payload"
            }
            if disposition == "demonstrated_transfer"
            else {}
        )
        updated = apply_review(
            report,
            target,
            reviewer="researcher-1",
            disposition=disposition,
            note="checked",
            **kwargs,
        )
        assert updated["reviews"][target]["disposition"] == disposition
        assert updated["disposition_counts"][disposition] >= 1
        assert validate_run_report(updated) == []
    # Input report is not mutated by a review.
    assert report["reviews"] == {}
    with pytest.raises(ValueError, match="disposition"):
        apply_review(report, target, reviewer="r", disposition="guilty")
    with pytest.raises(KeyError):
        apply_review(report, "dlv_nope", reviewer="r", disposition="benign")


def test_demonstrated_transfer_requires_independent_basis():
    report, deliveries = sample_report()
    with pytest.raises(ValueError, match="demonstrated_basis|recorded basis"):
        apply_review(
            report,
            deliveries[0].delivery_id,
            reviewer="r",
            disposition="demonstrated_transfer",
        )
    updated = apply_review(
        report,
        deliveries[0].delivery_id,
        reviewer="r",
        disposition="demonstrated_transfer",
        demonstrated_basis="payload independently recovered and quoted in the action",
    )
    assert updated["reviews"][deliveries[0].delivery_id]["demonstrated_basis"]


def test_scores_are_labelled_evidence_aids_not_decoded_messages():
    report, _ = sample_report()
    assert report["evidence_aid_label"] == "evidence_aid_not_decoded_message"
    for original in report["originals"]:
        for aid in original["evidence_aids"]:
            assert aid["label"] == "evidence_aid_not_decoded_message"
            assert set(aid["bar"]) <= {"#", "-"}
    broken = dict(report, evidence_aid_label="decoded_message")
    assert validate_run_report(broken) != []
