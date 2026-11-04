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


def spa_pair_counts(
    samples: bytes, width: int, height: int, channels: int, max_diff: int
) -> tuple[int, int, int] | None:
    """(pairs, LSB-agreeing pairs, smooth pairs) for SPA, or None (CL-78).

    Same pairs as the reference loop in `lsb._spa_statistics`:
    non-overlapping horizontally adjacent same-channel samples.
    """
    np = numpy_backend()
    if np is None:
        return None
    grid = np.frombuffer(samples, dtype=np.uint8)[: width * height * channels]
    grid = grid.reshape(height, width, channels)
    even = (width // 2) * 2
    u = grid[:, 0:even:2, :].astype(np.int16)
    v = grid[:, 1:even:2, :].astype(np.int16)
    pairs = int(u.size)
    agree = int(np.count_nonzero(((u ^ v) & 1) == 0))
    smooth = int(np.count_nonzero(np.abs(u - v) <= max_diff))
    return pairs, agree, smooth
