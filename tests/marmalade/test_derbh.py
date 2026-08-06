"""Tests for :mod:`destin.marmalade.derbh`."""
from __future__ import annotations

from posixpath import basename, dirname
from typing import TYPE_CHECKING
import lzma
import struct
import zlib

from destin.marmalade.derbh import is_derbh, unpack, unpack_to_dir
from destin.marmalade.test_utils import build_derbh
import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _derbh(files: Sequence[tuple[str, bytes, int, int]]) -> bytes:
    # Like build_derbh, but with explicit stored bytes, recorded usize and method per file, so
    # compressed members and deliberate size mismatches can be assembled.
    folders = ['']
    for path, *_ in files:
        folder = dirname(path)
        if folder and folder not in folders:
            folders.append(folder)
    fc = len(files)
    header = bytearray(b'DTRZ')
    header += struct.pack('<H', fc)
    header += struct.pack('<H', len(folders))
    header += b'\x00'
    for path, *_ in files:
        header += basename(path).encode('latin-1') + b'\x00'
    for folder in folders[1:]:
        header += folder.encode('latin-1') + b'\x00'
    for path, *_ in files:
        header += struct.pack('<HHH', folders.index(dirname(path) or ''), 0, 0)
    data_start = len(header) + (fc + 1) * 16
    blobs = [blob for _, blob, _, _ in files]
    table = bytearray()
    cursor = data_start
    for _, blob, usize, method in files:
        table += struct.pack('<IIII', cursor, usize, usize, method)
        cursor += len(blob)
    table += struct.pack('<IIII', cursor, 0, 0, 0x100)  # Terminator record.
    return bytes(header + table + b''.join(blobs))


def _deflate(raw: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-15)
    return compressor.compress(raw) + compressor.flush()


def _gzip_all_flags(raw: bytes) -> bytes:
    header = bytes((0x1F, 0x8B, 8, 0x1E)) + bytes(6)  # FEXTRA | FNAME | FCOMMENT | FHCRC.
    header += struct.pack('<H', 2) + b'\x00\x00'  # FEXTRA payload.
    header += b'name\x00' + b'comment\x00' + b'\x00\x00'  # FNAME, FCOMMENT, FHCRC.
    return header + _deflate(raw)


def _gzip_plain(raw: bytes) -> bytes:
    return bytes((0x1F, 0x8B, 8, 0, 0, 0, 0, 0, 0, 0)) + _deflate(raw)


def test_is_derbh() -> None:
    assert is_derbh(b'DTRZ....')
    assert not is_derbh(b'ZZZZ')
    assert not is_derbh(b'')


def test_roundtrip_single_file() -> None:
    archive = build_derbh([('hello.txt', b'hi there')])
    entries = list(unpack(archive))
    assert len(entries) == 1
    assert entries[0].path == 'hello.txt'
    assert entries[0].data == b'hi there'


def test_roundtrip_with_folders() -> None:
    archive = build_derbh([('a.bin', b'\x00\x01'), ('sub/dir/b.bin', b'payload'),
                           ('sub/c.bin', b'three')])
    got = {e.path: e.data for e in unpack(archive)}
    assert got == {'a.bin': b'\x00\x01', 'sub/dir/b.bin': b'payload', 'sub/c.bin': b'three'}


def test_unpack_rejects_non_derbh() -> None:
    with pytest.raises(ValueError, match=r'not a Derbh archive .*\.$'):
        list(unpack(b'NOPE' + b'\x00' * 32))


def test_unpack_to_dir(tmp_path: Path) -> None:
    archive = build_derbh([('x/y.bin', b'data')])
    count = unpack_to_dir(archive, tmp_path)
    assert count == 1
    assert (tmp_path / 'x' / 'y.bin').read_bytes() == b'data'


def test_decompress_gzip_member_with_all_header_flags() -> None:
    raw = b'gzip member payload'
    archive = _derbh([('g.bin', _gzip_all_flags(raw), len(raw), 0x8)])
    assert next(iter(unpack(archive))).data == raw


def test_decompress_lzma_member() -> None:
    raw = b'lzma member payload'
    archive = _derbh([('l.bin', lzma.compress(raw, format=lzma.FORMAT_ALONE), len(raw), 0x200)])
    assert next(iter(unpack(archive))).data == raw


def test_unknown_method_falls_back_to_magic_detection() -> None:
    raw = b'fallback payload'
    files = [('lz.bin', lzma.compress(raw, format=lzma.FORMAT_ALONE), len(raw), 0x300),
             ('gz.bin', _gzip_plain(raw), len(raw), 0x300),
             ('zl.bin', zlib.compress(raw), len(raw), 0x300),
             ('st.bin', b'\x00plain bytes', len(b'\x00plain bytes'), 0x300)]
    got = {entry.path: entry.data for entry in unpack(_derbh(files))}
    assert got['lz.bin'] == raw
    assert got['gz.bin'] == raw
    assert got['zl.bin'] == raw
    assert got['st.bin'] == b'\x00plain bytes'


def test_empty_file_yields_empty_bytes() -> None:
    got = {
        entry.path: entry.data
        for entry in unpack(build_derbh([('a.bin', b'data'), ('empty.bin', b'')]))
    }
    assert got['empty.bin'] == b''


def test_size_mismatch_is_tolerated() -> None:
    # A recorded uncompressed size larger than the stored bytes triggers the mismatch warning but
    # still yields the available data.
    archive = _derbh([('a.bin', b'short', 999, 0x100)])
    assert next(iter(unpack(archive))).data == b'short'


def _short_garbage_archive() -> bytes:
    header = bytearray(b'DTRZ')
    header += struct.pack('<H', 1) + struct.pack('<H', 1) + b'\x00'
    header += b'a\x00'
    header += struct.pack('<HHH', 0, 0, 0)
    return bytes(header + b'\xff' * 20)


def _far_offset_archive() -> bytes:
    n = 8192
    header = bytearray(b'DTRZ')
    header += struct.pack('<H', 1) + struct.pack('<H', 1) + b'\x00'
    header += b'a\x00'
    header += struct.pack('<HHH', 0, 0, 0)
    header += struct.pack('<IIII', n - 4, 0, 0, 0x100)  # Valid record, but far past the table.
    header += struct.pack('<IIII', 0, 0, 0, 0)  # Invalid second record.
    return bytes(header) + b'\x00' * (n - len(header))


@pytest.mark.parametrize('archive', [_short_garbage_archive(), _far_offset_archive()])
def test_unpack_raises_when_location_table_unfindable(archive: bytes) -> None:
    with pytest.raises(ValueError, match=r'Could not locate'):
        list(unpack(archive))
