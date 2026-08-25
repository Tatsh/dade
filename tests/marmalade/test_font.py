"""Tests for :mod:`dade.marmalade.font`."""
from __future__ import annotations

import struct

from dade.marmalade.font import decode_font
from dade.marmalade.test_utils import build_font


def _font_with_unmatched_palette() -> bytes:
    # A valid header followed by a palette region that never satisfies the alpha probe (entry 0
    # transparent, some entry opaque), so the probe loop falls through to the initial offset.
    off = 0x10
    pitch, height = 2, 2
    body = bytearray(off + 13 + pitch * height)
    struct.pack_into('<H', body, off + 3, pitch * 2)
    struct.pack_into('<H', body, off + 5, height)
    struct.pack_into('<H', body, off + 7, pitch)
    return bytes(body) + b'\xff' * 34


def test_decode_font_atlas() -> None:
    img = decode_font(build_font(pitch=3, height=2))
    assert img is not None
    assert img.mode == 'RGBA'
    assert img.size == (6, 2)
    # Entry 0 is transparent; pixel (0, 0) maps to atlas nibble 0 -> palette entry 0.
    assert img.getpixel((0, 0)) == (0, 0, 0, 0)


def test_decode_font_odd_width_skips_trailing_pixel() -> None:
    # An odd atlas width exercises the ``x + 1 < w`` guard on the high nibble.
    img = decode_font(build_font(pitch=1, height=1))
    assert img is not None
    assert img.size == (2, 1)


def test_returns_none_without_header() -> None:
    assert decode_font(b'\x00' * 0x60) is None


def test_returns_none_for_body_too_short_for_header() -> None:
    assert decode_font(b'\x00' * 20) is None


def test_decodes_with_fallback_palette_offset() -> None:
    img = decode_font(_font_with_unmatched_palette())
    assert img is not None
    assert img.size == (4, 2)
