"""NumPy fast path must preserve reference pixels and statistics exactly."""

import pytest

from covertlens.acceleration import sample_counts, unfilter_row
from covertlens.lsb import analyze_lsb_bytes
from tests.test_parsing import filtered_png


def test_requested_numpy_falls_back_when_extra_is_missing(monkeypatch):
    from covertlens import acceleration

    def missing_extra(name):
        assert name == "numpy"
        raise ModuleNotFoundError("NumPy extra is not installed")

    monkeypatch.setenv("COVERTLENS_FAST_PATH", "numpy")
    monkeypatch.setattr(acceleration, "import_module", missing_extra)
    assert acceleration.numpy_backend() is None
    assert sample_counts(b"\x00\x01\x01")[:3] == [1, 2, 0]
    assert unfilter_row(bytearray([1, 2, 3]), bytearray(3), 3, 1) is None


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
