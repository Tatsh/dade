from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.maxpayne.ras import (
    HEADER_SIZE,
    InvalidArchiveError,
    is_intact,
    iter_members,
    member_bytes,
    read_directory,
    read_header,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def test_read_header(make_ras: Callable[..., bytes]) -> None:
    header = read_header(make_ras())
    assert header.file_count == 2
    assert header.directory_count == 2
    assert header.version == pytest.approx(1.2)
    assert header.archiver_id == 3


def test_read_header_rejects_a_foreign_file() -> None:
    with pytest.raises(InvalidArchiveError, match='Not a RAS archive'):
        read_header(b'MZ\x90\x00' + bytes(64))


def test_read_header_rejects_an_unknown_version(make_ras: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidArchiveError, match='Unsupported RAS archive version'):
        read_header(make_ras(version=1.1))


def test_read_directory_names_members(make_ras: Callable[..., bytes]) -> None:
    contents = read_directory(make_ras())
    assert [entry.path for entry in contents.entries] == ['data/a.txt', 'data/b.bin']
    assert [directory.name for directory in contents.directories] == ['\\', '\\data\\']


def test_read_directory_reads_timestamps(make_ras: Callable[..., bytes]) -> None:
    assert read_directory(make_ras()).entries[0].modified == '2001-07-11 17:54:28.000'


def test_read_directory_treats_a_zero_year_as_unset(make_ras: Callable[..., bytes]) -> None:
    contents = read_directory(make_ras(modified=False))
    assert contents.entries[0].modified is None
    assert contents.directories[0].modified is None


def test_offsets_are_cumulative(make_ras: Callable[..., bytes]) -> None:
    contents = read_directory(make_ras((('a', b'0123'), ('b', b'456789'))))
    first, second = contents.entries
    assert second.offset == first.offset + first.stored_size


def test_member_bytes(make_ras: Callable[..., bytes]) -> None:
    archive = make_ras()
    contents = read_directory(archive)
    assert member_bytes(archive, contents.entries[0]) == b'hello'
    assert member_bytes(archive, contents.entries[1]) == b'world'


def test_member_bytes_raw_keeps_wrappers(make_ras: Callable[..., bytes],
                                         make_lzss: Callable[[bytes], bytes]) -> None:
    stream = make_lzss(b'payload')
    wrapped = b'RA->' + struct.pack('<II', 7, len(stream)) + stream
    archive = make_ras((('c.dat', wrapped),))
    entry = read_directory(archive).entries[0]
    assert member_bytes(archive, entry) == b'payload'
    assert member_bytes(archive, entry, raw=True) == wrapped


def test_iter_members(make_ras: Callable[..., bytes]) -> None:
    assert [(entry.name, data) for entry, data in iter_members(make_ras())] == [('a.txt', b'hello'),
                                                                                ('b.bin', b'world')]


def test_is_intact(make_ras: Callable[..., bytes]) -> None:
    assert is_intact(make_ras())


def test_is_intact_detects_truncation(make_ras: Callable[..., bytes]) -> None:
    assert not is_intact(make_ras()[:-1])


def test_read_header_reads_the_table_checksums(make_ras: Callable[..., bytes]) -> None:
    # The two words after the header's own CRC are checksums of the decrypted tables, which holds
    # on all five shipped archives.
    import zlib

    from dade.maxpayne.crypto import decrypt
    archive = make_ras()
    header = read_header(archive)
    start = 0x2C
    files = decrypt(archive[start:start + header.file_table_size], header.seed)
    directories = decrypt(
        archive[start + header.file_table_size:start + header.file_table_size +
                header.directory_table_size], header.seed)
    assert header.file_crc == zlib.crc32(files)
    assert header.directory_crc == zlib.crc32(directories)


def test_read_header_rejects_a_truncated_archive() -> None:
    # The magic is right but there is no header behind it, which used to raise `struct.error`.
    with pytest.raises(InvalidArchiveError, match='at least'):
        read_header(b'RAS\x00' + bytes(8))


def test_read_directory_rejects_an_entry_naming_a_directory_that_is_not_there(
        make_ras: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidArchiveError, match='names directory'):
        read_directory(make_ras(directory=7))


def test_read_directory_rejects_an_archive_cut_short_of_its_tables(
        make_ras: Callable[..., bytes]) -> None:
    # Slicing a short buffer gives back a short table rather than failing, so the walk over it used
    # to die inside a name with `ValueError: subsection not found`.
    with pytest.raises(InvalidArchiveError, match='The tables need'):
        read_directory(make_ras()[:HEADER_SIZE + 10])


def test_read_directory_reports_a_table_it_cannot_walk(make_ras: Callable[..., bytes]) -> None:
    # The tables are as long as the header promised and still nonsense inside: no name ends. That
    # used to surface as a bare `ValueError` from the name reader.
    with pytest.raises(InvalidArchiveError, match='The tables will not read'):
        read_directory(make_ras(terminate=False))
