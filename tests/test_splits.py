"""CL-10 acceptance tests: independent recovery scoring and leakage-safe splits.

AC1 each original and all derivatives remain in one split (DT-03)
AC2 held-out seeds, tasks, agent and encoder configurations are recorded (DT-03)
AC3 agents/detectors cannot access held-out labels; recovery checks pass (DT-04)
"""

import dataclasses
import json

import pytest

from covertlens.fixtures import build_dataset, build_pair
from covertlens.splits import (
    SPLITS,
    SplitPolicy,
    assign_splits,
    detector_manifest,
    group_key,
    held_out_record,
    scorer_ground_truth,
    validate_no_leakage,
    verify_recovery,
    write_split_dataset,
)


@pytest.fixture(scope="module")
def dataset():
    return build_dataset()


@pytest.fixture(scope="module")
def assignment(dataset):
    return assign_splits(dataset)


def test_each_original_and_derivatives_remain_in_one_split(dataset, assignment):
    by_group: dict[str, set[str]] = {}
    for fixture in dataset:
        by_group.setdefault(group_key(fixture), set()).add(assignment[fixture.fixture_id])
    assert all(len(splits) == 1 for splits in by_group.values())
    # A pair never straddles a split boundary.
    for pair_id in {f.pair_id for f in dataset if f.role in ("clean", "encoded")}:
        splits = {assignment[f.fixture_id] for f in dataset if f.pair_id == pair_id}
        assert len(splits) == 1


def test_assignment_is_complete_disjoint_and_deterministic(dataset, assignment):
    assert set(assignment) == {f.fixture_id for f in dataset}
    assert set(assignment.values()) <= set(SPLITS)
    assert assign_splits(dataset) == assignment
    other_seed = assign_splits(dataset, SplitPolicy(dataset_seed=7))
    assert set(other_seed) == set(assignment)  # still complete under another seed


def test_held_out_configurations_are_recorded(dataset, assignment):
    record = held_out_record(dataset, assignment)
    held = [f for f in dataset if assignment[f.fixture_id] == "held_out"]
    assert record["fixture_count"] == len(held) >= 1
    assert set(record["fixture_ids"]) == {f.fixture_id for f in held}
    assert set(record["cover_seeds"]) == {f.generator["seed"] for f in held}
    assert set(record["patterns"]) == {f.generator["pattern"] for f in held}
    assert {e["name"] for e in record["encoder_configs"]} <= {"lsb-png", "dct-jpeg"}
    assert record["policy"]["version"]
    json.dumps(record)


def test_detectors_cannot_access_held_out_labels(dataset, assignment):
    doc = detector_manifest(dataset, assignment)
    text = json.dumps(doc)
    assert "payload_hex" not in text
    held_ids = {f.fixture_id for f in dataset if assignment[f.fixture_id] == "held_out"}
    assert held_ids.isdisjoint({r["fixture_id"] for r in doc["fixtures"]})
    with pytest.raises(PermissionError):
        scorer_ground_truth(dataset, assignment, role="detector")
    truth = scorer_ground_truth(dataset, assignment, role="scorer")
    encoded_held = {
        f.fixture_id for f in dataset
        if assignment[f.fixture_id] == "held_out" and f.role == "encoded"
    }
    assert set(truth) == encoded_held


def test_independent_recovery_checks_pass(dataset):
    report = verify_recovery(dataset)
    encoded = [f for f in dataset if f.role == "encoded"]
    assert report.checked == len(encoded) == 6
    assert report.passed == report.checked
    assert report.failures == ()


def test_leakage_validator_catches_planted_leaks(dataset, assignment):
    assert validate_no_leakage(dataset, assignment) == []
    clean, encoded = build_pair("spatial_lsb", payload_bytes=8)
    broken = dict(assignment)
    # Reassign using dataset fixtures: split one pair across two splits.
    pair = [f for f in dataset if f.pair_id == clean.pair_id] or [
        f for f in dataset if f.role in ("clean", "encoded")
    ][:2]
    broken[pair[0].fixture_id] = "train"
    broken[pair[1].fixture_id] = "held_out"
    errors = validate_no_leakage(dataset, broken)
    assert any("split" in e for e in errors)


def test_identical_bytes_in_two_splits_are_leakage(dataset, assignment):
    source = dataset[0]
    clone = dataclasses.replace(source, fixture_id="clone-of-source", pair_id="clone-pair")
    fixtures = list(dataset) + [clone]
    broken = dict(assignment)
    broken[clone.fixture_id] = "held_out" if assignment[source.fixture_id] != "held_out" else "train"
    errors = validate_no_leakage(fixtures, broken)
    assert any("content_hash" in e for e in errors)


def test_write_split_dataset_separates_detector_and_scorer_outputs(tmp_path, dataset, assignment):
    out = write_split_dataset(tmp_path / "split", dataset, assignment)
    detector_doc = json.loads((out / "detector" / "manifest.json").read_text())
    scorer_doc = json.loads((out / "scorer" / "ground-truth.json").read_text())
    held_ids = {f.fixture_id for f in dataset if assignment[f.fixture_id] == "held_out"}
    assert held_ids.isdisjoint({r["fixture_id"] for r in detector_doc["fixtures"]})
    assert "payload_hex" not in json.dumps(detector_doc)
    assert set(scorer_doc) <= {f.fixture_id for f in dataset}
    assert (out / "assignments.json").exists()
