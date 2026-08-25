"""Tests for :mod:`dade.thps2pc.pkr`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct
import zlib

import pytest

from dade.thps2pc import pkr
from dade.thps2pc.test_utils import PkrFileSpec, pkr_archive, stored_file

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_reads_header(pkr_bytes: bytes) -> None:
    archive = pkr.parse(pkr_bytes)
    assert archive.header.dir_count == 2
    assert archive.header.file_count == 3
    assert archive.header.alignment == 4
    assert archive.header.table_b_start == 16 + 2 * pkr.DIR_SIZE


def test_iter_entries_joins_directory_and_file_names(pkr_bytes: bytes) -> None:
    archive = pkr.parse(pkr_bytes)
    assert [path for path, _ in pkr.iter_entries(archive)] == [
        'data/A.PSX', 'data/B.PSX', 'newtex/C.BMP'
    ]


def test_extract_entry_returns_stored_bytes(pkr_bytes: bytes) -> None:
    archive = pkr.parse(pkr_bytes)
    payloads = [pkr.extract_entry(pkr_bytes, entry) for _, entry in pkr.iter_entries(archive)]
    assert payloads == [b'AAAA', b'BB', b'CCCCCC']


def test_extract_all_mirrors_the_tree(pkr_bytes: bytes, tmp_path: Path) -> None:
    count, total = pkr.extract_all(pkr_bytes, tmp_path)
    assert (count, total) == (3, 12)
    assert (tmp_path / 'data' / 'A.PSX').read_bytes() == b'AAAA'
    assert (tmp_path / 'newtex' / 'C.BMP').read_bytes() == b'CCCCCC'


@pytest.mark.parametrize(('data', 'match'),
                         [(b'', r'too small'),
                          (struct.pack('<4sIII', b'NOPE', 4, 0, 0), r'Bad magic')])
def test_parse_rejects_invalid_input(data: bytes, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        pkr.parse(data)


def test_parse_rejects_truncated_tables() -> None:
    with pytest.raises(ValueError, match=r'Truncated PKR'):
        pkr.parse(struct.pack('<4sIII', b'PKR2', 4, 9, 9))


@pytest.mark.parametrize(('name', 'expected'), [('/etc/passwd', r'Unsafe path'),
                                                ('../escape/', r'Unsafe path')])
def test_extract_all_rejects_escaping_paths(name: str, expected: str, tmp_path: Path) -> None:
    data = pkr_archive(((name, (stored_file('x.bin', b'x'),)),))
    with pytest.raises(pkr.UnsafePathError, match=expected):
        pkr.extract_all(data, tmp_path)


def test_extract_entry_rejects_resource_past_eof() -> None:
    data = bytearray(pkr_archive((('d/', (stored_file('a.bin', b'abcd'),)),)))
    struct.pack_into('<I', data, 16 + pkr.DIR_SIZE + 0x2C, 4096)
    archive = pkr.parse(bytes(data))
    with pytest.raises(ValueError, match=r'runs past the end'):
        pkr.extract_entry(bytes(data), archive.files[0])


def test_extract_entry_rejects_unknown_method() -> None:
    data = pkr_archive((('d/', (PkrFileSpec('a.bin', b'raw', 99, 3),)),))
    archive = pkr.parse(data)
    with pytest.raises(NotImplementedError, match=r'Unknown compression method 99'):
        pkr.extract_entry(data, archive.files[0])


@pytest.mark.parametrize(('method', 'stored', 'size', 'expected'),
                         [(pkr.CompressionMethod.RLE8, bytes((3, 0x41)), 3, b'AAA'),
                          (pkr.CompressionMethod.RLE8, bytes(
                              (2, 0x41, 2, 0x5A)), 4, b'A' * 2 + b'Z' * 2),
                          (pkr.CompressionMethod.RLE16, struct.pack('<HB', 4, 0x43), 4, b'CCCC')])
def test_extract_entry_decodes_run_length(method: int, stored: bytes, size: int,
                                          expected: bytes) -> None:
    data = pkr_archive((('d/', (PkrFileSpec('a.bin', stored, method, size),)),))
    archive = pkr.parse(data)
    assert pkr.extract_entry(data, archive.files[0]) == expected


def test_run_length_pads_with_the_last_value() -> None:
    stored = bytes((2, 0x5A))
    data = pkr_archive((('d/', (PkrFileSpec('a.bin', stored, pkr.CompressionMethod.RLE8, 5),)),))
    archive = pkr.parse(data)
    assert pkr.extract_entry(data, archive.files[0]) == b'ZZZZZ'


def test_run_length_stops_before_overflowing_the_output() -> None:
    stored = bytes((2, 0x41, 9, 0x42))
    data = pkr_archive((('d/', (PkrFileSpec('a.bin', stored, pkr.CompressionMethod.RLE8, 4),)),))
    archive = pkr.parse(data)
    assert pkr.extract_entry(data, archive.files[0]) == b'AAAA'


def test_extract_entry_inflates_zlib() -> None:
    payload = b'compressible' * 8
    compressed = zlib.compress(payload)
    spec = PkrFileSpec('a.bin', compressed, pkr.CompressionMethod.ZLIB, len(payload))
    data = pkr_archive((('d/', (spec,)),))
    archive = pkr.parse(data)
    assert pkr.extract_entry(data, archive.files[0]) == payload


def test_empty_archive_parses() -> None:
    archive = pkr.parse(pkr_archive(()))
    assert archive.dirs == ()
    assert archive.files == ()
    assert list(pkr.iter_entries(archive)) == []
