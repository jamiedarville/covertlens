import pytest

from covertlens.scorecard import build_scorecard, load_scorecard, validate_scorecard


@pytest.fixture(scope="module")
def scorecard():
    return build_scorecard()


def test_scorecard_publishes_all_sections_with_sources(scorecard):
    assert validate_scorecard(scorecard) == []
    for section in scorecard["sections"].values():
        assert section["source_schema"].startswith("covertlens.")
        assert section["source_doc"].startswith("docs/contracts/")
    detection = scorecard["sections"]["detection_frozen_benchmark"]
    # LSB, DCT and metadata results are published with precision,
    # recall and the clean-run failure rate.
    assert set(detection["per_family"]) == {"spatial_lsb", "jpeg_dct", "metadata"}
    for family in detection["per_family"].values():
        assert family["recall_at_triage"] is not None
        assert family["enforcement_precision"] is not None
    assert detection["clean_runs"] >= 300
    assert detection["clean_run_failure_rate"] <= 0.01


def test_gate_latency_sequence_and_prevention_included(scorecard):
    sections = scorecard["sections"]
    assert sections["gate_and_trace"]["routes_partial"] == ["R-06"]
    assert sections["gate_and_trace"]["trace_links_all_explained"] is True
    latency = sections["latency_reliability"]
    assert latency["limits_explicit_and_withholding"] is True
    assert latency["concurrency_access_clean"] is True
    assert latency["classes_missed"], "latency misses must be published"
    sequence = sections["sequence_value"]
    assert sequence["image_only_auc"] > sequence["context_only_auc"]
    assert sections["prevention"]["attempts"]["blocked_counted_as_transfer"] == 0
    assert sections["robustness_bounds"]["separate_from_frozen_benchmark"] is True


def test_owner_decision_limitations_and_revisions_recorded(scorecard):
    decision = scorecard["decision"]
    assert decision["value"] == "release_with_limitations"
    assert decision["decision_owner"]
    assert len(decision["limitations"]) >= 5
    assert len(decision["target_revisions"]) >= 3
    for revision in decision["target_revisions"]:
        assert revision["target"] and revision["revision"] and revision["reason"]


def test_published_artifact_matches_built_scorecard(scorecard):
    published = load_scorecard()
    # Latency timings are machine-volatile; every other figure must
    # match the published artifact exactly.
    for card in (published, scorecard):
        latency = card["sections"]["latency_reliability"]
        latency.pop("p95_by_class")
        latency.pop("concurrent_p95_s")
    assert published == scorecard
