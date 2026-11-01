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
import json
import os
from pathlib import Path
from typing import Any

import covertlens


def cache_key() -> dict[str, str]:
    return {
        "library_version": covertlens.__version__,
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
    }


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
            f for f in dataset
            if f.role == role and f.subfamily == "height_position")
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
    from covertlens.geo_benchmark import run_geo_benchmark
    from covertlens.scorecard import load_scorecard

    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key()
    (cache_dir / "geometric.json").write_text(
        json.dumps(run_geo_benchmark(), sort_keys=True))
    (cache_dir / "scorecard.json").write_text(
        json.dumps(load_scorecard(), sort_keys=True))
    (cache_dir / "comparison.json").write_text(
        json.dumps(build_comparison(), sort_keys=True))
    (cache_dir / "key.json").write_text(json.dumps(key, sort_keys=True))
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
