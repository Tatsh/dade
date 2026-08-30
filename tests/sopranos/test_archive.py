from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.sopranos.archive import (
    SECTOR_SIZE,
    is_disc_image,
    iter_disc_archives,
    iter_entries,
    name_hash,
    read_directory,
)

from .conftest import build_archive

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_name_hash_is_case_insensitive() -> None:
    assert name_hash('Satriales_Doors') == name_hash('satriales_doors')


def test_name_hash_matches_the_game() -> None:
    # Taken from the shipped DATA_P.FS, where this name's directory entry carries this hash.
    assert name_hash('satriales_doors') == 0x81B3FB1B


def test_read_directory_pairs_names_with_entries(tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(build_archive({'beta.txt': b'two', 'alpha.txt': b'one'}))
    entries = read_directory(archive)
    assert [entry.name for entry in entries] == ['alpha.txt', 'beta.txt']
    assert [entry.size for entry in entries] == [3, 3]
    assert all(entry.offset % SECTOR_SIZE == 0 for entry in entries)


def test_iter_entries_yields_the_stored_bytes(tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(build_archive({'one.bin': b'hello', 'two.bin': b'world'}))
    assert {
        entry.name: data
        for entry, data in iter_entries(archive)
    } == {
        'one.bin': b'hello',
        'two.bin': b'world'
    }


def test_read_directory_names_entries_the_string_table_misses(tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(build_archive({'gone.bin': b'x'}, named=False))
    entries = read_directory(archive)
    assert len(entries) == 1
    assert entries[0].name == f'unnamed/{name_hash("gone.bin"):08x}.bin'


def test_read_directory_warns_when_a_name_has_no_entry(tmp_path: Path,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    raw = bytearray(build_archive({'kept.bin': b'x'}))
    extra = b'kept.bin\0missing.bin\0'
    toc = struct.unpack('<I', raw[-4:])[0]
    rebuilt = bytearray(raw[:toc])
    rebuilt += struct.pack('<4sI', b'STR ', len(extra)) + extra
    entry = struct.pack('<4I', 0, 0, 1, name_hash('kept.bin'))
    rebuilt += struct.pack('<4sI', b'DIR ', len(entry)) + entry
    rebuilt += struct.pack('<4sI', b'END ', 0) + struct.pack('<I', toc)
    archive = tmp_path / 'a.fs'
    archive.write_bytes(bytes(rebuilt))
    with caplog.at_level('WARNING'):
        entries = read_directory(archive)
    assert [entry.name for entry in entries] == ['kept.bin']
    assert 'missing.bin' in caplog.text


def test_read_directory_rejects_a_tiny_file(tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(b'ab')
    with pytest.raises(InvalidFormatError, match='too small'):
        read_directory(archive)


def test_read_directory_rejects_an_offset_past_the_end(tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(bytes(64) + struct.pack('<I', 0xFFFF))
    with pytest.raises(InvalidFormatError, match='beyond the end'):
        read_directory(archive)


def test_read_directory_explains_a_blank_archive(tmp_path: Path) -> None:
    archive = tmp_path / 'a.fs'
    archive.write_bytes(bytes(SECTOR_SIZE * 4))
    with pytest.raises(InvalidFormatError, match='only zero bytes'):
        read_directory(archive)


def test_read_directory_rejects_a_ragged_directory_chunk(tmp_path: Path) -> None:
    payload = bytes(20)
    chunks = struct.pack('<4sI', b'DIR ', len(payload)) + payload + struct.pack('<4sI', b'END ', 0)
    body = bytes(SECTOR_SIZE)
    archive = tmp_path / 'a.fs'
    archive.write_bytes(body + chunks + struct.pack('<I', len(body)))
    with pytest.raises(InvalidFormatError, match='not a multiple of 16'):
        read_directory(archive)


def test_read_directory_rejects_a_file_without_a_directory(tmp_path: Path) -> None:
    chunks = struct.pack('<4sI', b'END ', 0)
    body = bytes(SECTOR_SIZE)
    archive = tmp_path / 'a.fs'
    archive.write_bytes(body + chunks + struct.pack('<I', len(body)))
    with pytest.raises(InvalidFormatError, match='no directory chunk'):
        read_directory(archive)


def test_is_disc_image_recognises_the_standard_identifier(tmp_path: Path) -> None:
    image = tmp_path / 'game.iso'
    raw = bytearray(0x8100)
    raw[0x8001:0x8006] = b'CD001'
    image.write_bytes(bytes(raw))
    assert is_disc_image(image)


def test_is_disc_image_rejects_anything_else(tmp_path: Path) -> None:
    plain = tmp_path / 'plain.fs'
    plain.write_bytes(b'not a disc')
    assert not is_disc_image(plain)


def test_is_disc_image_survives_an_unreadable_path(tmp_path: Path) -> None:
    assert not is_disc_image(tmp_path / 'missing.iso')


def test_iter_disc_archives_yields_only_archives(mocker: MockerFixture, tmp_path: Path) -> None:
    image = mocker.MagicMock()
    image.iter_files.return_value = [('DATA/DATA_P.FS', 10), ('DATA/README.TXT', 5)]
    image.locate.return_value = (2048, 10)
    mocker.patch('dade.sopranos.archive.MmapReader')
    mocker.patch('dade.sopranos.archive.Iso9660Image', return_value=image)
    assert list(iter_disc_archives(tmp_path / 'game.iso')) == [('DATA_P.FS', 2048, 10)]


def test_read_directory_reads_on_when_a_zero_offset_is_not_a_blank_archive(tmp_path: Path) -> None:
    # A table of contents at zero is only suspicious when the file really is empty.
    entry = struct.pack('<4I', 0, 0, 4, name_hash('a.bin'))
    names = b'a.bin\0'
    chunks = (struct.pack('<4sI', b'STR ', len(names)) + names +
              struct.pack('<4sI', b'DIR ', len(entry)) + entry + struct.pack('<4sI', b'END ', 0))
    archive = tmp_path / 'a.fs'
    archive.write_bytes(chunks + bytes(SECTOR_SIZE) + struct.pack('<I', 0))
    assert [e.name for e in read_directory(archive)] == ['a.bin']


def test_read_directory_skips_chunks_it_does_not_know(tmp_path: Path) -> None:
    junk = b'\1\2\3\4'
    entry = struct.pack('<4I', 0, 0, 1, name_hash('a.bin'))
    names = b'a.bin\0'
    chunks = (struct.pack('<4sI', b'JUNK', len(junk)) + junk +
              struct.pack('<4sI', b'STR ', len(names)) + names +
              struct.pack('<4sI', b'DIR ', len(entry)) + entry + struct.pack('<4sI', b'END ', 0))
    body = bytes(SECTOR_SIZE)
    archive = tmp_path / 'a.fs'
    archive.write_bytes(body + chunks + struct.pack('<I', len(body)))
    assert [e.name for e in read_directory(archive)] == ['a.bin']


def test_read_directory_stops_at_a_truncated_chunk_header(tmp_path: Path) -> None:
    entry = struct.pack('<4I', 0, 0, 1, name_hash('a.bin'))
    names = b'a.bin\0'
    # No END chunk: the stream simply runs out mid-header.
    chunks = (struct.pack('<4sI', b'STR ', len(names)) + names +
              struct.pack('<4sI', b'DIR ', len(entry)) + entry + b'AB')
    body = bytes(SECTOR_SIZE)
    archive = tmp_path / 'a.fs'
    archive.write_bytes(body + chunks + struct.pack('<I', len(body)))
    assert [e.name for e in read_directory(archive)] == ['a.bin']
