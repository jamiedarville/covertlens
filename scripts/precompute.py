"""Precompute benchmark/report caches for the web service (CL-47).

Runs every benchmark and report once and writes JSON caches under
the data directory, keyed by library version and git SHA. The web
service runs this in a background thread at first start (health
answers immediately); it can also be run directly:

    python scripts/precompute.py [--data-dir /data]

CL-48 adds ``comparison.json``: the landing page's precomputed
two-skyline comparison (first clean and first encoded
height_position fixtures, each with its full ``/api/analyze``
payload from the analysis worker, reviewer fields already
stripped), served by ``GET /api/comparison``.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import covertlens

REPORT_COMMANDS = {
    "lsb": "benchmark-lsb",
    "dct": "benchmark-dct",
    "metadata": "metadata-demo",
    "frozen": "frozen-demo",
    "geometric": "geo-benchmark-demo",
    "ablations": "ablation-demo",
    "latency": "latency-demo",
    "robustness": "robustness-demo",
    "scorecard": "scorecard-demo",
}


def cache_key() -> dict[str, str]:
    from covertlens.acceleration import numpy_backend
    from covertlens.calibration import load_frozen_thresholds
    from covertlens.parsing import PARSER_VERSION

    backend = numpy_backend()
    return {
        "library_version": covertlens.__version__,
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
        "config_version": load_frozen_thresholds()[0].version,
        "parser_version": PARSER_VERSION,
        "fast_path": "numpy" if backend is not None else "python",
        "numpy_version": backend.__version__ if backend is not None else "absent",
        "cache_version": "2",
    }


def write_json(path: Path, body: Any) -> None:
    """Readers see either a complete old document or a complete new one."""
    from covertlens.cli import payload_json as _payload_json

    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        f.write(_payload_json(body))
        temporary = Path(f.name)
    temporary.replace(path)


def build_report(name: str) -> Any:
    """Use the actual CLI handlers, preserving their complete payloads."""
    from covertlens import demos

    command = REPORT_COMMANDS[name]
    handler = getattr(demos, "cmd_" + command.replace("-", "_"))
    result = handler(argparse.Namespace())
    if result.exit_code:
        raise ValueError(f"{command} failed validation: {result.exit_code}")
    return result.payload


def _worker_analyze():
    """Import the web analysis worker, direct-script runs included."""
    try:
        from app.analysis_worker import analyze_bytes
    except ImportError:  # `python scripts/precompute.py` outside the app
        import sys

        root = str(Path(__file__).resolve().parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from app.analysis_worker import analyze_bytes
    return analyze_bytes


def build_comparison() -> dict[str, Any]:
    """Precomputed clean-vs-encoded skyline pair for the landing page."""
    from covertlens.geometric_fixtures import build_geo_dataset

    analyze = _worker_analyze()
    dataset = build_geo_dataset()
    sides: dict[str, Any] = {}
    for label, role in (("clean", "clean"), ("encoded", "encoded")):
        fixture = next(
            f for f in dataset if f.role == role and f.subfamily == "height_position"
        )
        sides[label] = {
            "fixture_id": fixture.fixture_id,
            "content_hash": fixture.content_hash,
            "payload": analyze(fixture.data),
        }
    return {
        "schema": "covertlens.skyline-comparison",
        "schema_version": 1,
        "subfamily": "height_position",
        **sides,
    }


def precompute(cache_dir: Path) -> dict[str, Any]:
    """Write benchmark, scorecard and comparison caches. Returns the key."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key()
    provenance = {}
    write_json(cache_dir / "comparison.json", build_comparison())
    for name, command in REPORT_COMMANDS.items():
        report = build_report(name)
        write_json(cache_dir / f"{name}.json", report)
        provenance[name] = {
            **key,
            "command": command,
            "computed_at": datetime.now(UTC).isoformat(),
            "source": "published scorecard" if name == "scorecard" else "CLI handler",
        }
    write_json(cache_dir / "provenance.json", provenance)
    write_json(cache_dir / "key.json", key)
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("COVERTLENS_DATA_DIR", "/data"),
        help="data directory; caches are written under <data-dir>/cache",
    )
    args = parser.parse_args(argv)
    key = precompute(Path(args.data_dir) / "cache")
    print(f"precomputed caches for {key} under {args.data_dir}/cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
