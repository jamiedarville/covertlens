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


@pytest.mark.parametrize(
    "name", ["444", "422", "420", "restart", "optimized", "grayscale", "rgb"]
)
def test_jpeg_pixels_and_geometry_match_reference(monkeypatch, name):
    from covertlens.dct import detect_dct
    from covertlens.jpeg_pixels import decode_jpeg_rgb
    from covertlens.parsing import analyze_bytes
    from covertlens.segmentation import segment_image
    from tests.test_jpeg_pixels import DATA

    pytest.importorskip("numpy")
    data = (DATA / f"{name}.jpg").read_bytes()
    monkeypatch.delenv("COVERTLENS_FAST_PATH", raising=False)
    parsed = analyze_bytes(data)
    pixels = decode_jpeg_rgb(data)
    segment = segment_image(data).to_dict()
    finding = detect_dct(parsed)
    monkeypatch.setenv("COVERTLENS_FAST_PATH", "numpy")
    assert decode_jpeg_rgb(data) == pixels
    assert decode_jpeg_rgb(data, parsed=parsed) == pixels
    assert segment_image(data, parsed=parsed).to_dict() == segment
    assert detect_dct(parsed) == finding


def test_idct_batch_exact_rounding(monkeypatch):
    from covertlens.jpeg_pixels import _idct_block, _idct_blocks_numpy

    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(57)
    blocks = rng.integers(-2048, 2049, size=(100, 64))
    # DC-only blocks exercise positive and negative half-integer rounding.
    dc = np.zeros((100, 64), dtype=np.int64)
    dc[:, 0] = np.arange(-50, 50) * 4
    blocks = np.concatenate((blocks, dc))
    expected = [_idct_block(b.tolist()) for b in blocks]
    assert (
        _idct_blocks_numpy(blocks.astype(np.float64).reshape(-1, 8, 8), np)
        .reshape(-1, 64)
        .tolist()
        == expected
    )


def test_cached_jpeg_coefficients_are_bound_to_bytes(monkeypatch):
    from covertlens.jpeg_pixels import _ScanBits, decode_jpeg_rgb
    from covertlens.parsing import analyze_bytes
    from tests.test_jpeg_pixels import DATA

    pytest.importorskip("numpy")
    monkeypatch.setenv("COVERTLENS_FAST_PATH", "numpy")
    data = (DATA / "420.jpg").read_bytes()
    wrong = analyze_bytes((DATA / "444.jpg").read_bytes())
    expected = decode_jpeg_rgb(data)
    assert decode_jpeg_rgb(data, parsed=wrong) == expected
    parsed = analyze_bytes(data)

    def no_second_entropy_decode(*args):
        raise AssertionError("coefficients should be reused")

    monkeypatch.setattr(_ScanBits, "read_code", no_second_entropy_decode)
    assert decode_jpeg_rgb(data, parsed=parsed) == expected


@pytest.mark.parametrize("shape", [(1, 1), (1, 9), (9, 1), (2, 2), (17, 23)])
def test_morphology_matches_reference_at_edges(monkeypatch, shape):
    from covertlens.segmentation import _open_close

    np = pytest.importorskip("numpy")
    width, height = shape
    rng = np.random.default_rng(57)
    for probability in (0, 0.3, 0.9, 1):
        mask = (rng.random(width * height) < probability).tolist()
        monkeypatch.delenv("COVERTLENS_FAST_PATH", raising=False)
        expected = _open_close(mask, width, height)
        monkeypatch.setenv("COVERTLENS_FAST_PATH", "numpy")
        assert _open_close(mask, width, height) == expected


def test_thin_run_components_match_flood_fill():
    from covertlens.segmentation import _components, _thin_components_numpy

    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(57)
    for width, height in [(1, 1), (1, 9), (9, 1), (2, 3), (23, 17)]:
        for probability in (0, 0.1, 0.5, 0.9, 1):
            mask = (rng.random(width * height) < probability).tolist()
            for minimum in (1, 3, 8):
                expected = []
                for points in _components(mask, width, height, minimum):
                    xs, ys = [p % width for p in points], [p // width for p in points]
                    if min(max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) < 3:
                        expected.append(sorted(points))
                actual = _thin_components_numpy(mask, width, height, minimum, np)
                assert sorted(map(sorted, actual)) == sorted(expected)


def test_component_traversal_order_matches_reference():
    import random

    from covertlens.segmentation import _components

    rng = random.Random(57)
    for width, height in [(1, 9), (9, 1), (19, 23)]:
        for probability in (0.2, 0.8, 1):
            mask = [rng.random() < probability for _ in range(width * height)]
            seen = set()
            expected = []
            for start, filled in enumerate(mask):
                if not filled or start in seen:
                    continue
                stack, points = [start], []
                seen.add(start)
                while stack:
                    idx = stack.pop()
                    points.append(idx)
                    x, y = idx % width, idx // width
                    for nidx in (
                        idx - 1 if x else -1,
                        idx + 1 if x < width - 1 else -1,
                        idx - width if y else -1,
                        idx + width if y < height - 1 else -1,
                    ):
                        if nidx >= 0 and mask[nidx] and nidx not in seen:
                            seen.add(nidx)
                            stack.append(nidx)
                expected.append(points)
            assert _components(mask, width, height, 1) == expected


def test_numpy_sample_pair_counts_match_the_reference(monkeypatch):
    pytest.importorskip("numpy")
    from covertlens.fixtures import build_pair
    from covertlens.lsb import SPA_DEFAULT_CONFIG, _spa_statistics
    from covertlens.parsing import analyze_bytes

    for width in (17, 64):
        clean, encoded = build_pair(
            "spatial_lsb", width=width, height=9, payload_bytes=4
        )
        for fixture in (clean, encoded):
            result = analyze_bytes(fixture.data)
            image = result.image
            args = (
                result.pixels,
                image["width"],
                image["height"],
                image.get("channels", 3),
                SPA_DEFAULT_CONFIG,
            )
            monkeypatch.delenv("COVERTLENS_FAST_PATH", raising=False)
            reference = _spa_statistics(*args)
            monkeypatch.setenv("COVERTLENS_FAST_PATH", "numpy")
            assert _spa_statistics(*args) == reference
