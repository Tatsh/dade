from __future__ import annotations

from typing import TYPE_CHECKING
import bz2
import struct
import zlib

from destin.bitrock.exceptions import (
    CorruptArchiveError,
    DecryptionError,
    MemberNotFoundError,
    SignatureNotFoundError,
    UnsupportedCompressionError,
)
from destin.bitrock.sansio import BytesReader, CookFS, decompress_page, parse_fs_index
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


def test_bytes_reader_size_and_read() -> None:
    reader = BytesReader(b'0123456789')
    assert reader.size == 10
    assert reader.read(2, 3) == b'234'


def test_decompress_page_empty() -> None:
    assert decompress_page(b'') == b''


def test_decompress_page_none() -> None:
    assert decompress_page(b'\x00hello') == b'hello'


def test_decompress_page_zlib() -> None:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    body = compressor.compress(b'payload' * 4) + compressor.flush()
    assert decompress_page(b'\x01' + body) == b'payload' * 4


def test_decompress_page_bz2() -> None:
    stream = bz2.compress(b'payload' * 4)
    body = b'\x02' + struct.pack('>I', len(b'payload' * 4)) + stream
    assert decompress_page(body) == b'payload' * 4


def test_decompress_page_unsupported() -> None:
    with pytest.raises(UnsupportedCompressionError, match='compression id 255'):
        decompress_page(b'\xff' + b'anything')


def test_parse_fs_index_bad_magic() -> None:
    with pytest.raises(CorruptArchiveError, match='index magic'):
        parse_fs_index(b'NOTCFS20' + bytes(8))


def test_parse_fs_index_truncated() -> None:
    with pytest.raises(CorruptArchiveError, match='Truncated'):
        parse_fs_index(b'CFS2.200' + struct.pack('>i', 5))


def test_parse_fs_index_skips_metadata_without_separator() -> None:
    # An empty directory followed by a metadata entry that has no key/value NUL separator.
    blob = b'noseparator'
    index = (b'CFS2.200' + struct.pack('>i', 0) + struct.pack('>i', 1) +
             struct.pack('>I', len(blob)) + blob)
    assert parse_fs_index(index) == {}


def test_cookfs_namelist_and_iter(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_cookfs({'a': b'1', 'b/c': b'22'})))
    assert cookfs.namelist == ('a', 'b/c')
    assert tuple(cookfs) == ('a', 'b/c')


def test_cookfs_read_and_get_size(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_cookfs({'a': b'hello'})))
    assert cookfs.read('a') == b'hello'
    assert cookfs.get_size('a') == 5


def test_cookfs_merges_big_file(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(
        BytesReader(
            build_cookfs({
                'big': b'A' * 8,
                'big___bitrockBigFile1': b'B' * 4,
                'big___bitrockBigFile2': b'C' * 2,
            })))
    assert cookfs.namelist == ('big',)
    assert cookfs.read('big') == b'A' * 8 + b'B' * 4 + b'C' * 2
    assert cookfs.get_size('big') == 14


def test_cookfs_read_missing(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_cookfs({'a': b'1'})))
    with pytest.raises(MemberNotFoundError, match='nope'):
        cookfs.read('nope')


def test_cookfs_get_size_missing(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_cookfs({'a': b'1'})))
    with pytest.raises(MemberNotFoundError, match='nope'):
        cookfs.get_size('nope')


def test_cookfs_page_out_of_range(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_cookfs({'a': b'1'})))
    with pytest.raises(CorruptArchiveError, match='out of range'):
        cookfs.page(99)


def test_cookfs_page_cached(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_cookfs({'a': b'cached'})))
    assert cookfs.page(0) == b'cached'
    assert cookfs.page(0) == b'cached'


def test_cookfs_signature_not_found() -> None:
    with pytest.raises(SignatureNotFoundError, match='signature not found'):
        CookFS(BytesReader(b'no signature here at all'))


def test_cookfs_explicit_end_offset(build_cookfs: Callable[..., bytes]) -> None:
    data = build_cookfs({'a': b'1'})
    cookfs = CookFS(BytesReader(data), end_offset=len(data))
    assert cookfs.read('a') == b'1'


def test_cookfs_invalid_suffix() -> None:
    reader = BytesReader(bytes(16) + b'CFS0002')
    with pytest.raises(CorruptArchiveError, match='suffix'):
        CookFS(reader, end_offset=16)


def test_cookfs_corrupt_directory_offset() -> None:
    suffix = struct.pack('>IIB', 1000, 1000, 0) + b'CFS0002'
    with pytest.raises(CorruptArchiveError, match='directory offset'):
        CookFS(BytesReader(suffix), end_offset=len(suffix))


def test_cookfs_corrupt_page_data_offset() -> None:
    # A valid suffix and directory, but page sizes larger than the available prefix.
    page_count = 1
    sizes = struct.pack('>I', 4096)
    directory = bytes(page_count * 16) + sizes
    suffix = struct.pack('>IIB', 0, page_count, 0) + b'CFS0002'
    body = directory + suffix
    with pytest.raises(CorruptArchiveError, match='page data offset'):
        CookFS(BytesReader(body), end_offset=len(body))


def test_cookfs_is_encrypted(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_encrypted_cookfs({'a': b'secret'}, b'pw')))
    assert cookfs.is_encrypted is True


def test_cookfs_encrypted_read_without_password(
        build_encrypted_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_encrypted_cookfs({'a': b'secret'}, b'pw')))
    with pytest.raises(DecryptionError, match='password-protected'):
        cookfs.read('a')


def test_cookfs_unlock_with_password_argument(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_encrypted_cookfs({'a': b'secret'}, b'pw')), password='pw')
    assert cookfs.read('a') == b'secret'


def test_cookfs_unlock_after_construction(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_encrypted_cookfs({'a': b'secret'}, b'pw')))
    cookfs.unlock(b'pw')
    assert cookfs.read('a') == b'secret'


def test_cookfs_unlock_wrong_password(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_encrypted_cookfs({'a': b'secret'}, b'pw')))
    with pytest.raises(DecryptionError, match='Invalid password'):
        cookfs.unlock(b'wrong')


def test_cookfs_unlock_noop_when_not_encrypted(build_cookfs: Callable[..., bytes]) -> None:
    cookfs = CookFS(BytesReader(build_cookfs({'a': b'1'})))
    cookfs.unlock(b'ignored')
    assert cookfs.read('a') == b'1'


def test_cookfs_detects_compression_fallback(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    data = build_encrypted_cookfs({'a': b'secret'}, b'pw', decompress_command=None)
    cookfs = CookFS(BytesReader(data), password='pw')
    assert cookfs.read('a') == b'secret'


def test_cookfs_compression_override(build_encrypted_cookfs: Callable[..., bytes]) -> None:
    # The tail advertises 'lzham', but the pages are zip; the override must win.
    data = build_encrypted_cookfs({'a': b'secret'}, b'pw', decompress_command='lzham')
    cookfs = CookFS(BytesReader(data), password='pw', page_compression='zip')
    assert cookfs.read('a') == b'secret'
