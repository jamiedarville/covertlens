"""Precompute benchmark/report caches for the web service (CL-47).

Runs every benchmark and report once and writes JSON caches under
the data directory, keyed by library version and git SHA. The web
service runs this in a background thread at first start (health
answers immediately); it can also be run directly:

    python scripts/precompute.py [--data-dir /data]
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


def precompute(cache_dir: Path) -> dict[str, Any]:
    """Write geometric benchmark + scorecard caches. Returns the key."""
    from covertlens.geo_benchmark import run_geo_benchmark
    from covertlens.scorecard import load_scorecard

    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key()
    (cache_dir / "geometric.json").write_text(
        json.dumps(run_geo_benchmark(), sort_keys=True))
    (cache_dir / "scorecard.json").write_text(
        json.dumps(load_scorecard(), sort_keys=True))
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
