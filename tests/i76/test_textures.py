"""Tests for :py:mod:`destin.i76.textures`."""
from __future__ import annotations

import struct

import pytest

from destin.i76.textures import (
    PALETTE_SIZE,
    decode_map,
    decode_vqm,
    load_codebook,
    load_palette,
    to_rgb,
    vqm_codebook_name,
)


def test_load_palette_truncates(palette: bytes) -> None:
    assert load_palette(palette + b'trailing') == palette
    assert len(load_palette(palette)) == PALETTE_SIZE


def test_decode_map_dimensions(map_texture: bytes) -> None:
    image = decode_map(map_texture)
    assert (image.width, image.height) == (6, 4)
    assert image.pixels == bytes(range(24))


def test_load_codebook_entry_count(codebook: bytes) -> None:
    entries = load_codebook(codebook)
    assert len(entries) == 8
    assert all(len(entry) == 16 for entry in entries)


def test_vqm_codebook_name(vqm_texture: bytes) -> None:
    assert vqm_codebook_name(vqm_texture) == 'c.cbk'


def test_decode_vqm_dimensions(vqm_texture: bytes, codebook: bytes) -> None:
    image = decode_vqm(vqm_texture, load_codebook(codebook))
    assert (image.width, image.height) == (8, 8)
    assert image.codebook_name == 'c.cbk'
    assert len(image.pixels) == 64


def test_decode_vqm_expands_codebook_blocks(vqm_texture: bytes, codebook: bytes) -> None:
    entries = load_codebook(codebook)
    image = decode_vqm(vqm_texture, entries)
    # The top-left block references codebook entry 0, laid out row by row.
    assert b''.join(image.pixels[row * 8:row * 8 + 4] for row in range(4)) == entries[0]


def test_decode_vqm_solid_block(vqm_texture: bytes, codebook: bytes) -> None:
    image = decode_vqm(vqm_texture, load_codebook(codebook))
    # The fourth block has the solid flag set, so every one of its pixels is the low byte.
    assert {image.pixels[(4 + row) * 8 + 4:(4 + row) * 8 + 8] for row in range(4)} == {b'\x42' * 4}


def test_to_rgb_applies_palette(palette: bytes) -> None:
    assert to_rgb(bytes([0, 1]), 2, 1, palette) == palette[0:3] + palette[3:6]


def test_to_rgb_ignores_excess_indices(palette: bytes) -> None:
    assert to_rgb(bytes([0, 1, 2, 3]), 2, 1, palette) == palette[0:6]


@pytest.mark.parametrize(('width', 'height'), [(4, 4), (8, 4)])
def test_decode_vqm_sizes(codebook: bytes, width: int, height: int) -> None:
    blocks = (width // 4) * (height // 4)
    data = (struct.pack('<II', width, height) + b'c.cbk\0' + b'\0' * 10 +
            struct.pack(f'<{blocks}H', *([0] * blocks)))
    assert len(decode_vqm(data, load_codebook(codebook)).pixels) == width * height
