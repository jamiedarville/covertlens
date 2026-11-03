"""Order-preserving process-pool map for large fixture suites (CL-68).

The CL-68 banded suite builds and scores a few thousand fixtures in
pure Python. Every item is independent and deterministic, so a
process pool returns exactly the serial result, in the same order.
Parallelism is opt-in so a library call never starts processes by
surprise: `COVERTLENS_BUILD_WORKERS=auto` uses every CPU, a number sets
the pool size, and unset (or `1`) stays serial. Callers that opt in
must be importable without side effects (`python -m ...`, or a script
guarded by `if __name__ == "__main__"`), because pool workers import
the main module. CI and `make refreeze` opt in. Environments without
process support (Pyodide, restricted sandboxes) fall back to serial.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def workers() -> int:
    raw = (os.environ.get("COVERTLENS_BUILD_WORKERS") or "1").strip().lower()
    if raw == "auto":
        return os.cpu_count() or 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def process_map(
    func: Callable[[T], R], items: Sequence[T], *, chunksize: int = 4
) -> list[R]:
    """`[func(x) for x in items]`, computed in a process pool when possible."""
    count = min(workers(), len(items))
    if count <= 1:
        return [func(item) for item in items]
    try:
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures.process import BrokenProcessPool

        try:
            with ProcessPoolExecutor(max_workers=count) as pool:
                return list(pool.map(func, items, chunksize=chunksize))
        except BrokenProcessPool:
            pass
    except (ImportError, NotImplementedError, OSError, PermissionError):
        pass
    return [func(item) for item in items]


def star(args: tuple[Callable[..., Any], tuple[Any, ...]]) -> Any:
    """Top-level trampoline so pools can call functions with several args."""
    func, call_args = args
    return func(*call_args)
