"""CL-65: frozen-config selection, refreeze tooling, runbook artefacts."""

import json
from pathlib import Path

from covertlens.calibration import load_frozen_thresholds

ROOT = Path(__file__).resolve().parent.parent


def test_frozen_config_env_override(tmp_path, monkeypatch):
    source = json.loads((ROOT / "config" / "frozen-thresholds.json").read_text())
    source["frozen_config_version"] = "frozen-9.9.9"
    source["threshold_config"]["version"] = "frozen-9.9.9"
    alternate = tmp_path / "frozen-old.json"
    alternate.write_text(json.dumps(source))
    monkeypatch.setenv("COVERTLENS_FROZEN_CONFIG", str(alternate))
    config, _doc = load_frozen_thresholds()
    assert config.version == "frozen-9.9.9"


def test_frozen_config_default_unchanged(monkeypatch):
    monkeypatch.delenv("COVERTLENS_FROZEN_CONFIG", raising=False)
    config, _doc = load_frozen_thresholds()
    assert config.version.startswith("frozen-")


def test_refreeze_bump_and_files_exist():
    from scripts.refreeze import bump_version

    assert bump_version("frozen-1.1.0") == "frozen-1.1.1"
    assert (ROOT / "Makefile").read_text().count("refreeze") >= 1
    assert (ROOT / "scripts" / "refreeze.py").exists()


def test_campaign_log_and_runbook_close_the_gaps():
    log = (ROOT / "docs" / "campaign-log.md").read_text()
    assert "Template" in log and "Pin hash" in log
    runbook = (ROOT / "docs" / "operations-runbook.md").read_text()
    for needle in (
        "COVERTLENS_FROZEN_CONFIG",
        "make refreeze",
        "Regenerating published artefacts",
        "ParserLimits",
        "validate_handoff",
    ):
        assert needle in runbook, needle


def test_scorecard_records_pin_hash():
    card = json.loads((ROOT / "config" / "release-scorecard.json").read_text())
    assert str(card.get("pin_hash", "")).startswith("sha256:")
