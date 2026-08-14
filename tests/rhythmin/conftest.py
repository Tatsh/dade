"""Shared pytest configuration for the ``destin.rhythmin`` suite.

Every fixture builds its sample file from scratch, so the suite needs no copy of the game.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib
import struct
import zipfile

from click.testing import CliRunner
from destin.rhythmin.bfcodec import encipher
from destin.rhythmin.dialogue import POOLS
import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_IDX_BASE = 4
_FRAME_NAMES = ('TONE_00_1', 'TONE_L1_2_LIGHT', 'OVERFLOWING')
_LAYER_NAMES = ('ROOT', 'STAR')
_USER_NAMES = ('JACKET00', 'JACKET01')
# Stored as atlas u, atlas v, width, height. The third runs past the 2048-wide page on purpose.
_SPRITES = ((10, 20, 252, 252), (0, 2048, 170, 178), (2000, 0, 300, 10))
_ENTRY_FILLER = 0x7F
_MACHO_TABLE_OFFSET = 256

MACHO_VM_BASE = 0x4000
"""Virtual address the sample Mach-O image is mapped at."""
MACHO_TABLE_ADDRESS = MACHO_VM_BASE + _MACHO_TABLE_OFFSET
"""Virtual address of the sample Mach-O image's pointer table."""
MACHO_STRINGS = (b'plain ascii', 'ひみつ'.encode(), b'quotes " backslash \\ question ?', b'')
"""The strings the sample Mach-O image's pointer table points at."""
CHARA_JSON = {'Chara': [{'Id': 47, 'Name': 'ししゃも'}]}
"""The object the sample character-data file decrypts to."""


def _name_block(names: Sequence[str], start: int) -> bytes:
    """
    Build a NUL-separated name block padded so the next block is eight-byte aligned.

    Parameters
    ----------
    names : Sequence[str]
        The names to write.
    start : int
        The file offset the block begins at, which decides how much padding it needs.

    Returns
    -------
    bytes
        The block, padding included.
    """
    block = b''.join(name.encode('latin1') + b'\0' for name in names) + b'\0'
    end = start + len(block)
    return block + b'\0' * (-end % 8)


def _frame_entry(entry_type: int,
                 child: int = 0,
                 *,
                 frame_start: int = 0,
                 frame_end: int = 0,
                 position: int = 0,
                 color: int = 0) -> bytes:
    """
    Build one 0x24-byte frame entry.

    Parameters
    ----------
    entry_type : int
        The entry's type; a negative value terminates a chain.
    child : int
        The child ordinal.
    frame_start : int
        First frame of the window.
    frame_end : int
        One past the last frame of the window.
    position : int
        ``idxBase``-relative offset of the position channel.
    color : int
        ``idxBase``-relative offset of the colour channel.

    Returns
    -------
    bytes
        The entry.
    """
    return (struct.pack('<10h', entry_type, child, 1, 1, frame_start, frame_end, 0, 0, 3, 4) +
            struct.pack('<4i', position, 0, color, 0))


@pytest.fixture
def runner() -> CliRunner:
    """
    Provide a Click :py:class:`~click.testing.CliRunner` for command tests.

    Returns
    -------
    click.testing.CliRunner
        A fresh runner for invoking commands.
    """
    return CliRunner()


@pytest.fixture
def aep_index_bytes() -> bytes:
    """
    Build a small but complete AEP animation index.

    It holds three frame names with sprite records, two layers whose chains are terminated, a group
    entry pointing at a user name, and both a position and a colour channel.

    Returns
    -------
    bytes
        The index.
    """
    out = bytearray(b'\0' * 28)  # The four-byte prefix plus the 24-byte header.
    user_offset = len(out) - _IDX_BASE
    out += _name_block(_USER_NAMES, len(out))
    frame_offset = len(out) - _IDX_BASE
    out += _name_block(_FRAME_NAMES, len(out))
    for atlas_u, atlas_v, width, height in _SPRITES:
        out += struct.pack('<4h', atlas_u, atlas_v, width, height)
    layer_offset = len(out) - _IDX_BASE
    out += _name_block(_LAYER_NAMES, len(out))
    out += struct.pack('<2h', 0, 2)  # Layer ordinals: ROOT starts at entry 0, STAR at entry 2.
    out += b'\0' * 4  # Pad to a group of four ordinals.
    entries_at = len(out)
    # The channels sit past the entries and the filler that stops the entry walk.
    channels_at = entries_at + 4 * 0x24 + 0x24
    position_channel = channels_at - _IDX_BASE
    color_channel = position_channel + 3 * 8
    out += _frame_entry(0, 0, frame_end=10, position=position_channel)
    out += _frame_entry(-1, frame_end=2)
    out += _frame_entry(3, 0, frame_end=20, position=position_channel, color=color_channel)
    out += _frame_entry(-1, frame_end=2)
    out += bytes([_ENTRY_FILLER]) * 0x24
    out += struct.pack('<4h', 0, 10, 20, 0)
    out += struct.pack('<4h', 5, 30, 40, 0)
    out += struct.pack('<4h', -1, 0, 0, 0)
    out += struct.pack('<hH', 0, (20 << 8) | 10)
    out += struct.pack('<hH', 3, (0xFE << 8) | 0xFF)  # Read signed: colour -1, alpha -2.
    out += struct.pack('<hH', -1, 0)
    struct.pack_into('<hhiiiii', out, _IDX_BASE, 7, 0, frame_offset, 0, 0, layer_offset,
                     user_offset)
    return bytes(out)


@pytest.fixture
def aep_index_file(tmp_path: Path, aep_index_bytes: bytes) -> Path:
    """
    Write the sample animation index to a file.

    Returns
    -------
    pathlib.Path
        The written ``.idx``.
    """
    path = tmp_path / 'title.idx'
    path.write_bytes(aep_index_bytes)
    return path


@pytest.fixture
def treasure_map_bytes() -> bytes:
    """
    Build a four-square sugoroku board with a warp pair and a two-way link.

    Returns
    -------
    bytes
        The board file.
    """
    header = bytearray(b'\0' * 0x50)
    struct.pack_into('<BBh', header, 0, 1, 2, 4)
    header[0x04:0x04 + len('探検航海'.encode('shift_jis'))] = '探検航海'.encode('shift_jis')
    header[0x1C:0x1C + len('船出'.encode('shift_jis'))] = '船出'.encode('shift_jis')
    struct.pack_into('<i', header, 0x44, 3)
    squares = (
        ((0, 0, 0, 0, 0, -1, 1, -1, -1), 'スタート'),
        ((1, 100, 0, 4, 0, 0, 2, 3, -1), 'たからばこ<br>だ！'),  # noqa: RUF001
        ((2, 200, 0, 8, 5, 1, 3, -1, -1), 'ワープ'),
        ((3, 200, 50, 8, 5, 1, 2, -1, -1), ''),
    )
    out = bytearray(header)
    for fields, message in squares:
        record = bytearray(b'\0' * 0xAA)
        struct.pack_into('<9h', record, 0, *fields)
        text = message.encode('shift_jis')
        record[0x12:0x12 + len(text)] = text
        out += record
    return bytes(out)


@pytest.fixture
def treasure_map_file(tmp_path: Path, treasure_map_bytes: bytes) -> Path:
    """
    Write the sample board to a file.

    Returns
    -------
    pathlib.Path
        The written ``.map``.
    """
    path = tmp_path / 'map_042.map'
    path.write_bytes(treasure_map_bytes)
    return path


@pytest.fixture
def chara_file(tmp_path: Path) -> Path:
    """
    Write an encrypted character-data file whose JSON carries a trailing comma.

    Returns
    -------
    pathlib.Path
        The written ``.chr``.
    """
    path = tmp_path / 'chara001.chr'
    path.write_bytes(
        encipher(b'{"Chara": [{"Id": 47, "Name": "\\u3057\\u3057\\u3083\\u3082",},],}'))
    return path


@pytest.fixture
def standard_chart_bytes() -> bytes:
    """
    Build a standard chart with a tempo event, a tap, a hold, a bar, and an end record.

    Returns
    -------
    bytes
        The chart payload.
    """
    def record(tick: int,
               end: int,
               record_type: int,
               value: int,
               positions: Sequence[int] = (0, 0, 0, 0, 0, 0)) -> bytes:
        # Tick and end tick, the type at +0x8 with three unused bytes, the value at +0xc, then the
        # six position bytes at +0xe, for 20 bytes in all.
        return (struct.pack('<II', tick, end) + bytes([record_type, 0, 0, 0]) +
                struct.pack('<H', value) + bytes(positions))

    return (struct.pack('<f', 1.5) + record(0, 0, 2, 240) + record(0, 0, 1, 0) +
            record(500, 500, 0, 1, (10, 20, 30, 40, 50, 60)) + record(1000, 2000, 0, 2,
                                                                      (10, 20, 30, 40, 99, 60)) +
            record(0, 0, 4, 0) + record(1000, 1000, 4, 0) + record(3000, 3000, 3, 0))


@pytest.fixture
def arcade_chart_bytes() -> bytes:
    """
    Build an arcade chart with the magic header unit, taps, measures, beats, and an end unit.

    Returns
    -------
    bytes
        The chart payload.
    """
    def unit(tick: int, unit_type: int, value: int, pad: int = 0) -> bytes:
        return struct.pack('<I', tick) + bytes([pad, unit_type]) + struct.pack('<H', value)

    return (unit(0, 4, 120, ord('E')) + unit(0, 3, 0) + unit(0, 10, 0) + unit(0, 11, 0) +
            unit(100, 1, 0) + unit(200, 1, 4) + unit(300, 1, 0x0018) + unit(500, 11, 0) +
            unit(1000, 10, 0) + unit(1500, 1, 8) + unit(2000, 6, 0))


def _write_package(path: Path, chart: bytes, info: dict[str, object]) -> Path:
    """
    Write a song package holding one chart and an encrypted info plist.

    Parameters
    ----------
    path : pathlib.Path
        Where to write the package.
    chart : bytes
        The chart payload, which is enciphered here.
    info : dict[str, object]
        The song metadata.

    Returns
    -------
    pathlib.Path
        The written package.
    """
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('sheet_n', encipher(chart))
        archive.writestr('sheet_ex', encipher(chart))
        archive.writestr('info', encipher(plistlib.dumps(info, fmt=plistlib.FMT_BINARY)))
    return path


@pytest.fixture
def orb_package(tmp_path: Path, standard_chart_bytes: bytes) -> Path:
    """
    Write a standard song package.

    Returns
    -------
    pathlib.Path
        The written ``.orb``.
    """
    return _write_package(
        tmp_path / '200000007.orb',
        standard_chart_bytes,
        {
            'MusicName': 'テスト',
            'ArtistName': 'ピノキオP',  # noqa: RUF001
            'Normal': 3,
            'Ex': 9,
        })


@pytest.fixture
def acv_package(tmp_path: Path, arcade_chart_bytes: bytes) -> Path:
    """
    Write an arcade song package.

    Returns
    -------
    pathlib.Path
        The written ``.acv``.
    """
    return _write_package(tmp_path / 'ac000000001.acv', arcade_chart_bytes, {
        'MusicName': 'WORLD COLOR',
        'GenreName': 'ビタミンポップ',
        'Ex': 38,
    })


@pytest.fixture
def macho_image_all_pools() -> bytes:
    """
    Build a 32-bit Mach-O whose segment maps the real dialogue pool addresses.

    The six shipped pointer tables are exactly contiguous, so one segment based at the first
    table's address covers all 330 pointers and the strings that follow them.

    Returns
    -------
    bytes
        The image.
    """
    base = POOLS[0].address
    total = sum(spec.entry_count for spec in POOLS)
    string_offset = total * 4
    blob = bytearray()
    pointers = []
    for index in range(total):
        pointers.append(base + string_offset + len(blob))
        blob += f'message {index}'.encode() + b'\0'
    body = b''.join(struct.pack('<I', pointer) for pointer in pointers) + bytes(blob)
    header_size = 28 + 56
    segment = struct.pack('<II16sIIIIIIII', 0x1, 56, b'__TEXT', base, len(body), header_size,
                          len(body), 7, 5, 0, 0)
    header = struct.pack('<IIIIIII', 0xFEEDFACE, 12, 9, 2, 1, len(segment), 0)
    return header + segment + body


@pytest.fixture
def macho_image() -> bytes:
    """
    Build a 32-bit Mach-O image carrying one pointer table and its strings.

    The table sits at virtual address ``0x4100``, which is what
    :py:data:`tests.rhythmin.conftest.MACHO_TABLE_ADDRESS` records.

    Returns
    -------
    bytes
        The image.
    """
    body = bytearray(b'\0' * _MACHO_TABLE_OFFSET)
    string_offset = _MACHO_TABLE_OFFSET + len(MACHO_STRINGS) * 4
    blob = bytearray()
    pointers = []
    for text in MACHO_STRINGS:
        pointers.append(MACHO_VM_BASE + string_offset + len(blob))
        blob += text + b'\0'
    body += b''.join(struct.pack('<I', pointer) for pointer in pointers)
    body += blob
    segment = struct.pack('<II16sIIIIIIII', 0x1, 56, b'__TEXT', MACHO_VM_BASE, len(body), 0,
                          len(body), 7, 5, 0, 0)
    header = struct.pack('<IIIIIII', 0xFEEDFACE, 12, 9, 2, 1, len(segment), 0)
    return header + segment + b'\0' * (_MACHO_TABLE_OFFSET - len(header) - len(segment)) + bytes(
        body[_MACHO_TABLE_OFFSET:])


@pytest.fixture
def chara_json() -> dict[str, object]:
    """
    Return the object the sample character-data file decrypts to.

    Returns
    -------
    dict[str, object]
        The parsed character data.
    """
    return dict(CHARA_JSON)
