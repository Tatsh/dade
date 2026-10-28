from __future__ import annotations

from typing import TYPE_CHECKING
import hashlib
import zlib

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.tgr.rom import RELEASES, Release, decompress, identify, normalize, read_name, scan

if TYPE_CHECKING:
    from collections.abc import Sequence

_Z64 = b'\x80\x37\x12\x40'


def _asset(*chunks: bytes) -> bytes:
    body = b''
    for index, chunk in enumerate(chunks):
        stream = zlib.compress(chunk)
        body += len(stream).to_bytes(4, 'big') + stream
        if len(stream) % 2 and index < len(chunks) - 1:
            body += b'\0'
    return (8 + len(body)).to_bytes(4, 'big') + sum(map(len, chunks)).to_bytes(4, 'big') + body


def _raw_asset(size: int, streams: Sequence[bytes]) -> bytes:
    body = b''.join(len(s).to_bytes(4, 'big') + s for s in streams)
    return (8 + len(body)).to_bytes(4, 'big') + size.to_bytes(4, 'big') + body


def _cartridge(code: bytes) -> bytes:
    image = bytearray(0x100)
    image[0:4] = _Z64
    image[0x20:0x2E] = b'TOP GEAR RALLY'
    image[0x3B:0x3F] = code
    return bytes(image)


def test_normalize_big_endian_is_unchanged() -> None:
    assert normalize(_Z64 + b'abcd') == _Z64 + b'abcd'


def test_normalize_byte_swapped() -> None:
    assert normalize(b'\x37\x80\x40\x12badc') == _Z64 + b'abcd'


def test_normalize_little_endian() -> None:
    assert normalize(b'\x40\x12\x37\x80dcba') == _Z64 + b'abcd'


def test_normalize_rejects_other_files() -> None:
    with pytest.raises(InvalidFormatError, match='Nintendo 64'):
        normalize(b'PK\x03\x04')


def test_identify_rejects_other_games() -> None:
    with pytest.raises(InvalidFormatError, match='Not a Top Gear Rally'):
        identify(bytes(0x100))


def test_identify_rejects_unknown_code() -> None:
    with pytest.raises(InvalidFormatError, match='Unknown game code `XXXX`'):
        identify(_cartridge(b'XXXX'))


def test_identify_rejects_modified_image() -> None:
    with pytest.raises(InvalidFormatError, match='does not match the us release'):
        identify(_cartridge(b'NGRE'))


def test_identify_accepts_matching_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    image = _cartridge(b'NTST')
    release = Release('xx', hashlib.sha1(image, usedforsecurity=False).hexdigest(), 0, 0, 0)
    monkeypatch.setitem(RELEASES, 'NTST', release)
    assert identify(image) == release


def test_decompress_chunks() -> None:
    asset = _asset(b'first', b'second-chunk')
    found = decompress(b'\0\0' + asset + b'tail', 2)
    assert found.data == b'firstsecond-chunk'
    assert found.offset == 2
    assert found.end == 2 + len(asset)


@pytest.mark.parametrize(
    ('image', 'match'), [(bytes(8), 'No asset'), ((100).to_bytes(4, 'big') + bytes(16), 'No asset'),
                         ((16).to_bytes(4, 'big') + bytes(12), 'No asset'),
                         (_raw_asset(4, [b'\x78\x9c' + b'garbage!']), 'malformed'),
                         (_raw_asset(4, [b'']), 'malformed'),
                         (_raw_asset(4, [zlib.compress(b'data')[:-2]]), 'malformed'),
                         (_raw_asset(4, [zlib.compress(b'data') + b'xx']), 'malformed'),
                         (_raw_asset(9, [zlib.compress(b'data')]), 'inflates to 4 bytes, not 9')])
def test_decompress_rejects(image: bytes, match: str) -> None:
    with pytest.raises(InvalidFormatError, match=match):
        decompress(image, 0)


def test_scan_finds_assets_and_skips_false_matches() -> None:
    first = _asset(b'one' * 50, b'two' * 50)
    second = _asset(b'three')
    image = (bytes(0x20) + first + bytes(0x20 - len(first) % 2) + bytes(13) + b'\x78\x9c' +
             bytes(15) + b'\xff\xff\xff\xff' + bytes(4) + b'\x78\x9c' + bytes(16) + second)
    assets = scan(image, 0x10)
    assert [a.data for a in assets] == [b'one' * 50 + b'two' * 50, b'three']
    assert assets[0].offset == 0x20


def test_read_name() -> None:
    image = bytes(0x1010) + b'Hello\0World'
    assert read_name(image, 0x80200010) == 'Hello'
