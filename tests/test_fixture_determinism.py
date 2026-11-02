"""Fixture bytes must not depend on the machine that generates them.

Fixture content hashes feed fixture IDs, the frozen calibration's
development dataset hash and the published scorecard. CI once failed on
a self-hosted runner whose Python linked zlib-ng instead of classic
zlib: identical pixels, different compressed PNG bytes, different
hashes. These tests keep every pinned fixture path off the platform
compressor.
"""

import zlib

import pytest

from covertlens import ids
from covertlens.fixtures import _save_png, _zlib_stored, build_dataset
from covertlens.geo_benchmark import benign_controls
from covertlens.geo_calibration import geometric_calibration_dataset
from covertlens.metadata_fixtures import build_metadata_dataset


@pytest.mark.parametrize("size", [0, 1, 65_534, 65_535, 65_536, 200_003])
def test_stored_stream_round_trips_across_block_boundaries(size):
    data = bytes((i * 31) & 0xFF for i in range(size))
    stream = _zlib_stored(data)
    assert zlib.decompress(stream) == data
    assert int.from_bytes(stream[:2], "big") % 31 == 0  # valid zlib header


def test_png_bytes_are_pinned():
    # 2x1 RGB image; any change to the writer changes this digest.
    png = _save_png(bytes((1, 2, 3, 250, 251, 252)), 2, 1)
    assert ids.content_hash(png) == (
        "sha256:a21838c23105481eddd2df42d14ec79c729aadebb01cec10916357d3ffd999ff"
    )


def test_pinned_fixtures_never_use_the_platform_compressor(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "zlib.compress output varies by zlib build (zlib vs zlib-ng); "
            "pinned fixtures must use _zlib_stored"
        )

    monkeypatch.setattr(zlib, "compress", forbidden)
    build_dataset()
    build_metadata_dataset()
    geometric_calibration_dataset()
    benign_controls(1)
