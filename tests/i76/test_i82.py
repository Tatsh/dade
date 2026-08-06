"""Tests for :py:mod:`destin.i76.i82`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.i76.i82 import find_in_pools, level_ids, surface_names, texture_refs

if TYPE_CHECKING:
    from pathlib import Path


def test_surface_names(mrm_terrain: bytes) -> None:
    assert surface_names(mrm_terrain) == ('road.bmp', 'grass.tga')


def test_surface_names_skips_empty_entries() -> None:
    data = bytearray(b'ZONV' + bytes(8) + struct.pack('<I', 2) + bytes(0x80 * 2))
    data[0x10:0x10 + 8] = b'only.bmp'
    assert surface_names(bytes(data)) == ('only.bmp',)


def test_surface_names_without_magic() -> None:
    assert surface_names(b'NOPE' + bytes(64)) == ()


def test_texture_refs_merges_world_and_terrain(msa_world: bytes, mrm_terrain: bytes) -> None:
    assert texture_refs(msa_world, mrm_terrain) == ('body.tga', 'grass.tga', 'road.bmp', 'wall.bmp')


def test_texture_refs_lowercases_the_stem(mrm_terrain: bytes) -> None:
    assert texture_refs(b'Texture: WALL.bmp', mrm_terrain) == ('grass.tga', 'road.bmp', 'wall.bmp')


def test_texture_refs_extension_match_is_case_sensitive(mrm_terrain: bytes) -> None:
    # The world scan only matches lowercase extensions, so an upper-case reference is missed.
    # The object scan is case-insensitive; the difference is inherited from the original tools.
    assert 'wall.bmp' not in texture_refs(b'Texture: WALL.BMP', mrm_terrain)


def test_texture_refs_ignores_other_extensions(mrm_terrain: bytes) -> None:
    assert 'sound.wav' not in texture_refs(b'sound.wav', mrm_terrain)


def test_level_ids_intersects(i82_source: Path) -> None:
    assert level_ids(i82_source / 'data', i82_source / 'mrm') == ('lvl1',)


def test_level_ids_without_pairs(tmp_path: Path) -> None:
    (data := tmp_path / 'data').mkdir()
    (mrm := tmp_path / 'mrm').mkdir()
    (data / 'only.msa').write_bytes(b'')
    assert level_ids(data, mrm) == ()


def test_find_in_pools_takes_first_match(tmp_path: Path) -> None:
    (first := tmp_path / 'a').mkdir()
    (second := tmp_path / 'b').mkdir()
    (first / 'x.bmp').write_bytes(b'first')
    (second / 'x.bmp').write_bytes(b'second')
    found = find_in_pools('x.bmp', [first, second])
    assert found is not None
    assert found.read_bytes() == b'first'


def test_find_in_pools_absent(tmp_path: Path) -> None:
    assert find_in_pools('nope.bmp', [tmp_path]) is None
