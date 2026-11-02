"""Optional, exact NumPy operations (CL-57).

Enable with COVERTLENS_FAST_PATH=numpy after installing covertlens[fast].
The default remains the standard-library reference implementation.
"""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any


def numpy_backend() -> Any:
    if os.environ.get("COVERTLENS_FAST_PATH") != "numpy":
        return None
    try:
        # Load the optional extra at runtime so the dependency-free build
        # can also be type checked without NumPy installed.
        return import_module("numpy")
    except ImportError:
        return None


def sample_counts(samples: bytes) -> list[int]:
    np = numpy_backend()
    if np is not None:
        return np.bincount(
            np.frombuffer(samples, dtype=np.uint8), minlength=256
        ).tolist()
    counts = [0] * 256
    for value in samples:
        counts[value] += 1
    return counts


def unfilter_row(
    line: bytearray, prev: bytearray, channels: int, kind: int
) -> bytearray | None:
    """Vectorize exact None/Sub/Up filters; others use the reference loop."""
    np = numpy_backend()
    if np is None or kind not in (0, 1, 2):
        return None
    values = np.frombuffer(line, dtype=np.uint8).astype(np.uint64)
    if kind == 1:
        values = np.cumsum(values.reshape(-1, channels), axis=0)
    elif kind == 2:
        values += np.frombuffer(prev, dtype=np.uint8)
    return bytearray((values % 256).astype(np.uint8).tobytes())
