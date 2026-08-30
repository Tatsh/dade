from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.sopranos.texture import (
    BANK_MAGIC,
    PALETTE_ENTRIES,
    convert,
    convert_geometry,
    decode,
    iter_geometry_textures,
    iter_textures,
)

from .conftest import (
    FORMAT_PALETTED,
    FORMAT_RGB,
    FORMAT_RGBA,
    IMAGES_AT,
    build_bank,
    build_image,
)

if TYPE_CHECKING:
    from pathlib import Path

_PALETTE = bytes(bytearray(range(PALETTE_ENTRIES)) * 4)


def _rgba_image(name: str = 'art/one.tga') -> bytes:
    # Two by two, with a distinct alpha per pixel so the 0..128 rescale is visible.
    pixels = bytes([255, 0, 0, 0x40, 0, 255, 0, 0x80, 0, 0, 255, 0x00, 9, 9, 9, 0x20])
    return build_image(name, 2, 2, FORMAT_RGBA, pixels)


def test_iter_textures_lists_a_banks_images() -> None:
    bank = build_bank([_rgba_image('a/one.tga'), _rgba_image('b/two.tga')])
    assert [texture.name for texture in iter_textures(bank)] == ['a/one.tga', 'b/two.tga']


def test_decode_rescales_alpha_and_flips_rows() -> None:
    bank = build_bank([_rgba_image()])
    texture, = iter_textures(bank)
    image = decode(bank, texture)
    assert image.size == (2, 2)
    # Stored rows are bottom-up, so the first stored pixel ends up on the lower row.
    assert image.getpixel((0, 1)) == (255, 0, 0, 128)
    assert image.getpixel((1, 1)) == (0, 255, 0, 255)


def test_decode_reads_a_24_bit_image() -> None:
    bank = build_bank([build_image('a/rgb.tga', 2, 1, FORMAT_RGB, bytes([1, 2, 3, 4, 5, 6]))])
    texture, = iter_textures(bank)
    assert decode(bank, texture).getpixel((0, 0)) == (1, 2, 3, 255)


def test_decode_reads_a_paletted_image() -> None:
    pixels = bytes([0, 1, 2, 3])
    bank = build_bank([build_image('a/pal.tga', 2, 2, FORMAT_PALETTED, pixels, _PALETTE)])
    texture, = iter_textures(bank)
    assert decode(bank, texture).size == (2, 2)


def test_iter_textures_rejects_a_tiny_bank() -> None:
    with pytest.raises(InvalidFormatError, match='too small'):
        list(iter_textures(b'abc'))


def test_iter_textures_rejects_a_foreign_magic() -> None:
    with pytest.raises(InvalidFormatError, match='expected'):
        list(iter_textures(struct.pack('<3I', 0x99, 0, 0)))


def test_iter_textures_rejects_a_truncated_offset_table() -> None:
    with pytest.raises(InvalidFormatError, match='offset table is truncated'):
        list(iter_textures(struct.pack('<3I', 0x64, 0, 50)))


def test_iter_textures_rejects_an_offset_out_of_range() -> None:
    raw = bytearray(build_bank([_rgba_image()]))
    struct.pack_into('<I', raw, 12, 0xFFFF)
    with pytest.raises(InvalidFormatError, match='out-of-range image offset'):
        list(iter_textures(bytes(raw)))


def test_iter_textures_passes_over_an_empty_slot() -> None:
    # A bank reserves a slot for every image its reader may ask for by number; the build leaves a
    # zero where it had nothing to put. The game's own HUD banks are mostly these.
    raw = bytearray(build_bank([_rgba_image(), _rgba_image('b/two.tga')]))
    struct.pack_into('<I', raw, 12, 0)
    assert [texture.name for texture in iter_textures(bytes(raw))] == ['b/two.tga']


def test_iter_textures_accepts_a_bank_that_is_nothing_but_empty_slots() -> None:
    # Exactly a header and a table, no image data at all, which is how slots/p_hud.tex2 ships.
    raw = struct.pack('<3I', BANK_MAGIC, 0, 5) + bytes(5 * 4)
    assert list(iter_textures(raw)) == []


def test_iter_textures_rejects_a_bad_image_magic() -> None:
    raw = bytearray(build_bank([_rgba_image()]))
    struct.pack_into('<I', raw, 16, 0x99)
    with pytest.raises(InvalidFormatError, match='has magic'):
        list(iter_textures(bytes(raw)))


def test_iter_textures_rejects_an_unknown_pixel_format() -> None:
    raw = bytearray(build_bank([_rgba_image()]))
    raw[16 + 0x1A] = 9
    with pytest.raises(InvalidFormatError, match='unsupported pixel format'):
        list(iter_textures(bytes(raw)))


def test_decode_rejects_pixels_running_past_the_end() -> None:
    bank = build_bank([_rgba_image()])
    texture, = iter_textures(bank)
    with pytest.raises(InvalidFormatError, match='runs past the end'):
        decode(bank[:-4], texture)


def test_decode_rejects_a_palette_running_past_the_end() -> None:
    pixels = bytes([0, 1, 2, 3])
    bank = build_bank([build_image('a/pal.tga', 2, 2, FORMAT_PALETTED, pixels, _PALETTE)])
    texture, = iter_textures(bank)
    with pytest.raises(InvalidFormatError, match='runs past the end'):
        decode(bank[:-8], texture)


def _sgp_blob(images: list[bytes]) -> bytes:
    body = b''.join(images)
    raw = bytearray(IMAGES_AT)
    struct.pack_into('<I', raw, 0x0C, IMAGES_AT + len(body))
    return bytes(raw) + body


def _egp_blob(images: list[bytes]) -> bytes:
    body = b''.join(images)
    raw = bytearray(IMAGES_AT)
    struct.pack_into('<I', raw, 0x4C, IMAGES_AT)
    return bytes(raw) + body


def test_iter_geometry_textures_walks_a_skinned_blob() -> None:
    blob = _sgp_blob([_rgba_image('a/one.tga'), _rgba_image('b/two.tga')])
    assert [t.name for t in iter_geometry_textures(blob)] == ['a/one.tga', 'b/two.tga']


def test_iter_geometry_textures_walks_an_environment_blob() -> None:
    blob = _egp_blob([_rgba_image('a/one.tga')])
    assert [t.name for t in iter_geometry_textures(blob)] == ['a/one.tga']


def test_iter_geometry_textures_stops_at_a_non_image_word() -> None:
    blob = _egp_blob([_rgba_image('a/one.tga')]) + struct.pack('<I', 0) + bytes(0x2C)
    assert [t.name for t in iter_geometry_textures(blob)] == ['a/one.tga']


def test_iter_geometry_textures_ignores_a_tiny_blob() -> None:
    assert list(iter_geometry_textures(bytes(16))) == []


def test_iter_geometry_textures_stops_on_a_zero_length_record() -> None:
    image = bytearray(_rgba_image('a/one.tga'))
    struct.pack_into('<I', image, 4, 0)
    assert list(iter_geometry_textures(_sgp_blob([bytes(image)]))) == []


def test_convert_writes_a_png_per_image(tmp_path: Path) -> None:
    source = tmp_path / 'bank.tex2'
    source.write_bytes(build_bank([_rgba_image('a/one.tga'), _rgba_image('b/two.tga')]))
    written = convert(source, tmp_path / 'out')
    assert [path.name for path in written] == ['one.png', 'two.png']


def test_convert_suffixes_repeated_names(tmp_path: Path) -> None:
    source = tmp_path / 'bank.tex2'
    source.write_bytes(build_bank([_rgba_image('a/one.tga'), _rgba_image('b/one.tga')]))
    assert [path.name for path in convert(source, tmp_path / 'out')] == ['one.png', 'one_1.png']


def test_convert_geometry_writes_embedded_images(tmp_path: Path) -> None:
    source = tmp_path / 'mesh.egp2'
    source.write_bytes(_egp_blob([_rgba_image('a/one.tga')]))
    assert [path.name for path in convert_geometry(source, tmp_path / 'out')] == ['one.png']


def test_convert_makes_no_directory_when_there_are_no_images(tmp_path: Path) -> None:
    source = tmp_path / 'mesh.egp2'
    source.write_bytes(_egp_blob([]))
    assert convert_geometry(source, tmp_path / 'out') == ()
    assert not (tmp_path / 'out').exists()
