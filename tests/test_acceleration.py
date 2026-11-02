"""NumPy fast path must preserve reference pixels and statistics exactly."""

import pytest

from covertlens.acceleration import sample_counts, unfilter_row
from covertlens.lsb import analyze_lsb_bytes
from tests.test_parsing import filtered_png


def test_numpy_filters_and_histograms_match_reference(monkeypatch):
    pytest.importorskip("numpy")
    for width, height in [(1, 8), (17, 9), (31, 16)]:
        data = filtered_png(
            bytes((i * 71) % 256 for i in range(width * height * 3)), width, height
        )
        monkeypatch.delenv("COVERTLENS_FAST_PATH", raising=False)
        ref = analyze_lsb_bytes(data)
        monkeypatch.setenv("COVERTLENS_FAST_PATH", "numpy")
        fast = analyze_lsb_bytes(data)
        assert fast.pixels == ref.pixels
        assert fast.findings == ref.findings
    monkeypatch.delenv("COVERTLENS_FAST_PATH", raising=False)
    expected = sample_counts(bytes(range(256)) * 7)
    monkeypatch.setenv("COVERTLENS_FAST_PATH", "numpy")
    assert sample_counts(bytes(range(256)) * 7) == expected
    assert unfilter_row(
        bytearray([255, 3, 4, 2, 254, 253]), bytearray(6), 3, 1
    ) == bytearray([255, 3, 4, 1, 1, 1])
