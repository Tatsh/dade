"""Tests for the F3DEX walker in :mod:`destin.xg2.displaylist`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from destin.xg2.displaylist import parse_dl_textures, parse_pc_descriptors

if TYPE_CHECKING:
    from collections.abc import Callable

_PALETTE = 0x200
_PIXELS = 0x400
_OTHER_PIXELS = 0x500
_SIZ_CI4 = 0
_SIZ_CI8 = 1
_SIZ_RGBA16 = 2


def _settimg(address: int, header_width: int = 1) -> tuple[int, int]:
    return 0xFD000000 | (header_width - 1), 0x05000000 | address


def _loadtlut(count: int = 256) -> tuple[int, int]:
    return 0xF0000000, (count - 1) << 14


def _settile(size: int, line: int = 1) -> tuple[int, int]:
    return 0xF5000000 | (size << 19) | (line << 9), 0


def _settilesize(width: int, height: int) -> tuple[int, int]:
    return 0xF2000000, (((width - 1) * 4) << 12) | ((height - 1) * 4)


def _loadtile(bottom: int) -> tuple[int, int]:
    return 0xF4000000, bottom * 4


def _palette_load(count: int = 256) -> tuple[tuple[int, int], ...]:
    return _settimg(_PALETTE), _loadtlut(count)


def test_parse_dl_textures_decodes_an_indexed_tile(make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(), _settile(_SIZ_CI8), _settimg(_PIXELS), _settilesize(8, 8))
    textures = parse_dl_textures(make_dl_model(commands))
    assert len(textures) == 1
    assert (textures[0].pixel_format, textures[0].width, textures[0].height) == ('ci8', 8, 8)
    assert (textures[0].offset, len(textures[0].rgba)) == (_PIXELS, 8 * 8 * 4)


def test_parse_dl_textures_decodes_a_four_bit_tile(make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(16), _settile(_SIZ_CI4), _settimg(_PIXELS), _settilesize(8, 8))
    textures = parse_dl_textures(make_dl_model(commands))
    assert [(t.pixel_format, t.width, t.height) for t in textures] == [('ci4', 8, 8)]


def test_parse_dl_textures_decodes_a_direct_colour_tile(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (_settile(_SIZ_RGBA16), _settimg(_PIXELS), _settilesize(8, 8))
    textures = parse_dl_textures(make_dl_model(commands))
    assert [(t.pixel_format, t.width, t.height) for t in textures] == [('rgba16', 8, 8)]


def test_parse_dl_textures_bounds_an_atlas_by_its_tallest_tile(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(), _settile(_SIZ_CI8), _settimg(
        _PIXELS, 16), _loadtile(3), _loadtile(7), _settilesize(8, 8))
    textures = parse_dl_textures(make_dl_model(commands))
    assert [(t.width, t.height) for t in textures] == [(16, 8)]


def test_parse_dl_textures_measures_an_atlas_only_once(make_dl_model: Callable[..., bytes]) -> None:
    # The second run of loads for the same image is a redraw, so its bottom edge is ignored.
    commands = (*_palette_load(), _settile(_SIZ_CI8), _settimg(
        _PIXELS, 16), _loadtile(3), _settimg(_OTHER_PIXELS, 16), _loadtile(1), _settimg(
            _PIXELS, 16), _loadtile(31), _settilesize(8, 8))
    assert [t.height for t in parse_dl_textures(make_dl_model(commands))] == [4]


def test_parse_dl_textures_bounds_a_region_by_the_next_image(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(), _settile(_SIZ_CI8), _settimg(
        _PIXELS, 64), _loadtile(255), _settilesize(8, 8), _settimg(_OTHER_PIXELS), _settilesize(
            8, 8))
    # The first image runs to 0x500, so 0x100 bytes of 64-byte rows bound it to four.
    textures = parse_dl_textures(make_dl_model(commands))
    assert [(t.offset, t.height) for t in textures] == [(_PIXELS, 4), (_OTHER_PIXELS, 8)]


def test_parse_dl_textures_ignores_a_repeated_tile(make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(), _settile(_SIZ_CI8), _settimg(_PIXELS), _settilesize(
        8, 8), _settimg(_PIXELS), _settilesize(8, 8))
    assert len(parse_dl_textures(make_dl_model(commands))) == 1


def test_parse_dl_textures_ignores_a_tile_size_without_an_image(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (_settile(_SIZ_CI8), _settilesize(8, 8))
    assert parse_dl_textures(make_dl_model(commands)) == []


def test_parse_dl_textures_ignores_an_unknown_pixel_size(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(), _settile(3), _settimg(_PIXELS), _settilesize(8, 8))
    assert parse_dl_textures(make_dl_model(commands)) == []


def test_parse_dl_textures_rejects_an_implausible_size(make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(), _settile(_SIZ_CI8), _settimg(_PIXELS), _settilesize(1, 1))
    assert parse_dl_textures(make_dl_model(commands)) == []


def test_parse_dl_textures_rejects_a_tile_running_past_the_blob(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(), _settile(_SIZ_RGBA16), _settimg(0x7F0), _settilesize(64, 64))
    assert parse_dl_textures(make_dl_model(commands)) == []


def test_parse_dl_textures_rejects_a_four_bit_tile_running_past_the_blob(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (*_palette_load(16), _settile(_SIZ_CI4), _settimg(0x7F0), _settilesize(64, 64))
    assert parse_dl_textures(make_dl_model(commands)) == []


def test_parse_dl_textures_ignores_an_oversized_palette(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = (_settimg(0x7FE), _loadtlut(), _settile(_SIZ_CI8), _settimg(_PIXELS),
                _settilesize(8, 8))
    assert parse_dl_textures(make_dl_model(commands)) == []


def test_parse_dl_textures_ignores_a_palette_outside_segment_five(
        make_dl_model: Callable[..., bytes]) -> None:
    commands = ((0xFD000000, 0x01000200), _loadtlut(), _settile(_SIZ_CI8), _settimg(_PIXELS),
                _settilesize(8, 8))
    assert parse_dl_textures(make_dl_model(commands)) == []


@pytest.mark.parametrize('dimensions', [0x00040008, 0x00040800])
def test_parse_pc_descriptors_rejects_a_zero_dimension(dimensions: int) -> None:
    model = bytearray(0x100)
    struct.pack_into('<4I', model, 0, 0xAC000000, 0x05000020, dimensions, 0x05000040)
    assert list(parse_pc_descriptors(bytes(model))) == []
