"""Tests for :mod:`dade.xg2.xg1_level`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from dade.xg2.lzhuf import LzhufError
from dade.xg2.typing import Texture
from dade.xg2.xg1_level import (
    XG1,
    bank_texture_key,
    decode_level_geometry,
    decode_level_textures,
    demo,
    read_bank_descriptors,
    read_header,
    read_texture_bank,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_BASE = 0x1000
_STREAM = 0x100
_COORDS = 0x200
_TEXTURES = 0x300
_PIXELS = 0x400


def _header() -> bytes:
    words = [0] * 17
    words[0] = 0x800  # objects
    words[1] = 1  # object_count
    words[3] = _TEXTURES  # textures
    words[4] = 1  # texture_count
    words[5] = _PIXELS  # pixels
    words[6] = 0x240  # pixels_size
    words[13] = _COORDS  # coords
    words[14] = 2  # coords_count
    words[15] = _STREAM  # stream
    words[16] = 200  # stream_size
    return struct.pack('>17I', *words)


def _rom() -> bytearray:
    rom = bytearray(0x20000)
    rom[_BASE:_BASE + 0x44] = _header()
    # One object record: an origin and two corner points, the second span forced negative to wrap.
    struct.pack_into('>9i', rom, _BASE + 0x800, 0, 0, 0, -1, -1, -1, 0, 0, 0)
    return rom


def _vertex(x: int, y: int, z: int, index: int, colour: tuple[int, int, int]) -> bytes:
    return struct.pack('>3h4B', x, y, z, index, *colour)


def _bytecode() -> bytes:
    out = bytearray()
    out += bytes([1, 4])  # Four vertices.
    out += _vertex(0, 0, 0, 0, (10, 20, 30))
    out += _vertex(10, 0, 0, 1, (40, 50, 60))
    out += _vertex(0, 10, 0, 0, (70, 80, 90))
    out += _vertex(10, 10, 0, 9, (1, 2, 3))  # Coordinate index past the table falls back to zero.
    out += bytes([2, 0])  # Bind descriptor zero.
    out += bytes([3, 0x11, 0x22, 0x33])  # Primitive colour.
    out += bytes([7])  # Flat combiner.
    out += bytes([4]) + struct.pack('>H', (0 << 10) | (1 << 5) | 2)  # G_TRI1 over 0, 1, 2, tinted.
    out += bytes([6])  # Textured combiner.
    out += bytes([5]) + struct.pack('>2H', (0 << 10) | (1 << 5) | 2, (1 << 10) | (2 << 5) | 3)
    out += bytes([9, 0, 1])  # Retarget slot zero's coordinates at entry one.
    out += bytes([8, 1]) + b'\x00' * 6  # One normal record.
    out += bytes([12, 0])  # A bank opcode whose record is out of range.
    out += bytes([10])  # A no-operand opcode.
    out += bytes([0])  # End.
    return bytes(out)


def _dispatch(mocker: MockerFixture) -> None:
    descriptor = struct.pack('>4B2I', 4, 4, 1, 0, 0x10, 0x40)
    coords = struct.pack('>4h', 0, 0, 16, 16)
    payloads = {
        _BASE + _STREAM: _bytecode(),
        _BASE + _COORDS: coords,
        _BASE + _TEXTURES: descriptor,
        _BASE + _PIXELS: bytes(0x240),
    }

    def fake(_data: bytes, start: int, _size: int, **_kw: object) -> bytes:
        return payloads[start]

    mocker.patch('dade.xg2.xg1_level.decompress_lzhuf', side_effect=fake)


def test_demo_holds() -> None:
    demo()


def test_read_header_reads_the_region_fields() -> None:
    header = read_header(bytes(_rom()), _BASE, XG1)
    assert header.stream == _STREAM
    assert header.stream_size == 200
    assert header.region == 0


def test_decode_level_geometry_runs_the_bytecode(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.xg1_level.xg1_level_banks', return_value={_BASE: 0x5000})
    _dispatch(mocker)
    meshes = decode_level_geometry(bytes(_rom()), _BASE, XG1)
    assert meshes
    assert sum(len(mesh.triangles) for mesh in meshes) == 3


def test_decode_level_geometry_of_a_truncated_stream(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.xg1_level.decompress_lzhuf', side_effect=LzhufError(0, 1))
    assert decode_level_geometry(bytes(_rom()), _BASE, XG1) == []


def test_decode_level_geometry_binds_a_bank_texture(mocker: MockerFixture) -> None:
    key = bank_texture_key(0x5000, 0)
    mocker.patch('dade.xg2.xg1_level.xg1_level_banks', return_value={_BASE: 0x5000})
    mocker.patch('dade.xg2.xg1_level.read_texture_bank',
                 return_value=[Texture('ci8', key, 4, 4, b'\xff' * 64)])
    code = (bytes([1, 3]) + _vertex(0, 0, 0, 0, (1, 1, 1)) + _vertex(10, 0, 0, 0, (2, 2, 2)) +
            _vertex(0, 10, 0, 0, (3, 3, 3)) + bytes([12, 0, 4]) +
            struct.pack('>H', (0 << 10) | (1 << 5) | 2) + bytes([0]))
    mocker.patch('dade.xg2.xg1_level.decompress_lzhuf', return_value=code)
    meshes = decode_level_geometry(bytes(_rom()), _BASE, XG1)
    assert any(mesh.texture == key for mesh in meshes)


def test_decode_level_geometry_without_a_stream() -> None:
    rom = _rom()
    struct.pack_into('>I', rom, _BASE + 15 * 4, 0)  # Clear the stream offset.
    assert decode_level_geometry(bytes(rom), _BASE, XG1) == []


def test_decode_level_textures_reads_the_pool(mocker: MockerFixture) -> None:
    _dispatch(mocker)
    textures = decode_level_textures(bytes(_rom()), _BASE, XG1)
    assert len(textures) == 1
    assert textures[0].width == 4


def test_bank_texture_key_keeps_banks_apart() -> None:
    assert bank_texture_key(0x100, 1) == (0x100 << 32) | 1


def _bank(*, palette: bool = True) -> bytes:
    bank = bytearray(0x240)
    struct.pack_into('>I', bank, 0, 0x40 if palette else 0x38)
    struct.pack_into('>IHH', bank, 8, 0x20, 4, 4)
    struct.pack_into('>IHH', bank, 0x10, 0x30, 4, 4)
    bank[0x40:0x240] = b'\x00\x03' * 256
    return bytes(bank)


def test_read_bank_descriptors_stops_at_the_first_bad_record() -> None:
    assert read_bank_descriptors(_bank()) == [(0x20, 4, 4), (0x30, 4, 4)]


def test_read_texture_bank_decodes_every_record(mocker: MockerFixture) -> None:
    rom = bytearray(0x1000)
    struct.pack_into('>I', rom, 0x100, 0x240)
    mocker.patch('dade.xg2.xg1_level.decompress_lzhuf', return_value=_bank())
    textures = read_texture_bank(bytes(rom), 0x100)
    assert [texture.offset
            for texture in textures] == [bank_texture_key(0x100, i) for i in range(2)]


def test_read_texture_bank_ignores_an_implausible_size() -> None:
    rom = bytearray(0x1000)
    struct.pack_into('>I', rom, 0x100, 0x400000)
    assert read_texture_bank(bytes(rom), 0x100) == []


def test_read_texture_bank_without_a_descriptor_table(mocker: MockerFixture) -> None:
    rom = bytearray(0x1000)
    struct.pack_into('>I', rom, 0x100, 0x100)
    mocker.patch('dade.xg2.xg1_level.decompress_lzhuf', return_value=b'\x00' * 0x100)
    assert read_texture_bank(bytes(rom), 0x100) == []
