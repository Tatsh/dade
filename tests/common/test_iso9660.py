from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.io import BytesReader
from destin.common.iso9660 import Iso9660Image
from destin.common.typing import InvalidFormatError
import pytest

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
