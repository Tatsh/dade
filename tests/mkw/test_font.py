"""Tests for Mario Kart World font decryption."""
from __future__ import annotations

import pytest

from dade.mkw.font import decode_font

KEY = b'\x13\x57\x9b\xdf'
MAGIC = b'\x7f\x9a\x02\x18'


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % 4] for index, value in enumerate(data))


def _encrypt(font: bytes, *, key: bytes = KEY, size: int | None = None, pad: bool = True) -> bytes:
    body = font + bytes(-len(font) % 4) if pad else font
    header = MAGIC + (len(font) if size is None else size).to_bytes(4, 'big')
    return _xor(header, key) + _xor(body, key)


@pytest.mark.parametrize(('signature', 'suffix'), [(b'\x00\x01\x00\x00', '.ttf'), (b'true', '.ttf'),
                                                   (b'OTTO', '.otf'), (b'ttcf', '.ttc')])
@pytest.mark.parametrize('pad', [True, False])
def test_decode_font_recovers_each_kind(signature: bytes, suffix: str, *, pad: bool) -> None:
    font = signature + b'glyphs'
    assert decode_font(_encrypt(font, pad=pad)) == (font, suffix)


def test_decode_font_derives_key_from_header() -> None:
    font = b'OTTO' + bytes(range(64)) + b'xyz'
    assert decode_font(_encrypt(font, key=b'\xff\x00\xa5\x5a')) == (font, '.otf')


def test_decode_font_rejects_short_data() -> None:
    with pytest.raises(ValueError, match='too short'):
        decode_font(_encrypt(b'OTT', pad=False))


@pytest.mark.parametrize('size', [0, 9])
def test_decode_font_rejects_bad_size(size: int) -> None:
    with pytest.raises(ValueError, match='recorded length'):
        decode_font(_encrypt(b'OTTO', size=size))


def test_decode_font_rejects_non_font() -> None:
    with pytest.raises(ValueError, match='does not decrypt to a font'):
        decode_font(_encrypt(b'RIFFdata'))
