from __future__ import annotations

import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.common.io import BytesReader
from dade.itgps2.pck import PCKEntry, read_directory, read_entry
from dade.itgps2.test_utils import pck_pack

_FILES = {'Songs/A/A.sm': b'#TITLE:A;' * 20, 'Themes/x/metrics.ini': b'[Global]\n'}


@pytest.mark.parametrize('itg2', [True, False])
def test_read_directory_reads_both_layouts(*, itg2: bool) -> None:
    data = pck_pack(_FILES, itg2=itg2, name='sng1')
    name, entries = read_directory(BytesReader(data))
    assert name == 'sng1'
    assert [entry.path for entry in entries] == list(_FILES)
    assert [read_entry(BytesReader(data), entry) for entry in entries] == list(_FILES.values())


def test_read_entry_inflates_and_honours_the_base() -> None:
    data = b'pad' + pck_pack(_FILES, compressed=('Songs/A/A.sm',))
    reader = BytesReader(data)
    _, entries = read_directory(reader, 3, len(data) - 3)
    assert entries[0].compressed
    assert entries[0].size < entries[0].length
    assert read_entry(reader, entries[0], 3) == _FILES['Songs/A/A.sm']


def test_read_entry_rejects_a_wrong_length() -> None:
    data = pck_pack(_FILES, compressed=('Songs/A/A.sm',))
    _, entries = read_directory(BytesReader(data))
    with pytest.raises(InvalidFormatError, match='inflates to'):
        read_entry(BytesReader(data), entries[0]._replace(length=1))


def test_read_entry_reads_stored_bytes() -> None:
    entry = PCKEntry('a', 1, 2, 2, compressed=False)
    assert read_entry(BytesReader(b'abcd'), entry) == b'bc'


@pytest.mark.parametrize('data', [b'NOPE' + bytes(0x84), b'PCKF'])
def test_read_directory_rejects_a_bad_magic(data: bytes) -> None:
    with pytest.raises(InvalidFormatError, match='Not a PCK'):
        read_directory(BytesReader(data))


@pytest.mark.parametrize('directory', [
    struct.pack('<5I', 1, 1, 0x200, 1, 2) + b'a',
    struct.pack('<5I', 1, 1, 0x200, 99, 0),
    struct.pack('<5I', 1, 1, 0x10, 1, 0) + b'a',
    b'\0' * 4,
])
def test_read_directory_rejects_unknown_layouts(directory: bytes) -> None:
    data = b'PCKF' + bytes(0x80) + struct.pack('<I', 1) + directory
    with pytest.raises(InvalidFormatError, match='neither known layout'):
        read_directory(BytesReader(data.ljust(0x100, b'\0')), size=0x100)


def test_read_directory_rejects_more_entries_than_it_stores() -> None:
    data = b'PCKF' + bytes(0x80) + (1000).to_bytes(4, 'little') + bytes(8)
    with pytest.raises(InvalidFormatError, match='neither known layout'):
        read_directory(BytesReader(data))
