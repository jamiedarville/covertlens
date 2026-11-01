import pytest

from covertlens.ablations import run_ablations, validate_ablations


@pytest.fixture(scope="module")
def report():
    return run_ablations()


def test_three_arms_reported_with_confusion(report):
    assert validate_ablations(report) == []
    for arm in ("image_only", "context_only", "combined"):
        block = report["arms"][arm]
        assert block["auc"] is not None
        assert block["tp"] + block["fn"] == report["prevention"]["attempts"]["trials"]
        assert (
            block["fp"] + block["tn"]
            == report["prevention"]["clean_controls"]["trials"]
        )


def test_image_only_beats_context_only(report):
    # Artifact evidence carries the signal; repetition pressure
    # alone is the weak arm (that ordering is the ablation finding).
    assert report["arms"]["image_only"]["auc"] > report["arms"]["context_only"]["auc"]
    assert report["arms"]["combined"]["auc"] >= report["arms"]["context_only"]["auc"]


def test_blocked_artifacts_never_count_as_transfer(report):
    prevention = report["prevention"]
    assert prevention["attempts"]["blocked_counted_as_transfer"] == 0
    withheld = prevention["by_condition"]["withheld"]
    assert withheld["demonstrated_transfers"] == 0
    assert withheld["recovery_recovered"] == 0
    assert withheld["recovery_not_observed"] == withheld["trials"]
    # Observed transfers only ever come from delivered attempts.
    assert (
        prevention["attempts"]["observed_successful_transfers"]
        == prevention["by_condition"]["delivered"]["demonstrated_transfers"]
    )


def test_recovery_and_legitimate_success_are_separate(report):
    prevention = report["prevention"]
    controls = prevention["clean_controls"]
    # Clean controls have no payload to recover; their legitimate
    # task success is delivery of a usable image, reported apart
    # from attempt recovery.
    assert controls["legitimate_task_successes"] == controls["delivered"]
    delivered = prevention["by_condition"]["delivered"]
    assert delivered["recovery_recovered"] <= delivered["trials"]
    assert prevention["replay_cross_check"]["withheld"]["demonstrated_transfers"] == 0
