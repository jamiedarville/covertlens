"""CL-50 acceptance: demo JSON outputs validate against schemas/.

Every `*-demo` whose payload has a shipped JSON Schema is run
through the real CLI (`--json`) and validated with jsonschema.
Demos without a matching schema (list-events, list-routes,
runtime-demo, geo-fixtures-demo, sequence-demo) are enumerated
in `NO_SCHEMA_DEMOS` so the gap is explicit, and a guard test
fails if a future demo is added without being classified here.
The latency report is validated in a `slow`-marked test: its
generation measures wall-clock classes.
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("referencing")

from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

from covertlens.cli import COMMANDS, main  # noqa: E402

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _registry() -> Registry:
    resources = []
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resources.append((path.name, Resource.from_contents(doc)))
        if doc.get("$id"):
            resources.append((doc["$id"], Resource.from_contents(doc)))
    registry = Registry()
    for uri, resource in resources:
        registry = registry.with_resource(uri, resource)
    return registry


def _validator(schema_file: str) -> Draft202012Validator:
    doc = json.loads((SCHEMAS_DIR / schema_file).read_text(encoding="utf-8"))
    return Draft202012Validator(doc, registry=_registry())


def _run_json(capsys, argv: list[str]):
    exit_code = main([*argv, "--json"])
    assert exit_code == 0, f"{argv} exited {exit_code}"
    return json.loads(capsys.readouterr().out)


def _validate(schema_file: str, instances: list) -> None:
    validator = _validator(schema_file)
    assert instances, f"no instances extracted for {schema_file}"
    for instance in instances:
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
        assert not errors, (
            f"{schema_file}: {[f'{list(e.path)}: {e.message}' for e in errors[:5]]}"
        )


# demo -> (schema file, payload -> instances). Lambdas take the
# --json payload exactly as the CLI emits it.
CASES = {
    "validate-manifest": ("allowed-channel-manifest.schema.json", lambda p: [p]),
    "validate-runtime": ("runtime-policy.schema.json", lambda p: [p]),
    "store-demo": ("artifact-store.schema.json", lambda p: [p["v1"], p["v2"]]),
    "gate-demo": ("delivery-record.schema.json", lambda p: [p["delivery"]]),
    "parse-demo": ("analysis-result.schema.json", lambda p: p),
    "lsb-demo": ("analysis-result.schema.json", lambda p: p),
    "benchmark-lsb": ("lsb-benchmark.schema.json", lambda p: [p]),
    "dct-demo": ("analysis-result.schema.json", lambda p: p),
    "benchmark-dct": ("dct-benchmark.schema.json", lambda p: [p]),
    "trace-demo": ("trace-join.schema.json", lambda p: [p]),
    "metadata-demo": ("metadata-benchmark.schema.json", lambda p: [p["benchmark"]]),
    "report-demo": ("run-report.schema.json", lambda p: [p]),
    "pinning-demo": ("pin.schema.json", lambda p: [p["pin"]]),
    "calibrate-demo": ("calibration.schema.json", lambda p: [p]),
    "frozen-demo": ("frozen-benchmark.schema.json", lambda p: [p]),
    "pilot-demo": ("seeded-pilot.schema.json", lambda p: [p]),
    "ablation-demo": ("ablations-prevention.schema.json", lambda p: [p]),
    "route-audit-demo": ("route-trace-audit.schema.json", lambda p: [p]),
    "export-demo": ("review-export.schema.json", lambda p: [p["package"]]),
    "robustness-demo": ("robustness-evaluation.schema.json", lambda p: [p]),
    "scorecard-demo": ("release-scorecard.schema.json", lambda p: [p]),
    "handoff-demo": ("ops-handoff.schema.json", lambda p: [p]),
    "segmentation-demo": ("segmentation.schema.json", lambda p: list(p.values())),
    "geometric-demo": (
        "geometric-finding.schema.json",
        lambda p: [f for f in p["findings"].values() if f is not None],
    ),
    "vector-demo": ("vector-binding.schema.json", lambda p: [p["bound"]]),
    "geo-benchmark-demo": ("geo-benchmark.schema.json", lambda p: [p]),
    "replay-demo": ("replay-experiment.schema.json", lambda p: [p]),
    "verdict-demo": (
        "verdict-decision.schema.json",
        lambda p: [r["decision"] for r in p],
    ),
}

# Commands whose payload has no shipped schema (see docstring),
# plus the two directory-writing commands handled separately
# below and the wall-clock latency demo (slow test below).
NO_SCHEMA_DEMOS = {
    "list-events",
    "list-routes",
    "runtime-demo",
    "geo-fixtures-demo",
    "sequence-demo",
}
SEPARATE_DEMOS = {"build-fixtures", "split-dataset", "latency-demo"}


def test_every_demo_is_classified():
    registered = {name for name, *_ in COMMANDS}
    classified = set(CASES) | NO_SCHEMA_DEMOS | SEPARATE_DEMOS
    assert registered == classified, (
        f"unclassified: {sorted(registered - classified)}, "
        f"stale: {sorted(classified - registered)}"
    )


def test_every_schema_file_is_valid():
    files = sorted(SCHEMAS_DIR.glob("*.json"))
    assert files
    for path in files:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("command", sorted(CASES))
def test_demo_output_matches_schema(command, capsys):
    schema_file, extract = CASES[command]
    payload = _run_json(capsys, [command])
    _validate(schema_file, extract(payload))


def test_build_fixtures_manifest_matches_schema(capsys, tmp_path):
    payload = _run_json(capsys, ["build-fixtures", str(tmp_path / "fx")])
    _validate("fixture-manifest.schema.json", [payload])


def test_split_dataset_manifest_matches_schema(capsys, tmp_path):
    payload = _run_json(capsys, ["split-dataset", str(tmp_path / "split")])
    _validate("split-manifest.schema.json", [payload])


@pytest.mark.slow
def test_latency_demo_matches_schema(capsys):
    payload = _run_json(capsys, ["latency-demo"])
    _validate("latency-reliability.schema.json", [payload])
