"""CL-21 acceptance tests: delivered-vs-withheld replay (DT-05).

AC1 matched/randomized trials pin conditions and record stochastic variation
AC2 independent recovery and legitimate task outcomes are collected
AC3 blocked runs label parse not observed and never claim demonstrated transfer
"""

import json

import pytest

from covertlens.fixtures import build_dataset, build_pair
from covertlens.replay import ReplayConfig, run_replay, validate_replay


@pytest.fixture(scope="module")
def dataset():
    return build_dataset()


def test_matched_trials_pin_conditions(dataset):
    config = ReplayConfig(seed=7, repetitions=2, detector_versions=["d@1"],
                          verdict_config_version="cfg-1")
    report = run_replay(dataset, config=config)
    assert validate_replay(report) == []
    encoded = [f for f in dataset if f.role == "encoded"]
    assert len(report["trials"]) == len(encoded) * 2 * 2
    assert report["config"]["seed"] == 7
    assert report["conditions_pinned"]["fixture_hashes"] == {
        f.fixture_id: f.content_hash for f in encoded}
    # Every fixture appears in both arms (matched on the same artifact).
    by_fixture = {}
    for trial in report["trials"]:
        by_fixture.setdefault(trial["fixture_id"], set()).add(trial["condition"])
    assert all(v == {"delivered", "withheld"} for v in by_fixture.values())
    seeds = [t["trial_seed"] for t in report["trials"]]
    assert len(set(seeds)) == len(seeds)  # per-trial stochastic variation pinned
    json.dumps(report)


def test_randomization_is_seeded_and_reproducible(dataset):
    first = run_replay(dataset, config=ReplayConfig(seed=42))
    second = run_replay(dataset, config=ReplayConfig(seed=42))
    third = run_replay(dataset, config=ReplayConfig(seed=43))
    order = lambda r: [t["trial_id"] for t in r["trials"]]
    assert order(first) == order(second)
    assert order(first) != order(third)
    with pytest.raises(ValueError):
        ReplayConfig(repetitions=0)


def test_recovery_and_legitimate_outcomes_are_separate(dataset):
    # Legitimate task succeeds via the declared text channel even when
    # the image is withheld; recovery only happens when delivered.
    report = run_replay(
        dataset, config=ReplayConfig(seed=3),
        task_outcome=lambda fixture, data, seed: True)
    delivered = report["by_condition"]["delivered"]
    withheld = report["by_condition"]["withheld"]
    assert delivered["recovery_rate"] == 1.0  # payloads verify when delivered
    assert withheld["recovery_rate"] is None
    assert delivered["legitimate_task_success_rate"] == 1.0
    assert withheld["legitimate_task_success_rate"] == 1.0  # separate measure
    assert report["by_payload_band"]["high"]["delivered"]["recovered"] == 2


def test_withheld_trials_never_claim_transfer(dataset):
    report = run_replay(dataset, config=ReplayConfig(seed=5))
    withheld = [t for t in report["trials"] if t["condition"] == "withheld"]
    assert withheld
    for trial in withheld:
        assert trial["parse_status"] == "not_observed"
        assert trial["recovery"] == "not_observed"
        assert trial["demonstrated_transfer"] is False
    assert report["by_condition"]["withheld"]["demonstrated_transfers"] == 0
    assert report["by_condition"]["withheld"]["parse_not_observed"] == len(withheld)
    # Even a recover function that would succeed cannot create transfer.
    rigged = run_replay(
        dataset, config=ReplayConfig(seed=5), recover=lambda fixture: True)
    assert rigged["by_condition"]["withheld"]["demonstrated_transfers"] == 0
    assert rigged["by_condition"]["delivered"]["demonstrated_transfers"] == 6


def test_single_pair_replay_end_to_end():
    _, encoded = build_pair("jpeg_dct", width=64, height=48, payload_bytes=64)
    report = run_replay([encoded], config=ReplayConfig(seed=1))
    assert validate_replay(report) == []
    assert len(report["trials"]) == 2
    delivered = next(t for t in report["trials"] if t["condition"] == "delivered")
    assert delivered["recovery"] == "recovered"
    assert delivered["demonstrated_transfer"] is True
    assert report["equated_with_collusion"] is False
