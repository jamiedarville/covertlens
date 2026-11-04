"""CL-63: shared helpers consolidated, no private cross-module imports."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from covertlens._png import load_png, save_png
from covertlens._stats import roc_auc, score_summary, wilson
from covertlens._validation import canonical_hash, make_need, now_iso
from covertlens.events import Event, EventType
from covertlens.metadata import MetadataConfig, classify_entries
from covertlens.replay import ReplayConfig
from covertlens.sequence import SequenceConfig, context_only_score

ROOT = Path(__file__).resolve().parent.parent


def _modules():
    for package in ("covertlens", "app", "scripts"):
        for path in sorted((ROOT / package).glob("*.py")):
            yield path, ast.parse(path.read_text(encoding="utf-8"))


def test_no_module_imports_a_private_name_from_another_module():
    # Relative and absolute imports, across the package, the app and
    # the scripts (CL-78 widened this from relative-only).
    offenders = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            internal = node.level > 0 or (node.module or "").startswith(
                ("covertlens", "app", "scripts")
            )
            if not internal:
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    offenders.append(f"{path.name}:{node.lineno} imports {alias.name}")
    assert offenders == []


def test_clock_and_need_helpers_are_defined_once():
    defined = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                "_now",
                "now_iso",
                "need",
            ):
                defined.append(f"{path.name}:{node.name}")
    assert sorted(defined) == ["_validation.py:need", "_validation.py:now_iso"]


def test_stats_helpers_match_known_values():
    assert wilson(5, 10)["estimate"] == 0.5
    assert roc_auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert score_summary([1.0, 2.0])["mean"] == 1.5


def test_png_helpers_round_trip():
    data = save_png(bytes((10, 20, 30)) * 4, 2, 2)
    pixels, width, height = load_png(data)
    assert (width, height) == (2, 2)
    assert pixels == bytes((10, 20, 30)) * 4


def test_validation_helpers():
    errors: list[str] = []
    need = make_need(errors)
    need(False, "boom")
    need(True, "fine")
    assert errors == ["boom"]
    assert now_iso().endswith("+00:00") or "T" in now_iso()
    assert canonical_hash({"b": 1, "a": 2}) == canonical_hash({"a": 2, "b": 1})


def test_event_is_frozen():
    event = Event(EventType.RUN_FINALIZED, "run_1", 0, now_iso())
    with pytest.raises(FrozenInstanceError):
        event.seq = 9  # type: ignore[misc]


def test_moved_constants_live_in_versioned_configs():
    assert MetadataConfig().to_dict()["payload_size_cap_bytes"] == 512
    assert SequenceConfig().to_dict()["delivered_weight"] == 0.12
    assert ReplayConfig().to_dict()["seed_stride"] == 7919
    # Behaviour unchanged: context pressure uses the same weights.
    assert context_only_score({"prior_delivered": 1, "prior_actions": 1}) == 0.2
    score, _ = classify_entries(
        [{"keyword": "CovertLensPayload", "value_bytes": 512, "source": "png"}]
    )
    assert score == pytest.approx(0.9 + 512 / 5120.0)


def test_latency_percentile_ignores_float_noise():
    from covertlens.latency import percentile

    values = [float(i) for i in range(1, 101)]
    # 0.07 * 100 is 7.000000000000001; the nearest rank is still 7.
    assert percentile(values, 0.07) == 7.0
    assert percentile(values, 0.95) == 95.0
