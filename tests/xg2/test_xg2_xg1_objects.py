"""Tests for the track objects in :mod:`dade.xg2.xg1_objects`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import math
import struct

import pytest

from dade.xg2.lzhuf import LzhufError
from dade.xg2.xg1_level import XG1
from dade.xg2.xg1_objects import (
    GLOW_TEXTURE_KEY,
    SEGMENT_BASE,
    Entity,
    ObjectModel,
    face_colour,
    glow_model,
    glow_textures,
    is_flame,
    object_placements,
    pickup_swing,
    read_code_segment,
    read_entities,
    read_object_models,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_GLOW_LIST = 0x801064F0

_SEGMENT_SIZE = 0x120000
_SUBTYPE_LISTS = 0x80106994
_MODEL_TABLE = 0x80106B04
_MODEL_RECORD = 12
_LIST_VRAM = 0x800A0000
_VERTEX_VRAM = 0x800A1000
_DISPLAY_LIST_VRAM = 0x800A2000
_MASK_VRAM = 0x80146160
_CLOUD_VRAM = 0x80146360
_GLOW_SIDE = 32
_SPIN_START = 20.0
_TICK_HZ = 30


def _place(segment: bytearray, vram: int, payload: bytes) -> None:
    at = vram - SEGMENT_BASE
    segment[at:at + len(payload)] = payload


def _vertex(x: int, y: int, z: int, s: int, t: int, normal: tuple[int, int,
                                                                  int] = (0, 0, 127)) -> bytes:
    return struct.pack('>3hH2h3bB', x, y, z, 0, s, t, *normal, 0)


def _segment_with_model() -> bytearray:
    """
    Build a segment holding one sub-type whose cycle is a single triangle.

    Returns
    -------
    bytearray
        The segment.
    """
    segment = bytearray(_SEGMENT_SIZE)
    _place(segment, _VERTEX_VRAM,
           _vertex(0, 0, 0, 0, 0) + _vertex(100, 0, 0, 32, 0) + _vertex(0, 100, 0, 0, 32))
    # G_VTX loading three vertices ending at slot three, one G_TRI1 over them, then G_ENDDL.
    _place(
        segment,
        _DISPLAY_LIST_VRAM,
        struct.pack('>2I', 0x04000000 | (3 << 10) | (3 * 16 - 1), _VERTEX_VRAM) +
        # Slots are doubled on their way into the command, so 0, 1 and 2 are written 0x00, 0x02 and
        # 0x04.
        struct.pack('>2I', 0xBF000000, 0x00000204) + struct.pack('>2I', 0xB8000000, 0))
    _place(segment, _MODEL_TABLE, struct.pack('>I', _DISPLAY_LIST_VRAM) + bytes(_MODEL_RECORD - 4))
    _place(segment, _LIST_VRAM, struct.pack('>2h', 0, -1))
    _place(segment, _SUBTYPE_LISTS, struct.pack('>I', _LIST_VRAM))
    return segment


def test_read_object_models_decodes_one_triangle() -> None:
    cycles = read_object_models(bytes(_segment_with_model()))
    assert len(cycles[0]) == 1
    model = cycles[0][0]
    assert model.id == 0
    assert model.indices == (0, 1, 2)
    assert model.positions == ((0, 0, 0), (100, 0, 0), (0, 100, 0))
    assert model.coords == ((0, 0), (32, 0), (0, 32))


def test_read_object_models_leaves_unmapped_subtypes_empty() -> None:
    assert read_object_models(bytes(_segment_with_model()))[1] == ()


def _triangle(normal_along: str) -> ObjectModel:
    corners = {
        # Wound so the face normal comes out along +Z.
        'z': ((0, 0, 0), (1, 0, 0), (0, 1, 0)),
        # And here along -Z.
        '-z': ((0, 0, 0), (0, 1, 0), (1, 0, 0)),
        # And here along +X, which neither light points at.
        'x': ((0, 0, 0), (0, 0, 1), (0, 1, 0)),
    }[normal_along]
    return ObjectModel(0, corners, ((0, 0),) * 3, ((0.0, 1.0, 0.0),) * 3, (0, 1, 2), 0xFF, 0xFF,
                       0xFF)


@pytest.mark.parametrize(('normal_along', 'expected'), [
    ('z', (0x80, 0xFF, 0x80)),
    ('-z', (0xFF, 0xFF, 0xFF)),
    ('x', (0x80, 0x80, 0x80)),
])
def test_face_colour_lights_from_two_opposed_lights(normal_along: str,
                                                    expected: tuple[int, int, int]) -> None:
    assert face_colour(_triangle(normal_along), 0) == expected


def test_face_colour_scales_the_primitive_colour() -> None:
    model = _triangle('x')._replace(red=0x40, green=0x80, blue=0x00)
    # A face neither light reaches keeps the bare ambient, which is half.
    assert face_colour(model, 0) == (0x20, 0x40, 0x00)


def test_pickup_swing_starts_at_its_spawn_angle() -> None:
    assert pickup_swing(0.0) == pytest.approx((math.radians(_SPIN_START),) * 2)


@pytest.mark.parametrize(('axis', 'push'), [(0, 0.02), (1, 0.05)])
def test_swing_reaches_the_far_side_at_half_a_period(axis: int, push: float) -> None:
    # The motion is four parabolic arcs, so half a period is the opposite angle.
    half = 2 * math.sqrt((2 * _SPIN_START) / push)
    assert pickup_swing(half / _TICK_HZ)[axis] == pytest.approx(math.radians(-_SPIN_START))


def test_swing_never_leaves_its_starting_amplitude() -> None:
    limit = math.radians(_SPIN_START) + 1e-9
    for tick in range(600):
        for angle in pickup_swing(tick / _TICK_HZ):
            assert abs(angle) <= limit


@pytest.mark.parametrize('identifier', [0x36, 0x00, 0x38])
def test_is_flame_ignores_every_other_identifier(identifier: int) -> None:
    assert is_flame(_triangle('z')._replace(id=identifier)) is False


def test_is_flame_matches_the_flame_column() -> None:
    assert is_flame(_triangle('z')._replace(id=0x37)) is True


def test_is_flame_of_nothing() -> None:
    assert is_flame(None) is False


def test_object_placements_keeps_position_and_tints_flames_red() -> None:
    pickup = (_triangle('z'),)
    flame = (_triangle('z')._replace(id=0x37),)
    entities = [
        Entity(0, 0, 10, 20, 30),
        Entity(0, 1, 40, 50, 60),
        # A record of another type, and one whose sub-type has no models, are both skipped.
        Entity(2, 0, 70, 80, 90),
        Entity(0, 2, 1, 2, 3),
    ]
    placements = object_placements(entities, [pickup, flame, ()])
    assert [(p.x, p.y, p.z) for p in placements] == [(10, 20, 30), (40, 50, 60)]
    assert placements[0].icons == pickup
    assert placements[0].glow == (0x3C, 0xF0, 0x3C)
    # A flame column draws no icon and its glow is red.
    assert placements[1].icons == ()
    assert placements[1].glow == (0xF0, 0x3C, 0x3C)


def test_object_placements_ignores_a_subtype_past_the_table() -> None:
    assert object_placements([Entity(0, 90, 0, 0, 0)], [(_triangle('z'),)]) == []


def _segment_with_glow() -> bytes:
    segment = bytearray(_SEGMENT_SIZE)
    texels = _GLOW_SIDE * _GLOW_SIDE
    # Every nibble full, so the widened intensity is 0xFF throughout both images.
    _place(segment, _MASK_VRAM, b'\xff' * (texels // 2))
    _place(segment, _CLOUD_VRAM, b'\xff' * (texels // 2))
    return bytes(segment)


def test_glow_textures_bakes_one_image_per_step() -> None:
    images = glow_textures(_segment_with_glow(), 4)
    assert [image.offset for image in images] == [GLOW_TEXTURE_KEY - step for step in range(4)]
    assert all(image.width == _GLOW_SIDE and image.height == _GLOW_SIDE for image in images)
    assert all(len(image.rgba) == _GLOW_SIDE * _GLOW_SIDE * 4 for image in images)


def test_glow_textures_are_white_with_the_masked_intensity_as_alpha() -> None:
    rgba = glow_textures(_segment_with_glow(), 1)[0].rgba
    assert set(rgba[0::4]) == {0xFF}
    assert set(rgba[1::4]) == {0xFF}
    assert set(rgba[2::4]) == {0xFF}
    # 0xFF cloud times 0xFF mask over 0xFF is 0xFF.
    assert set(rgba[3::4]) == {0xFF}


def test_glow_textures_of_a_segment_without_them() -> None:
    assert glow_textures(b'', 4) == []


def _glow_segment() -> bytes:
    segment = bytearray(_SEGMENT_SIZE)
    outer_verts, nested_list, nested_verts = 0x80108000, 0x80107000, 0x80109000
    _place(segment, outer_verts,
           _vertex(0, 0, 0, 0, 0) + _vertex(1, 0, 0, 0, 0) + _vertex(0, 1, 0, 0, 0))
    _place(segment, nested_verts,
           _vertex(0, 0, 1, 0, 0) + _vertex(1, 0, 1, 0, 0) + _vertex(0, 1, 1, 0, 0))
    _place(
        segment, nested_list,
        struct.pack('>2I', 0x04000C2F, nested_verts) + struct.pack('>2I', 0xBF000000, 0x00000204) +
        struct.pack('>2I', 0xB8000000, 0))
    _place(
        segment, _GLOW_LIST,
        struct.pack('>2I', 0xFA000000, 0x10203040) + struct.pack('>2I', 0x04000C2F, outer_verts) +
        struct.pack('>2I', 0xBF000000, 0x00000204) + struct.pack('>2I', 0x06000000, nested_list) +
        struct.pack('>2I', 0xB8000000, 0))
    return bytes(segment)


def test_glow_model_merges_a_nested_display_list() -> None:
    model = glow_model(_glow_segment())
    assert model is not None
    assert len(model.positions) == 6
    assert model.indices == (0, 1, 2, 3, 4, 5)
    assert (model.red, model.green, model.blue) == (0x10, 0x20, 0x30)


def test_glow_model_of_a_list_that_loads_nothing() -> None:
    segment = bytearray(_SEGMENT_SIZE)
    # A G_VTX whose source is outside the segment loads nothing, so the triangle over its slots is
    # dropped and the list draws nothing at all.
    _place(
        segment, _GLOW_LIST,
        struct.pack('>2I', 0x04000C2F, 0) + struct.pack('>2I', 0xBF000000, 0x00000204) +
        struct.pack('>2I', 0xB8000000, 0))
    assert glow_model(bytes(segment)) is None


def test_glow_model_stops_at_maximum_nesting_depth() -> None:
    segment = bytearray(_SEGMENT_SIZE)
    addresses = [_GLOW_LIST, 0x80108000, 0x80108100, 0x80108200, 0x80108300, 0x80108400]
    for index in range(len(addresses) - 1):
        _place(
            segment, addresses[index],
            struct.pack('>2I', 0x06000000, addresses[index + 1]) +
            struct.pack('>2I', 0xB8000000, 0))
    assert glow_model(bytes(segment)) is None


def test_glow_model_runs_the_whole_command_budget() -> None:
    segment = bytearray(_SEGMENT_SIZE)
    _place(segment, _GLOW_LIST, struct.pack('>2I', 0xFA000000, 0) * 512)
    assert glow_model(bytes(segment)) is None


def test_glow_model_ignores_a_nested_list_that_draws_nothing() -> None:
    segment = bytearray(_SEGMENT_SIZE)
    nested = 0x80108000
    _place(
        segment, nested,
        struct.pack('>2I', 0x04000C2F, 0) + struct.pack('>2I', 0xBF000000, 0x00000204) +
        struct.pack('>2I', 0xB8000000, 0))
    _place(segment, _GLOW_LIST,
           struct.pack('>2I', 0x06000000, nested) + struct.pack('>2I', 0xB8000000, 0))
    assert glow_model(bytes(segment)) is None


def test_glow_model_steps_over_an_unknown_command() -> None:
    segment = bytearray(_SEGMENT_SIZE)
    _place(segment, _GLOW_LIST,
           struct.pack('>2I', 0x00000000, 0) + struct.pack('>2I', 0xB8000000, 0))
    assert glow_model(bytes(segment)) is None


def test_read_object_models_of_a_short_segment() -> None:
    assert read_object_models(b'\x00' * 16) == [()] * 96


def test_read_object_models_cycles_a_full_length_list() -> None:
    segment = _segment_with_model()
    _place(segment, _LIST_VRAM, struct.pack('>8h', *([0] * 8)))
    assert len(read_object_models(bytes(segment))[0]) == 8


def test_read_object_models_stops_at_a_list_running_off_the_end() -> None:
    size = _MODEL_TABLE - SEGMENT_BASE + 8
    segment = bytearray(size)
    _place(segment, _SUBTYPE_LISTS, struct.pack('>I', SEGMENT_BASE + size - 2))
    struct.pack_into('>h', segment, size - 2, 0)
    assert read_object_models(bytes(segment))[0] == ()


def test_read_object_models_stops_at_a_model_record_past_the_end() -> None:
    size = _MODEL_TABLE - SEGMENT_BASE + 4
    segment = bytearray(size)
    _place(segment, _SUBTYPE_LISTS, struct.pack('>I', _LIST_VRAM))
    struct.pack_into('>2h', segment, _LIST_VRAM - SEGMENT_BASE, 1, -1)
    assert read_object_models(bytes(segment))[0] == ()


def test_read_code_segment_decompresses(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.xg1_objects.decompress_lzhuf', return_value=b'segment')
    assert read_code_segment(b'\x00' * 0x100) == b'segment'


def test_read_code_segment_of_an_undecodable_rom(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.xg1_objects.decompress_lzhuf', side_effect=LzhufError(0, 1))
    assert read_code_segment(b'\x00' * 0x100) == b''


def _region() -> bytes:
    region = bytearray(0xC0)
    struct.pack_into('>I', region, 0x40, 0x80)  # The entity stream starts at 0x80.
    struct.pack_into('>2B', region, 0x80, 0, 5)  # A type-zero object, sub-type five.
    struct.pack_into('>3i', region, 0x80 + 8, 10, 20, 30)
    struct.pack_into('>2B', region, 0xA0, 3, 0)  # A record of another type.
    struct.pack_into('>3i', region, 0xA0 + 8, 40, 50, 60)
    return bytes(region)


def _region_rom() -> bytes:
    words = [0] * 17
    words[7] = 0x100  # region offset
    words[8] = 0x100  # region size
    return struct.pack('>17I', *words) + b'\x00' * 0x400


def test_read_entities_reads_the_stream(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.xg1_objects.decompress_lzhuf', return_value=_region())
    entities = read_entities(_region_rom(), 0, XG1)
    assert [(e.type, e.subtype, e.x, e.y, e.z) for e in entities] == [(0, 5, 10, 20, 30),
                                                                      (3, 0, 40, 50, 60)]


def test_read_entities_without_a_region() -> None:
    assert read_entities(struct.pack('>17I', *([0] * 17)) + b'\x00' * 0x400, 0, XG1) == []


def test_read_entities_of_an_undecodable_region(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.xg1_objects.decompress_lzhuf', side_effect=LzhufError(0, 1))
    assert read_entities(_region_rom(), 0, XG1) == []


def test_read_entities_of_a_region_without_a_pointer(mocker: MockerFixture) -> None:
    mocker.patch('dade.xg2.xg1_objects.decompress_lzhuf', return_value=b'\x00' * 0x100)
    assert read_entities(_region_rom(), 0, XG1) == []
