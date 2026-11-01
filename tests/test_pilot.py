import pytest

from covertlens.pilot import run_pilot, validate_pilot


@pytest.fixture(scope="module")
def pilot():
    return run_pilot(
        adjudications={
            "uns-1": {
                "disposition": "suspected",
                "note": "strong DCT evidence; no independent basis yet",
            },
            "uns-5": {"disposition": "benign", "note": "clean control pattern"},
        }
    )


def test_seeded_runs_cover_attempts_and_controls_in_both_modes(pilot):
    assert validate_pilot(pilot) == []
    seeded = pilot["seeded"]
    assert seeded["attempts"] > 0
    assert seeded["clean_controls"] > 0
    # Log/flag mode: unfrozen config, everything logs and delivers.
    assert seeded["log_flag"]["enforceable"] is False
    assert seeded["log_flag"]["delivered"] == seeded["traces"]
    # Enforcement mode withholds the strong seeded attempts.
    assert seeded["enforcement"]["withheld"] > 0
    assert pilot["pin_hash"].startswith("sha256:")


def test_disagreements_are_named_not_hidden(pilot):
    disagreements = pilot["disagreements"]
    # Low-band seeded attempts that enforcement still delivers are
    # listed individually (missed attempts are a finding, not a pass).
    assert isinstance(disagreements["seeded_attempts_delivered_in_enforcement"], list)
    assert isinstance(disagreements["seeded_clean_controls_withheld"], list)
    assert disagreements["verdict_changes_between_modes"] > 0


def test_unseeded_uncertain_cases_remain_unresolved(pilot):
    unseeded = pilot["unseeded"]
    assert unseeded["disposition_counts"]["suspected"] == 1
    assert unseeded["disposition_counts"]["benign"] == 1
    # The three unreviewed traces stay unresolved by construction.
    assert unseeded["disposition_counts"]["unresolved"] == 3
    assert len(unseeded["unresolved_delivery_ids"]) == 3
    assert pilot["review_volume"]["unseeded_unresolved"] == 3


def test_demonstrated_transfer_needs_independent_basis():
    with pytest.raises(ValueError, match="demonstrated_transfer"):
        run_pilot(
            adjudications={
                "uns-1": {"disposition": "demonstrated_transfer"},
            }
        )


def test_repeated_weak_signals_reported(pilot):
    signals = pilot["repeated_weak_signals"]
    assert isinstance(signals, list)
    for entry in signals:
        assert entry["count"] >= 2
        assert entry["trace_ids"]
