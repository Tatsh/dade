from __future__ import annotations

import struct

import pytest

from dade.tgr.f3dex import Corner, DisplayListReader, Material
from dade.tgr.texture import FMT_CI, FMT_RGBA, SIZ_4B, SIZ_16B, TextureKey

_END = struct.pack('>II', 0xB8 << 24, 0)
_IMAGE = 0x180
_PALETTE = 0x1C0


def _cmd(opcode: int, low: int = 0, w1: int = 0) -> bytes:
    return struct.pack('>II', opcode << 24 | low, w1)


def _vtx(address: int, count: int, first: int = 0) -> bytes:
    return _cmd(0x04, (first * 2) << 16 | count << 10, address)


def _tri(a: int, b: int, c: int) -> bytes:
    return _cmd(0xBF, 0, (a * 2) << 16 | (b * 2) << 8 | c * 2)


def _vertex(x: int, y: int, z: int, s: int = 0, t: int = 0) -> bytes:
    return struct.pack('>hhhHhhBBBB', x, y, z, 0, s, t, 1, 2, 3, 4)


def _memory(commands: bytes, at: int = 0) -> bytearray:
    memory = bytearray(0x200)
    memory[at:at + len(commands)] = commands
    vertices = _vertex(0, 0, 0) + _vertex(10, 0, 0, 64, 0) + _vertex(0, 10, 0, 0, 32)
    memory[0x100:0x100 + len(vertices)] = vertices
    return memory


def _settile(tile: int, fmt: int, siz: int, *, tmem: int = 0, line: int = 1, low: int = 0) -> bytes:
    return _cmd(0xF5, fmt << 21 | siz << 19 | line << 9 | tmem, tile << 24 | low)


def _tile_size(tile: int, width: int, height: int, uls: int = 0) -> bytes:
    return _cmd(0xF2, uls << 12, tile << 24 | (width - 1) << 2 << 12 | (height - 1) << 2)


def _load(image: int = _IMAGE, tile: int = 7, tmem: int = 0, opcode: int = 0xF3) -> bytes:
    setup = _settile(tile, FMT_RGBA, SIZ_16B, tmem=tmem) if tile == 7 else b''
    return _cmd(0xFD, 0, image) + setup + _cmd(opcode, 0, tile << 24)


def _draw() -> bytes:
    return _vtx(0x100, 3) + _tri(0, 1, 2) + _END


def _run(commands: bytes, base: int = 0, address: int = 0) -> DisplayListReader:
    reader = DisplayListReader(_memory(commands), base)
    reader.run(address)
    return reader


def test_offset_drops_the_high_byte() -> None:
    assert DisplayListReader(b'', 0x1000).offset(0x80001234) == 0x234


def test_untextured_triangle() -> None:
    reader = _run(_vtx(0x80001100, 3) + _cmd(0xE7) + _tri(0, 1, 2) + _END, 0x1000, 0x80001000)
    (triangle,) = reader.triangles
    assert triangle.material == Material(None, lit=False, two_sided=False)
    assert triangle.corners == (Corner(
        (0.0, 0.0, 0.0), (0.0, 0.0),
        (1, 2, 3, 4)), Corner((10.0, 0.0, 0.0), (0.0, 0.0),
                              (1, 2, 3, 4)), Corner((0.0, 10.0, 0.0), (0.0, 0.0), (1, 2, 3, 4)))


def test_tri2_and_geometry_mode() -> None:
    reader = _run(
        _cmd(0xB6, 0, 0x2000) + _cmd(0xB7, 0, 0x20000) + _vtx(0x100, 3) +
        _cmd(0xB1, 0 << 16 | 2 << 8 | 4, 4 << 16 | 2 << 8 | 0) + _END)
    assert len(reader.triangles) == 2
    assert all(t.material.lit and t.material.two_sided for t in reader.triangles)
    assert reader.triangles[1].corners[0].position == (0.0, 10.0, 0.0)


def test_textured_triangle_coordinates() -> None:
    reader = _run(_load() + _settile(0, FMT_RGBA, SIZ_16B) + _tile_size(0, 4, 2) +
                  _cmd(0xBB, 0 << 8 | 1, 0x8000 << 16 | 0x8000) + _draw())
    (triangle,) = reader.triangles
    assert triangle.material.texture == TextureKey(_IMAGE, -1, FMT_RGBA, SIZ_16B, 4, 2, 1)
    assert [c.uv for c in triangle.corners] == [(0.0, 0.0), (0.25, 0.0), (0.0, 0.25)]


def test_ci_texture_with_palette() -> None:
    reader = _run(
        _load(_PALETTE, 5, opcode=0xF0) + _load() + _settile(0, FMT_CI, SIZ_4B) +
        _tile_size(0, 4, 4) + _draw())
    assert reader.triangles[0].material.texture == TextureKey(_IMAGE, _PALETTE, FMT_CI, SIZ_4B, 4,
                                                              4, 1)


def test_ci_texture_without_palette_is_untextured() -> None:
    reader = _run(
        _load(tile=6) + _settile(0, FMT_CI, SIZ_4B, tmem=0x1F0) + _tile_size(0, 4, 4) + _draw())
    assert reader.triangles[0].material.texture is None


def test_texture_inside_a_loaded_block() -> None:
    reader = _run(_load() + _settile(0, FMT_RGBA, SIZ_16B, tmem=0x2) + _tile_size(0, 2, 2) +
                  _draw())
    texture = reader.triangles[0].material.texture
    assert texture is not None
    assert texture.address == _IMAGE + 0x10


def test_mask_clamps_size() -> None:
    reader = _run(_load() + _settile(0, FMT_RGBA, SIZ_16B, low=1 << 14 | 1 << 4) +
                  _tile_size(0, 8, 8) + _draw())
    texture = reader.triangles[0].material.texture
    assert texture is not None
    assert (texture.width, texture.height) == (2, 2)


@pytest.mark.parametrize(('shift', 'u'), [(1, 0.25), (15, 1.0)])
def test_shift_scales_coordinates(shift: int, u: float) -> None:
    reader = _run(_load() + _settile(0, FMT_RGBA, SIZ_16B, low=shift) + _tile_size(0, 1, 1) +
                  _cmd(0xBB, 1, 0x4000 << 16 | 0x4000) + _draw())
    assert reader.triangles[0].corners[1].uv == (u, 0.0)


@pytest.mark.parametrize('commands', [
    _settile(0, FMT_RGBA, SIZ_16B) + _tile_size(0, 4, 4),
    _load() + _settile(0, FMT_RGBA, SIZ_16B) + _tile_size(0, 1, 1, uls=8),
    _load(0x9000) + _settile(0, FMT_RGBA, SIZ_16B) + _tile_size(0, 4, 4),
    _load() + _settile(0, FMT_RGBA, SIZ_16B) + _tile_size(0, 4, 4) + _cmd(0xB7, 0, 0x40000),
    _load() + _settile(0, FMT_RGBA, SIZ_16B) + _tile_size(0, 4, 4) + _cmd(0xBB, 0, 0)
])
def test_untextured_cases(commands: bytes) -> None:
    assert _run(commands + _draw()).triangles[0].material.texture is None


def test_detail_mode_uses_next_tile() -> None:
    reader = _run(_load() + _settile(1, FMT_RGBA, SIZ_16B) + _tile_size(1, 4, 4) +
                  _cmd(0xBA, 16 << 8 | 3, 1 << 16 | 2 << 17) + _draw())
    texture = reader.triangles[0].material.texture
    assert texture is not None
    assert texture.width == 4


def test_bound_texture_is_used() -> None:
    key = TextureKey(0, -1, FMT_RGBA, SIZ_16B, 8, 8, 0)
    reader = DisplayListReader(_memory(_draw()))
    reader.bound = key
    reader.run(0)
    assert reader.triangles[0].material.texture == key


@pytest.mark.parametrize(('flag', 'count'), [(0, 2), (1, 1)])
def test_call_and_branch(flag: int, count: int) -> None:
    commands = _cmd(0x06, flag << 16, 0x40) + _tri(0, 1, 2) + _END
    memory = _memory(commands)
    memory[0x40:0x40 + 24] = _draw()
    reader = DisplayListReader(memory)
    reader.run(0)
    assert len(reader.triangles) == count


def test_recursion_is_bounded() -> None:
    assert _run(_cmd(0x06, 0, 0) + _END).triangles == []


def test_address_outside_memory() -> None:
    assert _run(_draw(), address=0x800000).triangles == []


def test_vertices_past_the_slots_or_memory_are_not_loaded() -> None:
    reader = _run(_vtx(0x100, 3, 62) + _vtx(0x1F8, 1, 0) + _tri(62, 63, 0) + _END)
    assert [c.position for c in reader.triangles[0].corners] == [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                                                                 (0.0, 0.0, 0.0)]
