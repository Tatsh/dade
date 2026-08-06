"""Tests for :mod:`destin.marmalade.texture`."""
from __future__ import annotations

import struct

from destin.marmalade.test_utils import build_texture
from destin.marmalade.texture import decode_texture


def _tex_header(width: int, height: int, pitch: int) -> bytes:
    # A 13-byte body holds exactly one scan offset (off == 4), so the width/height/pitch triple
    # under test is the only candidate the decoder evaluates.
    body = bytearray(13)
    struct.pack_into('<H', body, 7, width)
    struct.pack_into('<H', body, 9, height)
    struct.pack_into('<H', body, 11, pitch)
    return bytes(body)


def test_decode_rgba() -> None:
    texels = bytes(range(16))  # 2x2 RGBA8888
    img = decode_texture(build_texture(2, 2, 4, texels))
    assert img is not None
    assert img.mode == 'RGBA'
    assert img.size == (2, 2)
    assert img.getpixel((0, 0)) == (0, 1, 2, 3)


def test_decode_rgb() -> None:
    img = decode_texture(build_texture(2, 2, 3, bytes(range(12))))
    assert img is not None
    assert img.mode == 'RGB'
    assert img.size == (2, 2)


def test_decode_rgb565() -> None:
    img = decode_texture(build_texture(2, 2, 2, bytes(range(8))))
    assert img is not None
    assert img.mode == 'RGB'
    assert img.size == (2, 2)


def test_decode_greyscale() -> None:
    img = decode_texture(build_texture(2, 2, 1, bytes(range(4))))
    assert img is not None
    assert img.mode == 'L'
    assert img.size == (2, 2)


def test_pitch_not_multiple_of_width_is_skipped() -> None:
    assert decode_texture(_tex_header(2, 2, 3)) is None


def test_unsupported_bytes_per_pixel_is_skipped() -> None:
    assert decode_texture(_tex_header(2, 2, 10)) is None


def test_texel_offset_out_of_range_is_skipped() -> None:
    assert decode_texture(_tex_header(2, 2, 2)) is None


def test_returns_none_for_garbage() -> None:
    assert decode_texture(b'\x00' * 8) is None


def test_returns_none_when_full_scan_finds_nothing() -> None:
    # A body long enough to scan every offset without an early break still yields nothing when
    # no candidate validates, exercising the loop-completion path.
    assert decode_texture(b'\x01' * 48) is None
