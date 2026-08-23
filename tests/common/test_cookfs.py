from __future__ import annotations

import bz2
import struct
import zlib

import pytest

from destin.bitrock.exceptions import (
    CorruptArchiveError,
    SignatureNotFoundError,
    UnsupportedCompressionError,
)
from destin.common.cookfs import (
    Block,
    decompress_page,
    locate_end_offset,
    parse_fs_index,
    parse_index,
)
from destin.common.io import BytesReader


def test_block_fields() -> None:
    block = Block(1, 2, 3)
    assert (block.page_index, block.offset, block.size) == (1, 2, 3)


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


def test_parse_index_returns_files_and_metadata() -> None:
    blob = b'key\x00value'
    index = (b'CFS2.200' + struct.pack('>i', 0) + struct.pack('>i', 1) +
             struct.pack('>I', len(blob)) + blob)
    files, metadata = parse_index(index)
    assert files == {}
    assert metadata == {'key': b'value'}


def test_locate_end_offset_explicit_is_returned() -> None:
    assert locate_end_offset(BytesReader(b'anything'), 5, 16) == 5


def test_locate_end_offset_scans_for_signature() -> None:
    data = b'prefix' + b'CFS0002' + b'trailer'
    assert locate_end_offset(BytesReader(data), None, len(data)) == len(b'prefix') + 7


def test_locate_end_offset_missing_signature() -> None:
    with pytest.raises(SignatureNotFoundError, match='signature not found'):
        locate_end_offset(BytesReader(b'no signature here'), None, 64)
