"""Build the Python half of the static Analyze page (CL-66).

Writes, into the Vite public dir of the static build:

- `covertlens-py.zip` — the `covertlens` package, the shipped
  `config/` files and `app/analysis_worker.py` (the code behind
  `POST /api/analyze`), unpacked by Pyodide at start. Deterministic:
  sorted entries, fixed timestamps.
- `examples/` — a few built-in fixtures (PNG) plus `index.json`.

and, outside the site, the CPython reference output of
`analyze_bytes` for every example, so `npm run test:pyodide` can check
that Pyodide produces the same analysis.

Standard library only; run with the repository on `PYTHONPATH`:
`python3 scripts/build_static_bundle.py --out public-static --expected .static-build/expected`.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def _bundle_files() -> list[Path]:
    files = [
        p
        for p in sorted((ROOT / "covertlens").rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".txt")
    ]
    files += sorted((ROOT / "config").glob("*.json"))
    files += [ROOT / "app" / "__init__.py", ROOT / "app" / "analysis_worker.py"]
    return files


def write_bundle(out: Path) -> Path:
    target = out / "covertlens-py.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _bundle_files():
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), _FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return target


def _examples() -> list[tuple[str, str, object]]:
    from covertlens.fixtures import build_pair
    from covertlens.geo_benchmark import build_structured_pair
    from covertlens.geometric_fixtures import build_geo_pair
    from covertlens.metadata_fixtures import build_metadata_pair

    geo_clean, geo_encoded = build_geo_pair("height_position")
    _c, colour = build_geo_pair("colour_code")
    _c2, structured = build_structured_pair("height_position", 0)
    _c3, lsb = build_pair("spatial_lsb", payload_bytes=192)
    _c4, meta = build_metadata_pair("png", payload_bytes=64)
    return [
        ("Clean bar scene (height grid)", "clean", geo_clean),
        ("Encoded bar heights (random symbols)", "encoded", geo_encoded),
        ("Encoded bar heights (structured word)", "encoded", structured),
        ("Encoded colour codes", "encoded", colour),
        ("Spatial LSB payload (high band)", "encoded", lsb),
        ("PNG metadata payload", "encoded", meta),
    ]


def write_examples(out: Path, expected: Path | None) -> list[dict[str, object]]:
    sys.path.insert(0, str(ROOT))
    from app.analysis_worker import analyze_bytes

    examples_dir = out / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    if expected is not None:
        expected.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, object]] = []
    for label, kind, fixture in _examples():
        data: bytes = fixture.data  # type: ignore[attr-defined]
        name = f"{fixture.fixture_id}.png"  # type: ignore[attr-defined]
        (examples_dir / name).write_bytes(data)
        index.append(
            {
                "fixture_id": fixture.fixture_id,  # type: ignore[attr-defined]
                "kind": kind,
                "subfamily": getattr(fixture, "subfamily", None),
                "content_hash": fixture.content_hash,  # type: ignore[attr-defined]
                "media_type": "image/png",
                "file": name,
                "label": label,
            }
        )
        if expected is not None:
            reference = analyze_bytes(data, 2_000_000)
            (expected / f"{name}.json").write_text(
                json.dumps(reference, sort_keys=True) + "\n"
            )
    (examples_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected", type=Path, default=None)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    bundle = write_bundle(args.out)
    index = write_examples(args.out, args.expected)
    print(
        f"static bundle: {bundle.name} ({bundle.stat().st_size} bytes), "
        f"{len(index)} examples"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
