"""Tests for :mod:`destin.xg2.models`, :mod:`destin.xg2.displaylist`, and montage building."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.xg2.displaylist import (
    MAX_TEXTURE_SIDE,
    MIN_TEXTURE_SIDE,
    parse_dl_textures,
    parse_pc_descriptors,
    parse_pc_textures,
)
from destin.xg2.models import SKYBOX_HEIGHT, SKYBOX_WIDTH, collect_textures, walk_sub_archive
from destin.xg2.montage import build_index, build_montage
from destin.xg2.typing import Texture
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from destin.xg2.typing import Endian


def _skybox_tile() -> bytes:
    return b''.join(
        struct.pack('>H', (i & 0xFFFE) | 1) for i in range(SKYBOX_WIDTH * SKYBOX_HEIGHT))


def _pc_model() -> bytes:
    model = bytearray(struct.pack('<I', 0x05000000) + b'\x00' * 4)
    model += struct.pack('<I', 0xAC000000)
    model += struct.pack('<I', 0x05000100)  # Palette.
    model += struct.pack('<I', 0x00040808)  # Eight by eight.
    model += struct.pack('<I', 0x05000800)  # Pixels.
    return bytes(model) + b'\x00' * (0x1000 - len(model))


def test_walk_sub_archive_reads_contiguous_entries(make_sub_archive: Callable[..., bytes]) -> None:
    blob = make_sub_archive([b'a' * 16, b'b' * 32])
    assert [size for _, size in walk_sub_archive(blob)] == [16, 32]


def test_walk_sub_archive_stops_at_a_gap(make_sub_archive: Callable[..., bytes]) -> None:
    blob = bytearray(make_sub_archive([b'a' * 16, b'b' * 16]))
    struct.pack_into('>I', blob, 8 + 12 + 4, 0xFFF)  # Break the second record's contiguity.
    assert len(walk_sub_archive(bytes(blob))) == 1


def test_walk_sub_archive_rejects_a_non_archive() -> None:
    assert walk_sub_archive(b'\x05\x00\x00\x00' + b'\x11' * 64) == []


def test_walk_sub_archive_little_endian(make_sub_archive: Callable[..., bytes]) -> None:
    blob = make_sub_archive([b'a' * 16, b'b' * 16], '<')
    assert [size for _, size in walk_sub_archive(blob, '<')] == [16, 16]


@pytest.mark.parametrize('endian', ['>', '<'])
def test_collect_textures_decodes_skybox_tiles(make_sub_archive: Callable[..., bytes],
                                               endian: Endian) -> None:
    blob = make_sub_archive([_skybox_tile()] * 6, endian)
    textures = collect_textures(blob, endian)
    assert len(textures) == 6
    assert all(t.width == SKYBOX_WIDTH and t.height == SKYBOX_HEIGHT for t in textures)
    assert all(t.pixel_format == 'rgba16' for t in textures)
    assert all(len(t.rgba) == SKYBOX_WIDTH * SKYBOX_HEIGHT * 4 for t in textures)


def test_collect_textures_ignores_sub_blobs_of_other_sizes(
        make_sub_archive: Callable[..., bytes]) -> None:
    blob = make_sub_archive([b'\x00' * 100] * 6)
    assert collect_textures(blob) == []


def test_collect_textures_on_a_short_blob() -> None:
    assert collect_textures(b'\x00\x00') == []


def test_collect_textures_treats_a_small_table_as_flat(
        make_sub_archive: Callable[..., bytes]) -> None:
    # Fewer than four sub-blobs is parsed flat rather than as a sub-archive.
    assert collect_textures(make_sub_archive([_skybox_tile()] * 2)) == []


def test_parse_dl_textures_on_an_empty_display_list() -> None:
    assert parse_dl_textures(struct.pack('>I', 0x05000000) + b'\x00' * 4) == []


def test_parse_dl_textures_ignores_non_segment_five_images() -> None:
    commands = struct.pack('>II', 0xFD000000, 0x01000000) + struct.pack('>II', 0xF2000000, 0)
    assert parse_dl_textures(commands) == []


def test_parse_pc_descriptors_finds_a_descriptor() -> None:
    descriptors = list(parse_pc_descriptors(_pc_model()))
    assert len(descriptors) == 1
    _, palette, pixels, width, height = descriptors[0]
    assert (palette, pixels, width, height) == (0x100, 0x800, 8, 8)


def test_parse_pc_descriptors_rejects_a_bad_dimension_word() -> None:
    model = bytearray(_pc_model())
    struct.pack_into('<I', model, 16, 0x00050808)  # Wrong marker byte.
    assert list(parse_pc_descriptors(bytes(model))) == []


def test_parse_pc_textures_decodes_a_descriptor() -> None:
    textures = parse_pc_textures(_pc_model())
    assert len(textures) == 1
    assert (textures[0].pixel_format, textures[0].width, textures[0].height) == ('ci8', 8, 8)
    assert len(textures[0].rgba) == 8 * 8 * 4


def test_parse_pc_textures_skips_a_descriptor_past_the_end() -> None:
    model = bytearray(_pc_model())
    struct.pack_into('<I', model, 20, 0x05000FFF)  # Pixels run past the blob.
    assert parse_pc_textures(bytes(model)) == []


def test_parse_pc_textures_ignores_a_repeated_pixel_offset() -> None:
    model = _pc_model()
    doubled = model[:24] + model[8:24] + model[24:]
    assert len(parse_pc_textures(doubled)) == 1


def test_texture_side_bounds() -> None:
    assert MIN_TEXTURE_SIDE == 2
    assert MAX_TEXTURE_SIDE == 512


def test_build_montage_dimensions() -> None:
    textures = [Texture('ci8', 0, 8, 8, b'\xff' * (8 * 8 * 4)) for _ in range(20)]
    width, height, rgba = build_montage(textures, cell=16, columns=8)
    assert (width, height) == (128, 48)
    assert len(rgba) == width * height * 4


def test_build_montage_of_nothing_is_one_row() -> None:
    width, height, rgba = build_montage([], cell=16, columns=8)
    assert (width, height) == (128, 16)
    assert len(rgba) == width * height * 4


def test_build_montage_draws_opaque_pixels() -> None:
    texture = Texture('ci8', 0, 16, 16, b'\xff\x00\x00\xff' * (16 * 16))
    _, _, rgba = build_montage([texture], cell=16, columns=1)
    assert rgba[:4] == b'\xff\x00\x00\xff'


def test_build_montage_leaves_transparent_pixels_as_background() -> None:
    texture = Texture('ci8', 0, 16, 16, b'\xff\x00\x00\x00' * (16 * 16))
    _, _, rgba = build_montage([texture], cell=16, columns=1)
    assert rgba[:4] != b'\xff\x00\x00\xff'


def test_build_montage_does_not_enlarge() -> None:
    texture = Texture('ci8', 0, 2, 2, b'\xff\xff\xff\xff' * 4)
    _, _, rgba = build_montage([texture], cell=16, columns=1)
    # The 2x2 texture is centred, so the top-left corner keeps the checkerboard.
    assert rgba[:4] != b'\xff\xff\xff\xff'


def test_build_index_lines_up_with_the_grid() -> None:
    textures = [Texture('ci8', 0, 8, 8, b'\x00' * 256) for _ in range(3)]
    index = build_index(textures, ['a', 'b', 'c'], columns=2)
    lines = index.splitlines()
    assert len(lines) == 3
    assert 'r00c00' in lines[0]
    assert 'r01c00' in lines[2]
    assert lines[2].endswith('c')


def test_build_index_requires_matching_labels() -> None:
    with pytest.raises(ValueError, match='argument 2 is shorter'):
        build_index([Texture('ci8', 0, 8, 8, b'\x00' * 256)], [], columns=2)


def test_walk_sub_archive_stops_at_a_non_contiguous_record(
        make_sub_archive: Callable[..., bytes]) -> None:
    blob = bytearray(make_sub_archive([b'a' * 16, b'b' * 16]))
    struct.pack_into('>I', blob, 8 + 12 + 4, 40)  # Valid, but not where the first record ended.
    assert len(walk_sub_archive(bytes(blob))) == 1


def test_collect_textures_parses_flat_sub_models(make_sub_archive: Callable[..., bytes],
                                                 n64_model: bytes) -> None:
    blob = make_sub_archive([n64_model, *([b'\x05\x00\x00\x00' + b'\x00' * 12] * 3)])
    assert len(collect_textures(blob)) == 1
