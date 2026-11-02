"""CL-55: cached values use the CLI's serialization and retain provenance."""

import argparse
import json

import pytest

from covertlens import demos
from covertlens.cli import _payload_json
from scripts import precompute


@pytest.mark.parametrize(
    "name",
    [
        "lsb",
        "dct",
        "metadata",
        "frozen",
        "geometric",
        "ablations",
        "robustness",
        "scorecard",
    ],
)
def test_cached_payload_is_exact_cli_payload(name, tmp_path):
    handler = getattr(
        demos, "cmd_" + precompute.REPORT_COMMANDS[name].replace("-", "_")
    )
    expected = handler(argparse.Namespace()).payload
    actual = precompute.build_report(name)
    path = tmp_path / f"{name}.json"
    precompute.write_json(path, actual)
    assert path.read_text() == _payload_json(expected)
    assert json.loads(path.read_text()) == json.loads(_payload_json(expected))


def test_latency_cache_keeps_measured_values_without_rounding(monkeypatch, tmp_path):
    # Use stable measurements so serialization equality isn't confused by
    # independently measured wall clocks. The production CLI handler is used.
    payload = {
        "schema": "covertlens.latency-reliability",
        "classes": [
            {
                "class": "large",
                "media": "jpeg",
                "p95_s": 1.2345,
                "meets_proposal": True,
                "statuses": {"parsed": 5},
            }
        ],
        "proposal": {"p95_at_most_s": 2},
        "concurrent": {"p95_s": 1.2345},
        "assessment": {
            "universal_claim": False,
            "limits_explicit_and_withholding": True,
            "concurrency_access_clean": True,
        },
        "limit_behavior": {
            "timeout_status": "timeout",
            "oversized_status": "oversized",
            "enforcement_served_bytes": False,
        },
    }
    monkeypatch.setattr(demos, "run_reliability_report", lambda: payload)
    actual = precompute.build_report("latency")
    precompute.write_json(tmp_path / "latency.json", actual)
    assert (tmp_path / "latency.json").read_text() == _payload_json(payload)


def test_precompute_has_provenance_and_commits_key_last(monkeypatch, tmp_path):
    monkeypatch.setattr(
        precompute, "build_report", lambda name: {"name": name, "value": 0.123456}
    )
    monkeypatch.setattr(precompute, "build_comparison", lambda: {"comparison": True})
    key = precompute.precompute(tmp_path)
    provenance = json.loads((tmp_path / "provenance.json").read_text())
    assert json.loads((tmp_path / "key.json").read_text()) == key
    for name in precompute.REPORT_COMMANDS:
        assert provenance[name]["command"] == precompute.REPORT_COMMANDS[name]
        assert provenance[name]["computed_at"]
        assert provenance[name]["library_version"] == key["library_version"]
        assert provenance[name]["config_version"] == key["config_version"]
        assert json.loads((tmp_path / f"{name}.json").read_text())["name"] == name


def test_http_serves_exact_cache_and_rejects_stale_versions(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import app.main as main

    monkeypatch.setenv("COVERTLENS_PRECOMPUTE", "off")
    monkeypatch.setattr(main, "CACHE_DIR", tmp_path)
    precompute.write_json(tmp_path / "key.json", main._cache_key())
    raw = '{"n": 0.123456, "sweep": []}'
    (tmp_path / "lsb.json").write_text(raw)
    with TestClient(main.app) as client:
        assert client.get("/api/benchmarks/lsb").text == raw
        assert client.get("/api/benchmarks/robustness").status_code == 202
        assert client.get("/api/benchmarks/unknown").status_code == 404
        precompute.write_json(tmp_path / "key.json", {"library_version": "old"})
        assert client.get("/api/benchmarks/lsb").status_code == 202
