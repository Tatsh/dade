"""Tests for :mod:`destin.marmalade.material`."""
from __future__ import annotations

from destin.marmalade.material import decode_material
from destin.marmalade.test_utils import build_material


def test_decode_same_as_default() -> None:
    material = decode_material(build_material(flags=0x2A, same_as_default=True))
    assert material == {'same_as_default': True, 'flags': '0x2a'}


def test_decode_full_material_resolves_textures() -> None:
    body = build_material(flags=0x1,
                          colours=[(1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16)],
                          texture_hashes=(0, 0xABCDEF01, 0x12345678))
    material = decode_material(body, {0xABCDEF01: 'wall.png'})
    assert material['same_as_default'] is False
    assert material['colour_ambient'] == [1, 2, 3, 4]
    assert material['colour_colour4'] == [13, 14, 15, 16]
    # A zero hash is an unused slot and is dropped; mapped hashes resolve to names and
    # unmapped hashes fall back to eight hex digits.
    assert material['textures'] == ['wall.png', '12345678']
