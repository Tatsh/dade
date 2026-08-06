"""Tests for :py:mod:`destin.i76.horizon`."""
from __future__ import annotations

import struct

from destin.i76.horizon import assemble_panorama, bundle_stem, horizon_set, parse_hzd
from destin.i76.textures import decode_map
import pytest


def test_parse_hzd(hzd: bytes) -> None:
    assert parse_hzd(hzd) == ('NH_3_01.MAP', 'NH_3_02.MAP', 'NH_3_03.MAP')


def test_parse_hzd_keeps_trailing_name() -> None:
    # The final name is not NUL-terminated, so it is only found by the trailing flush.
    assert parse_hzd(b'A_1_01.MAP') == ('A_1_01.MAP',)


def test_parse_hzd_ignores_other_extensions() -> None:
    assert parse_hzd(b'skip.act\x00keep.map\x00') == ('keep.map',)


def test_parse_hzd_empty() -> None:
    assert parse_hzd(b'') == ()


@pytest.mark.parametrize(('name', 'expected'), [('NH_3_01.MAP', 3), ('NH_17_02.MAP', 17)])
def test_horizon_set(name: str, expected: int) -> None:
    assert horizon_set(name) == expected


def test_horizon_set_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match='invalid literal'):
        horizon_set('NH_X_01.MAP')


@pytest.mark.parametrize(('number', 'expected'), [(3, 'nhoriz3m'), (17, 'nhoriz17m')])
def test_bundle_stem(number: int, expected: str) -> None:
    assert bundle_stem(number) == expected


def test_assemble_panorama_dimensions(palette: bytes) -> None:
    strips = [decode_map(struct.pack('<II', 2, 3) + bytes(6)) for _ in range(3)]
    panorama = assemble_panorama(strips, palette)
    assert (panorama.width, panorama.height) == (6, 3)
    assert len(panorama.pixels) == 6 * 3 * 3


def test_assemble_panorama_lays_strips_left_to_right(palette: bytes) -> None:
    left = decode_map(struct.pack('<II', 1, 1) + bytes([0]))
    right = decode_map(struct.pack('<II', 1, 1) + bytes([1]))
    panorama = assemble_panorama([left, right], palette)
    assert panorama.pixels == palette[0:3] + palette[3:6]


def test_assemble_panorama_rejects_empty(palette: bytes) -> None:
    with pytest.raises(ValueError, match='No horizon strips'):
        assemble_panorama([], palette)
