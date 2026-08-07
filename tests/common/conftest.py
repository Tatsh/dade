from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

_BLOCK_SIZE = 2048
_ROOT_LBA = 18
_GEN_LBA = 19
_TOP_DATA_LBA = 20
_ARK_DATA_LBA = 21
_TOTAL_SECTORS = 22


def _iso_record(identifier: bytes, extent: int, size: int, *, is_dir: bool) -> bytes:
    length = 33 + len(identifier)
    if length % 2:
        length += 1
    record = bytearray(length)
    record[0] = length
    struct.pack_into('<I', record, 2, extent)
    struct.pack_into('>I', record, 6, extent)
    struct.pack_into('<I', record, 10, size)
    struct.pack_into('>I', record, 14, size)
    record[25] = 0x02 if is_dir else 0x00
    record[32] = len(identifier)
    record[33:33 + len(identifier)] = identifier
    return bytes(record)


def _iso_extent(records: Iterable[bytes]) -> bytes:
    extent = bytearray(_BLOCK_SIZE)
    position = 0
    for record in records:
        extent[position:position + len(record)] = record
        position += len(record)
    return bytes(extent)


def _iso_wrap_sectors(iso: bytes, mode: str) -> bytes:
    match mode.upper():
        case 'MODE1/2352':
            prefix, suffix = 16, 288
        case 'MODE2/2352':
            prefix, suffix = 24, 280
        case _:  # MODE1/2048.
            prefix, suffix = 0, 0
    return b''.join(
        bytes(prefix) + iso[start:start + _BLOCK_SIZE] + bytes(suffix)
        for start in range(0, len(iso), _BLOCK_SIZE))


@pytest.fixture
def make_ps2_icon() -> Callable[..., bytes]:
    """
    Build a PS2 3D icon (``.ico``/``.icn``).

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``vertices``, ``anim``, and ``magic`` values.
    """
    def build(*, vertices: int = 3, anim: int = 1, magic: int = 0x10000) -> bytes:
        stride = 8 * anim + 16
        out = bytearray(struct.pack('<4I', magic, anim, 0, 0) + struct.pack('<I', vertices))
        for i in range(vertices):
            vertex = bytearray(stride)
            struct.pack_into('<3h', vertex, 0, i * 100, i * 200, i * 300)
            struct.pack_into('<3h', vertex, 8 * anim, 0, 4096, 0)
            struct.pack_into('<2h', vertex, 8 * anim + 8, i * 512, i * 256)
            out += vertex
        return bytes(out) + bytes(range(256)) * (0x8000 // 256)

    return build


@pytest.fixture
def make_icon_sys() -> Callable[..., bytes]:
    """
    Build a PS2 ``icon.sys`` save-metadata file.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``title`` and ``magic`` values.
    """
    def build(*, title: str = 'AMPLITUDE', magic: bytes = b'PS2D') -> bytes:
        out = bytearray(0x1C8)
        out[0:4] = magic
        struct.pack_into('<H', out, 6, 5)
        struct.pack_into('<I', out, 0xC, 32)
        encoded = title.encode('shift_jis')
        out[0xC0:0xC0 + len(encoded)] = encoded
        out[0x108:0x108 + 10] = b'normal.ico'
        out[0x148:0x148 + 8] = b'copy.ico'
        out[0x188:0x188 + 10] = b'delete.ico'
        return bytes(out)

    return build


@pytest.fixture
def make_iso9660() -> Callable[..., bytes]:
    """
    Build a minimal valid ISO 9660 image.

    The image has a top-level file ``TOP.DAT`` and a ``GEN`` subdirectory holding ``MAIN.ARK``.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``top_data`` and ``ark_data`` values.
    """
    def build(*, top_data: bytes = b'TOP DATA', ark_data: bytes = b'ARK DATA') -> bytes:
        image = bytearray(_TOTAL_SECTORS * _BLOCK_SIZE)
        pvd = bytearray(_BLOCK_SIZE)
        pvd[0:6] = b'\x01CD001'
        pvd[6] = 1
        struct.pack_into('<H', pvd, 128, _BLOCK_SIZE)
        struct.pack_into('>H', pvd, 130, _BLOCK_SIZE)
        root_record = _iso_record(b'\x00', _ROOT_LBA, _BLOCK_SIZE, is_dir=True)
        pvd[156:156 + len(root_record)] = root_record
        image[16 * _BLOCK_SIZE:17 * _BLOCK_SIZE] = pvd
        terminator = bytearray(_BLOCK_SIZE)
        terminator[0:6] = b'\xffCD001'
        terminator[6] = 1
        image[17 * _BLOCK_SIZE:18 * _BLOCK_SIZE] = terminator
        image[_ROOT_LBA * _BLOCK_SIZE:(_ROOT_LBA + 1) * _BLOCK_SIZE] = _iso_extent(
            (_iso_record(b'\x00', _ROOT_LBA, _BLOCK_SIZE,
                         is_dir=True), _iso_record(b'\x01', _ROOT_LBA, _BLOCK_SIZE, is_dir=True),
             _iso_record(b'GEN', _GEN_LBA, _BLOCK_SIZE, is_dir=True),
             _iso_record(b'TOP.DAT;1', _TOP_DATA_LBA, len(top_data), is_dir=False)))
        image[_GEN_LBA * _BLOCK_SIZE:(_GEN_LBA + 1) * _BLOCK_SIZE] = _iso_extent(
            (_iso_record(b'\x00', _GEN_LBA, _BLOCK_SIZE,
                         is_dir=True), _iso_record(b'\x01', _ROOT_LBA, _BLOCK_SIZE, is_dir=True),
             _iso_record(b'MAIN.ARK;1', _ARK_DATA_LBA, len(ark_data), is_dir=False)))
        image[_TOP_DATA_LBA * _BLOCK_SIZE:_TOP_DATA_LBA * _BLOCK_SIZE + len(top_data)] = top_data
        image[_ARK_DATA_LBA * _BLOCK_SIZE:_ARK_DATA_LBA * _BLOCK_SIZE + len(ark_data)] = ark_data
        return bytes(image)

    return build


@pytest.fixture
def make_cuebin(tmp_path: Path) -> Callable[..., Path]:
    """
    Wrap ISO 9660 bytes into a cue/bin pair on disk.

    Returns
    -------
    collections.abc.Callable[..., pathlib.Path]
        A callable taking the ISO bytes and a keyword ``mode``, returning the ``.cue`` path.
    """
    def build(iso: bytes, *, mode: str = 'MODE1/2352') -> Path:
        (tmp_path / 'image.bin').write_bytes(_iso_wrap_sectors(iso, mode))
        cue = tmp_path / 'image.cue'
        cue.write_text(
            f'REM GENERATED\nFILE "image.bin" BINARY\n  TRACK 01 {mode}\n    INDEX 01 00:00:00\n')
        return cue

    return build
