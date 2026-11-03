"""Re-freeze thresholds and regenerate the scorecard (CL-65).

The one supported way to change enforcement points:

1. Recalibrate on development data only (CL-27; held-out labels
   raise, C-07) via `calibration.calibrate_thresholds`.
2. Bump the frozen config version (`frozen-1.1.0` -> `frozen-1.1.1`,
   or an explicit `--version`) — a frozen file is never edited in
   place at the same version.
3. Write `config/frozen-thresholds.json`, preserving operator-owned
   top-level blocks (`owners`, `coverage`) from the previous freeze.
4. Regenerate `config/release-scorecard.json` from the new freeze so
   the published scorecard (and its recorded pin hash) matches the
   code that tests rebuild.

Run it through `make refreeze`. Rollback is the reverse: point
`COVERTLENS_FROZEN_CONFIG` at the previous freeze file (kept in git)
and announce it in `docs/campaign-log.md`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FROZEN_PATH = ROOT / "config" / "frozen-thresholds.json"
SCORECARD_PATH = ROOT / "config" / "release-scorecard.json"


def bump_version(version: str) -> str:
    match = re.fullmatch(r"(frozen-\d+\.\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"cannot bump frozen config version: {version!r}")
    return f"{match.group(1)}.{int(match.group(2)) + 1}"


def refreeze(
    frozen_path: Path = FROZEN_PATH,
    scorecard_path: Path = SCORECARD_PATH,
    *,
    version: str | None = None,
) -> dict[str, str]:
    from covertlens.calibration import (
        calibrate_thresholds,
        development_calibration_data,
    )
    from covertlens.scorecard import build_scorecard

    previous = json.loads(frozen_path.read_text())
    old_version = previous["frozen_config_version"]
    # An explicit version skips labels already used elsewhere (CL-68
    # skips frozen-1.2.0, taken by an unmerged branch). It must be new.
    new_version = version or bump_version(old_version)
    if not re.fullmatch(r"frozen-\d+\.\d+\.\d+", new_version):
        raise ValueError(f"not a frozen config version: {new_version!r}")
    if new_version == old_version:
        raise ValueError("a re-freeze needs a new version (never edit in place)")

    fixtures, assignments = development_calibration_data()
    report = calibrate_thresholds(fixtures, assignments)

    # The calibration report is the new freeze; carry over the
    # operator-owned blocks it does not generate.
    for key in ("owners", "coverage"):
        if key in previous:
            report[key] = previous[key]
    report["frozen_config_version"] = new_version
    report["threshold_config"]["version"] = new_version

    frozen_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    # The scorecard must be rebuilt *after* the new freeze is on
    # disk: it loads frozen thresholds and records the pin hash.
    # Point the loader at the file just written so a custom path
    # (or a stale env override) cannot rebuild against the old one.
    previous_env = os.environ.get("COVERTLENS_FROZEN_CONFIG")
    os.environ["COVERTLENS_FROZEN_CONFIG"] = str(frozen_path)
    try:
        card = build_scorecard()
    finally:
        if previous_env is None:
            os.environ.pop("COVERTLENS_FROZEN_CONFIG", None)
        else:
            os.environ["COVERTLENS_FROZEN_CONFIG"] = previous_env
    scorecard_path.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    return {"previous": old_version, "new": new_version, "pin_hash": card["pin_hash"]}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        help="explicit new frozen config version (default: bump the patch)",
    )
    args = parser.parse_args(argv)
    result = refreeze(version=args.version)
    print(
        f"refroze {result['previous']} -> {result['new']}; "
        f"scorecard pin_hash {result['pin_hash']}"
    )
    print("Next: run the test suite, then log the change in docs/campaign-log.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
