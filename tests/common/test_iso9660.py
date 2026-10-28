from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.common.io import BytesReader
from dade.common.iso9660 import Iso9660Image

if TYPE_CHECKING:
    from collections.abc import Callable


def test_read_file_top_level(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660(top_data=b'hello top'))
    assert image.read_file('TOP.DAT') == b'hello top'


def test_read_file_in_subdirectory(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660(ark_data=b'main ark data'))
    assert image.read_file('GEN/MAIN.ARK') == b'main ark data'


def test_read_file_is_case_insensitive(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660(ark_data=b'data'))
    assert image.read_file('gen/main.ark') == b'data'


def test_read_file_normalises_backslashes(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660(ark_data=b'data'))
    assert image.read_file('\\GEN\\MAIN.ARK') == b'data'


def test_read_file_missing_raises_key_error(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660())
    with pytest.raises(KeyError):
        image.read_file('NOPE.BIN')


def test_locate_gives_the_byte_range_of_a_files_extent(make_iso9660: Callable[..., bytes]) -> None:
    raw = make_iso9660(ark_data=b'main ark data')
    image = Iso9660Image.from_bytes(raw)
    offset, size = image.locate('GEN/MAIN.ARK')
    assert size == len(b'main ark data')
    assert raw[offset:offset + size] == b'main ark data'


def test_locate_raises_for_a_file_that_is_not_there(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660())
    with pytest.raises(KeyError):
        image.locate('NOPE.BIN')


def test_iter_files_lists_all(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660(top_data=b'ab', ark_data=b'abcd'))
    assert list(image.iter_files()) == [('GEN/MAIN.ARK', 4), ('TOP.DAT', 2)]


def test_contains(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image.from_bytes(make_iso9660())
    assert image.contains('gen/main.ark')
    assert not image.contains('missing.bin')


def test_from_reader(make_iso9660: Callable[..., bytes]) -> None:
    image = Iso9660Image(BytesReader(make_iso9660(top_data=b'via reader')))
    assert image.read_file('TOP.DAT') == b'via reader'


def test_missing_cd001_raises(make_iso9660: Callable[..., bytes]) -> None:
    image = bytearray(make_iso9660())
    image[16 * 2048 + 1:16 * 2048 + 6] = b'XXXXX'
    with pytest.raises(InvalidFormatError, match='CD001'):
        Iso9660Image.from_bytes(bytes(image))


def test_extent_out_of_range_raises(make_iso9660: Callable[..., bytes]) -> None:
    image = bytearray(make_iso9660())
    # Point the root directory record's extent LBA far past the end of the image.
    image[16 * 2048 + 156 + 2:16 * 2048 + 156 + 6] = (0xFFFF).to_bytes(4, 'little')
    with pytest.raises(InvalidFormatError, match='outside the image'):
        Iso9660Image.from_bytes(bytes(image))


def _joliet_record(identifier: bytes, extent: int, size: int, *, is_dir: bool) -> bytes:
    length = 33 + len(identifier) + (1 - len(identifier) % 2)
    record = bytearray(length)
    record[0] = length
    record[2:10] = extent.to_bytes(4, 'little') + extent.to_bytes(4, 'big')
    record[10:18] = size.to_bytes(4, 'little') + size.to_bytes(4, 'big')
    record[25] = 0x02 if is_dir else 0x00
    record[32] = len(identifier)
    record[33:33 + len(identifier)] = identifier
    return bytes(record)


def _joliet_image(escape: bytes = b'%/E') -> bytes:
    block = 2048
    image = bytearray(24 * block)

    def descriptor(type_: int, root: int) -> bytes:
        sector = bytearray(block)
        sector[0:6] = bytes((type_,)) + b'CD001'
        sector[6] = 1
        sector[128:132] = block.to_bytes(2, 'little') + block.to_bytes(2, 'big')
        if type_ == 2:
            sector[88:91] = escape
        sector[156:190] = _joliet_record(b'\x00', root, block, is_dir=True)
        return bytes(sector)

    def directory(lba: int, parent: int, *records: bytes) -> None:
        extent = (_joliet_record(b'\x00', lba, block, is_dir=True) +
                  _joliet_record(b'\x01', parent, block, is_dir=True) + b''.join(records))
        image[lba * block:lba * block + len(extent)] = extent

    image[16 * block:17 * block] = descriptor(1, 19)
    image[17 * block:18 * block] = descriptor(2, 20)
    image[18 * block:18 * block + 6] = b'\xffCD001'
    directory(19, 19, _joliet_record(b'README.TXT;1', 22, 5, is_dir=False))
    directory(20, 20, _joliet_record('Data'.encode('utf-16-be'), 21, block, is_dir=True),
              _joliet_record('ReadMe.txt;1'.encode('utf-16-be'), 22, 5, is_dir=False))
    directory(21, 20, _joliet_record('Long File Name.bin'.encode('utf-16-be'), 23, 4, is_dir=False))
    image[22 * block:22 * block + 5] = b'hello'
    image[23 * block:23 * block + 4] = b'long'
    return bytes(image)


def test_joliet_tree_is_read_with_original_case() -> None:
    image = Iso9660Image.from_bytes(_joliet_image())
    assert list(image.iter_files()) == [('Data/Long File Name.bin', 4), ('ReadMe.txt', 5)]
    assert image.read_file('data/long file name.BIN') == b'long'
    assert image.contains('README.TXT')


def test_supplementary_descriptor_without_joliet_escape_is_ignored() -> None:
    image = Iso9660Image.from_bytes(_joliet_image(b'\0\0\0'))
    assert list(image.iter_files()) == [('README.TXT', 5)]
    assert image.read_file('readme.txt') == b'hello'
