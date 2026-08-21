"""Tests for :py:mod:`destin.ddrsplus.pvr`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.common.exceptions import InvalidFormatError
from destin.ddrsplus.pvr import BANNER_SIZE, crop, decode_pvr, read_header
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


def test_the_header_reports_the_dimensions(make_pvr: Callable[..., bytes]) -> None:
    header = read_header(make_pvr())
    assert (header.width, header.height, header.bit_count) == (256, 64, 16)


def test_the_alpha_flag_is_read(make_pvr: Callable[..., bytes]) -> None:
    assert read_header(make_pvr()).has_alpha


def test_rgba4444_expands_each_nibble_to_a_byte(make_pvr: Callable[..., bytes]) -> None:
    # 0xD4FF is red 0xD, green 0x4, blue 0xF, alpha 0xF.
    texture = decode_pvr(make_pvr(fill=0xD4FF, height=1, width=1))
    assert texture.pixels == bytes((0xDD, 0x44, 0xFF, 0xFF))


def test_an_all_ones_channel_becomes_full_scale(make_pvr: Callable[..., bytes]) -> None:
    assert decode_pvr(make_pvr(fill=0xFFFF, height=1, width=1)).pixels == b'\xff' * 4


def test_the_decoded_size_matches_the_dimensions(make_pvr: Callable[..., bytes]) -> None:
    texture = decode_pvr(make_pvr())
    assert len(texture.pixels) == texture.width * texture.height * 4


def test_cropping_trims_to_the_requested_region(make_pvr: Callable[..., bytes]) -> None:
    cropped = crop(decode_pvr(make_pvr()), BANNER_SIZE)
    assert (cropped.width, cropped.height) == BANNER_SIZE
    assert len(cropped.pixels) == BANNER_SIZE[0] * BANNER_SIZE[1] * 4


def test_cropping_keeps_the_top_left_pixels(make_pvr: Callable[..., bytes]) -> None:
    texture = decode_pvr(make_pvr())
    assert crop(texture, (2, 2)).pixels[:4] == texture.pixels[:4]


def test_a_texture_smaller_than_the_region_is_untouched(make_pvr: Callable[..., bytes]) -> None:
    texture = decode_pvr(make_pvr(height=4, width=4))
    assert crop(texture, BANNER_SIZE) is texture


def test_a_short_file_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='Too short'):
        read_header(b'')


def test_a_file_without_the_tag_is_rejected(make_pvr: Callable[..., bytes]) -> None:
    data = bytearray(make_pvr())
    struct.pack_into('<I', data, 44, 0)
    with pytest.raises(InvalidFormatError, match='Not a PVR v2 texture'):
        read_header(bytes(data))


def test_a_mipmapped_texture_is_rejected(make_pvr: Callable[..., bytes]) -> None:
    data = bytearray(make_pvr())
    struct.pack_into('<I', data, 16, 0x8110)
    with pytest.raises(InvalidFormatError, match='mipmapped'):
        read_header(bytes(data))


def test_a_data_size_that_does_not_match_is_rejected(make_pvr: Callable[..., bytes]) -> None:
    data = bytearray(make_pvr())
    struct.pack_into('<I', data, 20, 7)
    with pytest.raises(InvalidFormatError, match='compressed'):
        read_header(bytes(data))


def test_a_texture_with_no_colour_masks_is_rejected(make_pvr: Callable[..., bytes]) -> None:
    data = bytearray(make_pvr())
    struct.pack_into('<III', data, 28, 0, 0, 0)
    with pytest.raises(InvalidFormatError, match='colour bit masks'):
        read_header(bytes(data))


_PVR_TAG = 0x21525650


def _pvr(*,
         width: int = 1,
         height: int = 1,
         flags: int = 0x8010,
         data_size: int | None = None,
         bit_count: int = 16,
         masks: tuple[int, int, int, int] = (0xF000, 0x0F00, 0x00F0, 0x000F),
         header_size: int = 52,
         body: bytes | None = None) -> bytes:
    size = width * height * bit_count // 8 if data_size is None else data_size
    header = struct.pack('<13I', header_size, height, width, 0, flags, size, bit_count, *masks,
                         _PVR_TAG, 1)
    return header + (bytes(width * height * bit_count // 8) if body is None else body)


def test_an_unexpected_header_size_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='header size'):
        read_header(_pvr(header_size=100))


def test_a_pixel_that_is_not_a_whole_byte_count_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='whole byte count'):
        read_header(_pvr(bit_count=15))


def test_a_body_shorter_than_the_declared_size_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='pixel bytes but only'):
        read_header(_pvr(width=2, height=1, bit_count=16, body=b'\x00\x00'))


def test_a_texture_without_alpha_fills_the_channel() -> None:
    # Flags without the alpha bit make the alpha reader return full scale.
    texture = decode_pvr(_pvr(flags=0x0010))
    assert texture.pixels[3] == 0xFF


def test_eight_bit_channels_are_read_directly() -> None:
    pixel = struct.pack('<I', 0x11223344)
    texture = decode_pvr(
        _pvr(bit_count=32, masks=(0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000), body=pixel))
    assert texture.pixels == bytes((0x44, 0x33, 0x22, 0x11))


def test_sub_nibble_channels_are_scaled_by_multiplication() -> None:
    # A three-bit red channel of all ones scales to 7 * (255 // 7) = 252.
    texture = decode_pvr(_pvr(bit_count=8, masks=(0x07, 0x38, 0xC0, 0x00), body=b'\x07'))
    assert texture.pixels[0] == 252
