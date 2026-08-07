"""Fixtures for the Interstate '76 tests."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

_EOF_MARKER = b'\x11\x00\x00'
"""Token 17 with a zero operand, which ends an LZO stream."""


def _build_archive(magic: bytes, members: tuple[tuple[str, bytes, int], ...]) -> bytes:
    """
    Build a synthetic single-block ZFS archive.

    Parameters
    ----------
    magic : bytes
        The four-byte archive magic.
    members : tuple[tuple[str, bytes, int], ...]
        Name, payload, and flags for each member.

    Returns
    -------
    bytes
        The archive.
    """
    header = bytearray(0x20)
    header[0:4] = magic
    struct.pack_into('<I', header, 0x10, len(members))
    struct.pack_into('<I', header, 0x1C, 0)
    directory = bytearray(36 * 100)
    blob = bytearray()
    base = 0x20 + len(directory)
    for index, (name, payload, flags) in enumerate(members):
        offset = index * 36
        directory[offset:offset + 16] = name.encode().ljust(16, b'\0')
        struct.pack_into('<5I', directory, offset + 16, base + len(blob), index, len(payload), 0,
                         flags)
        blob += payload
    return bytes(header + directory + blob)


@pytest.fixture(autouse=True)
def _isolate_command_logging(mocker: MockerFixture) -> None:
    """Stop command callbacks from configuring real logging during the test run."""
    mocker.patch('bascom.cli.setup_logging')


@pytest.fixture
def palette() -> bytes:
    """Provide a 768-byte palette whose entries are predictable."""
    return bytes((index * 7 + channel * 3) % 256 for index in range(256) for channel in range(3))


@pytest.fixture
def zfsf_archive() -> bytes:
    """Provide a ZFSF archive whose members are all stored uncompressed."""
    return _build_archive(b'ZFSF',
                          (('A.GEO', b'first', 0), ('b.map', b'second!', 0), ('', b'skip', 0)))


@pytest.fixture
def zfs3_archive() -> bytes:
    """Provide a ZFS3 archive, including one member with unexpected flags."""
    return _build_archive(b'ZFS3', (('DATA.MSA', b'world', 0), ('ODD.BIN', b'verbatim', 6)))


@pytest.fixture
def multi_block_archive() -> bytes:
    """Provide a ZFSF archive whose directory spans two blocks."""
    count = 150
    header = bytearray(0x20)
    header[0:4] = b'ZFSF'
    struct.pack_into('<I', header, 0x10, count)
    first = bytearray(36 * 100)
    struct.pack_into('<I', header, 0x1C, 0x20 + len(first))
    second = bytearray(4 + 36 * 100)
    for index in range(count):
        target, base = (first, index * 36) if index < 100 else (second, 4 + (index - 100) * 36)
        target[base:base + 16] = f'f{index}.geo'.encode().ljust(16, b'\0')
        struct.pack_into('<5I', target, base + 16, 1000 + index, index, 7, 0, index % 8)
    return bytes(header + first + second)


@pytest.fixture
def lzo_stream() -> bytes:
    """Provide an LZO stream that decodes to a known literal run."""
    return b'\x03ABCDEF' + _EOF_MARKER


@pytest.fixture
def map_texture() -> bytes:
    """Provide a 6x4 palette-indexed texture."""
    return struct.pack('<II', 6, 4) + bytes(range(24))


@pytest.fixture
def codebook() -> bytes:
    """Provide a codebook of eight 4x4 blocks."""
    return struct.pack('<I', 8) + bytes((index * 3) % 256 for index in range(8 * 16))


@pytest.fixture
def vqm_texture() -> bytes:
    """Provide an 8x8 vector-quantised texture referencing ``c.cbk``."""
    return (struct.pack('<II', 8, 8) + b'c.cbk\0' + b'\0' * 10 +
            struct.pack('<4H', 0, 1, 2, 0x8000 | 0x42))


@pytest.fixture
def geo_mesh() -> bytes:
    """Provide a ``.geo`` mesh of five vertices and two quads."""
    data = bytearray(b'OEG.' + struct.pack('<8i', 0, 0, 0, 0, 0, 5, 2, 0))
    for index in range(5):
        data += struct.pack('<3f', float(index), index * 2.0, index * 3.0)
    data += b'\0' * (5 * 12)
    for _ in range(2):
        record = bytearray(0x37 + 4 * 0x10)
        struct.pack_into('<i', record, 4, 4)
        for vertex in range(4):
            struct.pack_into('<i', record, 0x37 + vertex * 0x10, vertex)
        data += record
    return bytes(data)


@pytest.fixture
def sdf_model() -> bytes:
    """Provide an ``.sdf`` whose SGEO chunk holds a root part and a child."""
    data = bytearray(b'SGEO' + b'\0' * 4 + struct.pack('<I', 2))
    for name, parent, offset in (('root', '', 1.0), ('child', 'root', 2.0)):
        record = bytearray(120)
        record[0:8] = name.encode().ljust(8, b'\0')
        struct.pack_into('<9f', record, 8, 1, 0, 0, 0, 1, 0, 0, 0, 1)
        struct.pack_into('<3f', record, 44, offset, 0.0, 0.0)
        record[56:64] = parent.encode().ljust(8, b'\0')
        data += record
    return bytes(data)


@pytest.fixture
def bwd2_container() -> bytes:
    """Provide a BWD2 container holding one nested leaf."""
    leaf = b'LEAF' + struct.pack('<I', 14) + b'abcdef'
    inner = b'WDEF' + struct.pack('<I', 8 + len(leaf)) + leaf
    return b'BWD2' + struct.pack('<I', 8 + len(inner)) + inner


@pytest.fixture
def mission() -> bytes:
    """Provide a mission whose WRLD chunk references a palette, a map, and a strip list."""
    body = b'terrain.act\0sky.map\0ab\0horizon.hzd\0'
    return b'BWD2\0\0\0\0WRLD' + struct.pack('<I', 8 + len(body)) + body


@pytest.fixture
def pix_text() -> str:
    """Provide the text of a ``.pix`` index, including one unusable line."""
    return '3\nA.GEO 0 5\nB.MAP 6 7\nshort\nC.ACT 14 3\n'


@pytest.fixture
def hzd() -> bytes:
    """Provide an ``.hzd`` strip list naming three strips of set 3."""
    return b'NH_3_01.MAP\0NH_3_02.MAP\0NH_3_03.MAP'


@pytest.fixture
def packed_dll() -> bytes:
    """Provide a minimal PE image carrying a valid packed overlay."""
    overlay_offset, optional_size = 0x1BE00, 0xE0
    pe_offset = 0x80
    data = bytearray(overlay_offset + 0x400)
    data[0:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b'PE\0\0'
    struct.pack_into('<H', data, pe_offset + 6, 1)
    struct.pack_into('<H', data, pe_offset + 20, optional_size)
    optional = pe_offset + 24
    struct.pack_into('<I', data, optional + 28, 0x10000000)
    struct.pack_into('<I', data, optional + 32, 0x1000)
    struct.pack_into('<I', data, optional + 56, 0x8000)
    struct.pack_into('<I', data, optional + 60, 0x400)
    header = optional + optional_size
    data[header:header + 8] = b'.text'.ljust(8, b'\0')
    struct.pack_into('<I', data, header + 8, 0x2000)
    struct.pack_into('<I', data, header + 12, 0x1000)
    struct.pack_into('<I', data, header + 16, 0x400)
    struct.pack_into('<I', data, header + 20, 0x400)
    overlay = (struct.pack('<IIII', 0x04181996, 1, 0x1234, 0) + struct.pack('<II', 0, 0) +
               struct.pack('<II', 16, 0x00CD00))
    data[overlay_offset:overlay_offset + len(overlay)] = overlay
    return bytes(data)


@pytest.fixture
def mrm_terrain() -> bytes:
    """Provide a ``.mrm`` terrain whose surface table names two textures."""
    data = bytearray(b'ZONV' + bytes(8) + struct.pack('<I', 2) + bytes(0x80 * 2))
    data[0x10:0x10 + 8] = b'road.bmp'
    data[0x90:0x90 + 9] = b'grass.tga'
    return bytes(data)


@pytest.fixture
def msa_world() -> bytes:
    """Provide an ``.msa`` world placing two static objects, one vehicle, and a texture."""
    return (b'Texture: wall.bmp\n'
            b'Object_Header {\nFile: tower.stf\nPos: 0 0 0\n}\n'
            b'Object_Header {\nFile: crate.stf\nPos: 1 0 0\n}\n'
            b'Object_Header {\nFile: car.vdf\nPos: 2 0 0\n}\n'
            b'Skin: body.tga\n')


@pytest.fixture
def i82_source(tmp_path: Path, msa_world: bytes, mrm_terrain: bytes) -> Path:
    """
    Provide a ZFS3 extraction tree holding one complete level, its objects, and its textures.

    Returns
    -------
    pathlib.Path
        Root of the tree, with ``data``, ``mrm``, ``bmp``, and ``tga`` subdirectories.
    """
    root = tmp_path / 'extracted'
    for name in ('bmp', 'data', 'mrm', 'tga'):
        (root / name).mkdir(parents=True)
    data, mrm = root / 'data', root / 'mrm'
    (data / 'lvl1.msa').write_bytes(msa_world)
    (mrm / 'lvl1.mrm').write_bytes(mrm_terrain)
    (data / 'orphan.msa').write_bytes(msa_world)  # No terrain, so not a level.
    (root / 'bmp' / 'wall.bmp').write_bytes(b'wall')
    (root / 'bmp' / 'road.bmp').write_bytes(b'road')
    (root / 'tga' / 'body.tga').write_bytes(b'body')
    # grass.tga is deliberately absent so the missing-texture path is exercised.
    (data / 'tower.stf').write_bytes(b'Geometry_Files {\n  tower.six\n}\n')
    (data / 'tower.sbx').write_bytes(b'mesh\x00wall.bmp\x00')
    (data / 'crate.stf').write_bytes(b'no geometry block\n')
    (data / 'car.vdf').write_bytes(b'Chassis = sedan\n')
    (data / 'sedan.cdf').write_bytes(b'Geometry_Files {\n  sedan.six\n}\n'
                                     b'Wheels {\n  wheel.six\n}\n'
                                     b'Stock_Paint = body.tga\n')
    (data / 'sedan.six').write_bytes(b'mesh\x00body.tga\x00')  # Only a .six, no .sbx.
    # wheel.sbx is deliberately absent so the missing-mesh path is exercised.
    return root
