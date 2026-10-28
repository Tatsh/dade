from __future__ import annotations

import pytest

from dade.tgr.texture import (
    FMT_CI,
    FMT_I,
    FMT_IA,
    FMT_RGBA,
    SIZ_4B,
    SIZ_8B,
    SIZ_16B,
    SIZ_32B,
    TextureKey,
    decode,
    decode_tlut,
    rgba5551,
)


@pytest.mark.parametrize(('value', 'expected'), [(0xFFFF, (255, 255, 255, 255)),
                                                 (0x0000, (0, 0, 0, 0)), (0xF801, (255, 0, 0, 255)),
                                                 (0x003E, (0, 0, 255, 0))])
def test_rgba5551(value: int, expected: tuple[int, int, int, int]) -> None:
    assert rgba5551(value) == expected


def test_decode_tlut_reads_out_of_range_colours_as_transparent() -> None:
    assert decode_tlut(b'\xff\xff\xf8\x01', -2, 4) == [(0, 0, 0, 0), (255, 255, 255, 255),
                                                       (255, 0, 0, 255), (0, 0, 0, 0)]


@pytest.mark.parametrize(('memory', 'fmt', 'siz', 'width', 'expected'),
                         [(b'\x1f', FMT_I, SIZ_4B, 2, bytes((17,) * 4 + (255,) * 4)),
                          (b'\x80', FMT_I, SIZ_8B, 1, bytes((128,) * 4)),
                          (b'\xf1', FMT_IA, SIZ_4B, 2, bytes((255, 255, 255, 255, 0, 0, 0, 255))),
                          (b'\xf3', FMT_IA, SIZ_8B, 1, bytes((255, 255, 255, 51))),
                          (b'\x40\x80', FMT_IA, SIZ_16B, 1, bytes((64, 64, 64, 128))),
                          (b'\x01\x02\x03\x04', FMT_RGBA, SIZ_32B, 1, b'\x01\x02\x03\x04'),
                          (b'\xf8\x01', FMT_RGBA, SIZ_16B, 1, bytes((255, 0, 0, 255))),
                          (b'', FMT_RGBA, SIZ_16B, 1, bytes(4))])
def test_decode_formats(memory: bytes, fmt: int, siz: int, width: int, expected: bytes) -> None:
    assert decode(memory, TextureKey(0, -1, fmt, siz, width, 1, 0)) == expected


def test_decode_ci4_uses_palette() -> None:
    memory = b'\x01' + bytes(1) + b'\x00\x00\xf8\x01'
    assert decode(memory, TextureKey(0, 2, FMT_CI, SIZ_4B, 2, 1, 0)) == bytes(
        (0, 0, 0, 0, 255, 0, 0, 255))


def test_decode_ci8_uses_palette() -> None:
    memory = b'\x01\x00' + b'\x00\x00\x00\x3f'
    assert decode(memory, TextureKey(0, 2, FMT_CI, SIZ_8B, 1, 1, 0)) == bytes((0, 0, 255, 255))


def test_decode_ci_value_past_palette_is_transparent() -> None:
    assert decode(b'\xff\xff', TextureKey(0, 2, FMT_CI, SIZ_16B, 1, 1, 0)) == bytes(4)


@pytest.mark.parametrize(('swapped_rows', 'second_row'), [(True, (12, 13, 14, 15, 8, 9, 10, 11)),
                                                          (False, tuple(range(8, 16)))])
def test_decode_odd_rows(second_row: tuple[int, ...], *, swapped_rows: bool) -> None:
    rgba = decode(bytes(range(16)),
                  TextureKey(0, -1, FMT_I, SIZ_8B, 8, 2, 0),
                  swapped_rows=swapped_rows)
    assert tuple(rgba[32::4]) == second_row
    assert tuple(rgba[0:32:4]) == tuple(range(8))


def test_decode_line_stride() -> None:
    rgba = decode(bytes(range(32)), TextureKey(0, -1, FMT_I, SIZ_8B, 1, 2, 2), swapped_rows=False)
    assert tuple(rgba[::4]) == (0, 16)
