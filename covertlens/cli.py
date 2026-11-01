"""Command-line entry point: checks and demos for CovertLens.

Split in CL-50: this module owns argument parsing and dispatch
only (handlers live in `covertlens.demos`, one function per
command over the same library calls the web service makes).

Usage:
    python -m covertlens [--json] [--out PATH] <command> [args]
    python -m covertlens <command> [--json] [--out PATH] [args]

With no command, `validate-manifest` runs (the historical
default). `--json` prints the command's full JSON payload
instead of its human summary; `--out PATH` also writes that
payload to a file. Exit codes: 0 success, 1 validation or
benchmark failure, 2 usage or output errors. Run with `--help`
for the command list.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from . import demos
from .demos import DemoResult

Handler = Callable[[argparse.Namespace], DemoResult]

# (name, help); the handler is demos.cmd_<name, dashes as underscores>.
_COMMAND_HELP: list[tuple[str, str]] = [
    ("validate-manifest", "validate manifest + route inventory"),
    ("list-events", "list harness event families"),
    ("list-routes", "list the artifact route inventory"),
    ("store-demo", "immutable originals store round trip (CL-8)"),
    ("build-fixtures", "build synthetic paired fixtures (CL-9)"),
    ("split-dataset", "leakage-safe splits + scoring (CL-10)"),
    ("validate-runtime", "validate runtime evidence policy (CL-11)"),
    ("runtime-demo", "permissioned evidence read demo (CL-11)"),
    ("gate-demo", "interception + pending delivery demo (CL-12)"),
    ("parse-demo", "bounded parsing demo (CL-13)"),
    ("lsb-demo", "LSB scoring demo (CL-14)"),
    ("benchmark-lsb", "threshold-free LSB benchmark (CL-14)"),
    ("dct-demo", "DCT scoring demo (CL-15)"),
    ("benchmark-dct", "paired DCT benchmark by band (CL-15)"),
    ("trace-demo", "trace join demo (CL-16)"),
    ("verdict-demo", "verdict ladder demo (CL-17)"),
    ("replay-demo", "delivered-vs-withheld replay (CL-21)"),
    ("metadata-demo", "metadata + integrated pipeline (CL-23)"),
    ("sequence-demo", "sequence benchmark demo (CL-24)"),
    ("report-demo", "researcher report demo (CL-25)"),
    ("pinning-demo", "pin + reproducibility demo (CL-26)"),
    ("calibrate-demo", "frozen threshold points (CL-27)"),
    ("frozen-demo", "frozen benchmark + clean stability (CL-28)"),
    ("latency-demo", "latency + reliability report (CL-29)"),
    ("pilot-demo", "seeded pilot + adjudication (CL-30)"),
    ("ablation-demo", "ablations + prevention (CL-31)"),
    ("route-audit-demo", "route + trace coverage audit (CL-32)"),
    ("export-demo", "review export + access checks (CL-33)"),
    ("robustness-demo", "adaptive/unseen-config eval (CL-34)"),
    ("scorecard-demo", "release scorecard + decision (CL-35)"),
    ("handoff-demo", "ops/rollback/handoff checks (CL-36)"),
    ("geo-fixtures-demo", "geometric paired fixtures (CL-38)"),
    ("segmentation-demo", "segmentation + attributes (CL-39)"),
    ("geometric-demo", "quantization + structure tests (CL-40)"),
    ("vector-demo", "vector source verdict binding (CL-41)"),
    ("geo-benchmark-demo", "geometric benchmark (CL-42)"),
]
_POSITIONALS: dict[str, tuple[str, str]] = {
    "validate-manifest": ("path", "manifest path (default: shipped)"),
    "build-fixtures": ("out_dir", "output dir (default: fixtures-out)"),
    "split-dataset": ("out_dir", "output dir (default: split-out)"),
    "validate-runtime": ("path", "policy path (default: shipped)"),
}


def _handler(name: str) -> Handler:
    handler: Handler = getattr(demos, "cmd_" + name.replace("-", "_"))
    return handler


COMMANDS: list[tuple[str, str, Handler, tuple[str, str] | None]] = [
    (name, help_text, _handler(name), _POSITIONALS.get(name))
    for name, help_text in _COMMAND_HELP
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="covertlens",
        description="CovertLens contract checks and demos.",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the full JSON payload"
    )
    parser.add_argument(
        "--out", metavar="PATH", help="also write the JSON payload to PATH"
    )
    parser.set_defaults(func=demos.cmd_validate_manifest, path=None)

    # Same flags after the subcommand; SUPPRESS defaults keep any
    # value given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print the full JSON payload",
    )
    common.add_argument(
        "--out",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="also write the JSON payload to PATH",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")
    for name, help_text, handler, positional in COMMANDS:
        sub = subparsers.add_parser(name, help=help_text, parents=[common])
        if positional is not None:
            dest, pos_help = positional
            sub.add_argument(dest, nargs="?", help=pos_help)
        sub.set_defaults(func=handler)
    return parser


def _payload_json(payload: object) -> str:
    return json.dumps(payload, indent=2, default=str)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.func
    result = handler(args)
    if args.out:
        try:
            Path(args.out).write_text(
                _payload_json(result.payload) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"cannot write --out {args.out}: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(_payload_json(result.payload))
    elif result.summary is not None:
        print(result.summary)
    elif result.payload is not None:
        print(_payload_json(result.payload))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
