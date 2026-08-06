"""Tests for :mod:`destin.xg2.images`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from PIL import Image
from destin.xg2.images import (
    TLUT_SIZE,
    bmp_to_png,
    decode_ci,
    decode_i8,
    decode_rgba16,
    read_tlut,
    rgba5551,
    write_png,
)
import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(('value', 'expected'), [(0x0000, b'\x00\x00\x00\x00'),
                                                 (0xFFFF, b'\xff\xff\xff\xff'),
                                                 (0x0001, b'\x00\x00\x00\xff'),
                                                 (0xF801, b'\xff\x00\x00\xff'),
                                                 (0x07C1, b'\x00\xff\x00\xff'),
                                                 (0x003F, b'\x00\x00\xff\xff')])
def test_rgba5551(value: int, expected: bytes) -> None:
    assert rgba5551(value) == expected


def test_rgba5551_alpha_bit_is_all_or_nothing() -> None:
    assert rgba5551(0xFFFE)[3] == 0
    assert rgba5551(0xFFFF)[3] == 255


def test_read_tlut_reads_every_entry(palette_bytes: bytes) -> None:
    assert len(read_tlut(palette_bytes, 0, TLUT_SIZE)) == TLUT_SIZE


def test_read_tlut_stops_at_the_end_of_the_buffer() -> None:
    assert len(read_tlut(b'\x00\x01\x00\x03', 0, TLUT_SIZE)) == 2


def test_read_tlut_respects_byte_order() -> None:
    data = struct.pack('>H', 0xF801)
    assert read_tlut(data, 0, 1) == [rgba5551(0xF801)]
    assert read_tlut(data, 0, 1, '<') == [rgba5551(0x01F8)]


def test_decode_ci_8bpp_maps_indices() -> None:
    tlut = [b'\x01\x02\x03\x04', b'\x05\x06\x07\x08']
    assert decode_ci(b'\x00\x01', 0, 2, 1, tlut, 8, 2) == b'\x01\x02\x03\x04\x05\x06\x07\x08'


def test_decode_ci_4bpp_takes_the_high_nibble_first() -> None:
    tlut = [b'\x00\x00\x00\x00', b'\xff\xff\xff\xff']
    assert decode_ci(b'\x10', 0, 2, 1, tlut, 4, 1) == b'\xff\xff\xff\xff\x00\x00\x00\x00'


def test_decode_ci_out_of_range_index_is_transparent() -> None:
    assert decode_ci(b'\x05', 0, 1, 1, [b'\xff\xff\xff\xff'], 8, 1) == b'\x00\x00\x00\x00'


def test_decode_ci_honours_stride() -> None:
    tlut = [b'\x00\x00\x00\x00', b'\xff\xff\xff\xff']
    # Two rows of one visible pixel each, with one padding byte per row.
    assert decode_ci(b'\x01\x00\x01\x00', 0, 1, 2, tlut, 8, 2) == b'\xff\xff\xff\xff' * 2


def test_decode_ci_past_the_buffer_uses_index_zero() -> None:
    tlut = [b'\x11\x22\x33\x44']
    assert decode_ci(b'', 0, 1, 1, tlut, 8, 1) == b'\x11\x22\x33\x44'


def test_decode_rgba16_respects_byte_order() -> None:
    data = struct.pack('>H', 0xF801)
    assert decode_rgba16(data, 0, 1, 1, 2) == rgba5551(0xF801)
    assert decode_rgba16(data, 0, 1, 1, 2, '<') == rgba5551(0x01F8)


def test_decode_rgba16_leaves_missing_texels_transparent() -> None:
    assert decode_rgba16(b'', 0, 2, 1, 4) == b'\x00' * 8


def test_decode_i8_is_opaque_grey() -> None:
    assert decode_i8(b'\x00\x80', 2, 1) == b'\x00\x00\x00\xff\x80\x80\x80\xff'


def test_write_png_round_trips(tmp_path: Path) -> None:
    rgba = b'\xff\x00\x00\xff\x00\xff\x00\xff'
    path = tmp_path / 'out.png'
    write_png(path, 2, 1, rgba)
    with Image.open(path) as image:
        assert image.size == (2, 1)
        assert image.convert('RGBA').tobytes() == rgba


def _build_bmp(width: int, height: int, bpp: int = 8) -> bytes:
    stride = (width + 3) & ~3
    palette = b''.join(bytes((i, i, i, 0)) for i in range(TLUT_SIZE))
    pixels = bytes(bytearray(range(width)) + bytes(stride - width)) * abs(height)
    offset = 14 + 40 + len(palette)
    header = b'BM' + struct.pack('<IHHI', offset + len(pixels), 0, 0, offset)
    info = struct.pack('<IiiHHIIiiII', 40, width, height, 1, bpp, 0, len(pixels), 0, 0, TLUT_SIZE,
                       0)
    return header + info + palette + pixels


def test_bmp_to_png_converts_eight_bit(tmp_path: Path) -> None:
    source = tmp_path / 'in.bmp'
    source.write_bytes(_build_bmp(4, 2))
    destination = tmp_path / 'out.png'
    assert bmp_to_png(source, destination)
    with Image.open(destination) as image:
        assert image.size == (4, 2)


def test_bmp_to_png_flips_bottom_up_rows(tmp_path: Path) -> None:
    source = tmp_path / 'in.bmp'
    source.write_bytes(_build_bmp(4, -2))
    top_down = tmp_path / 'top.png'
    assert bmp_to_png(source, top_down)
    source.write_bytes(_build_bmp(4, 2))
    bottom_up = tmp_path / 'bottom.png'
    assert bmp_to_png(source, bottom_up)
    assert top_down.read_bytes() != b''
    assert bottom_up.read_bytes() != b''


def test_bmp_to_png_rejects_other_depths(tmp_path: Path) -> None:
    source = tmp_path / 'in.bmp'
    source.write_bytes(_build_bmp(4, 2, bpp=24))
    assert not bmp_to_png(source, tmp_path / 'out.png')


def test_bmp_to_png_rejects_a_non_bitmap(tmp_path: Path) -> None:
    source = tmp_path / 'in.bmp'
    source.write_bytes(b'RIFF' + b'\x00' * 64)
    assert not bmp_to_png(source, tmp_path / 'out.png')
