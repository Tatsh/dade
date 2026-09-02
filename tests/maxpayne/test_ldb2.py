from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.maxpayne.ldb2 import InvalidLevel2Error, read_level2

if TYPE_CHECKING:
    from collections.abc import Callable


def test_read_level2_reads_a_level(make_ldb2: Callable[..., bytes]) -> None:
    level = read_level2(make_ldb2())
    assert level.mesh is not None
    assert len(level.mesh.meshes) == 1
    assert len(level.textures) == 1
    assert len(level.lightmaps) == 1
    assert level.materials[0].image == 'x:\\a.dds'


def test_read_level2_places_a_batch_by_its_rooms_transform(make_ldb2: Callable[..., bytes]) -> None:
    # A Max Payne 2 room carries the transform that puts it in the world, where the first game's
    # left it to the exit graph.
    level = read_level2(make_ldb2())
    assert level.mesh is not None
    assert level.mesh.meshes[0].transform == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                                              0.0)


def test_read_level2_builds_a_face_per_triangle(make_ldb2: Callable[..., bytes]) -> None:
    level = read_level2(make_ldb2())
    assert level.mesh is not None
    face = level.mesh.meshes[0].faces[0]
    assert face.corner_count == 3
    assert face.first_corner == 0
    # The normal comes off the corners, because the format stores one per vertex and none per face.
    assert face.normal == (0.0, -1.0, 0.0)


def test_read_level2_names_a_mesh_after_its_room(make_ldb2: Callable[..., bytes]) -> None:
    level = read_level2(make_ldb2())
    assert level.mesh is not None
    assert level.mesh.names == ('::room_0',)


def test_read_level2_rejects_a_foreign_file(make_ldb2: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidLevel2Error, match='Not a Max Payne 2 level'):
        read_level2(make_ldb2(magic=b'LDB1'))


def test_read_level2_rejects_another_version(make_ldb2: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidLevel2Error, match='Unsupported'):
        read_level2(make_ldb2(version=32))


def test_read_level2_rejects_a_tag_it_does_not_know(make_ldb2: Callable[..., bytes]) -> None:
    data = bytearray(make_ldb2())
    data[4] = 0x7F
    with pytest.raises(InvalidLevel2Error, match='Not a value'):
        read_level2(bytes(data))


def test_read_level2_rejects_a_run_past_the_end(make_ldb2: Callable[..., bytes]) -> None:
    # The string pool claims more than the file holds.
    data = make_ldb2()
    with pytest.raises(InvalidLevel2Error, match='runs past the end'):
        read_level2(data[:12])


def test_read_level2_rejects_a_count_that_is_not_a_number(make_ldb2: Callable[..., bytes]) -> None:
    # A boolean where the texture count belongs.
    data = make_ldb2(textures=0)
    at = data.index(struct.pack('<f', 169.75)) + 4
    with pytest.raises(InvalidLevel2Error, match='Expected a number'):
        read_level2(data[:at] + b'\x0e\x00' + data[at + 2:])


def test_read_level2_reads_targa_lightmaps(make_ldb2: Callable[..., bytes]) -> None:
    # `is_dds` is false on levels whose atlases stayed Targa, and has to be taken at its word.
    level = read_level2(make_ldb2(lightmaps_are_dds=False))
    assert level.lightmaps[0].kind == 0


def test_read_level2_reads_dds_lightmaps(make_ldb2: Callable[..., bytes]) -> None:
    assert read_level2(make_ldb2()).lightmaps[0].kind == 5


def test_read_level2_reads_a_lit_batch(make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _int, _ldb2_batch
    level = read_level2(make_ldb2(rooms=(_int(1) + _ldb2_batch(lit=True),)))
    assert level.mesh is not None
    assert level.mesh.corners[0].lightmap_uv == (0.5, 0.5)


def test_read_level2_steps_over_a_detail_coordinate_set(make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _int, _ldb2_batch
    level = read_level2(make_ldb2(rooms=(_int(1) + _ldb2_batch(detailed=True),)))
    assert level.mesh is not None
    assert len(level.mesh.meshes[0].faces) == 1


def test_read_level2_drops_a_triangle_indexing_a_missing_vertex(
        make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _int, _ldb2_batch
    level = read_level2(make_ldb2(rooms=(_int(1) + _ldb2_batch(indices=(0, 1, 9)),)))
    assert level.mesh is not None
    assert level.mesh.meshes[0].faces == ()


def test_read_level2_steps_over_collision_shapes(make_ldb2: Callable[..., bytes]) -> None:
    # Havok's shapes are not drawn, but the reader has to get past them to reach the next room.
    level = read_level2(make_ldb2(collisions=1))
    assert level.mesh is not None
    assert len(level.mesh.meshes) == 1


def test_read_level2_steps_over_volume_lights(make_ldb2: Callable[..., bytes]) -> None:
    level = read_level2(make_ldb2(volume_lights=1))
    assert level.mesh is not None
    assert len(level.mesh.meshes) == 1


def test_read_level2_rejects_a_room_without_a_transform(make_ldb2: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidLevel2Error, match='no transform'):
        read_level2(make_ldb2(placed=False))


def test_read_level2_ignores_a_frame_past_the_diffuse_group(
        make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _ldb2_material
    level = read_level2(make_ldb2(materials=(_ldb2_material(first=9),)))
    assert not level.materials[0].image


def test_read_level2_falls_back_to_the_first_frame(make_ldb2: Callable[..., bytes]) -> None:
    # An animated material names a range and which frame to show; a frame outside it is ignored.
    from .conftest import _ldb2_material
    level = read_level2(make_ldb2(materials=(_ldb2_material(first=0, showing=9),)))
    assert level.materials[0].image == 'x:\\a.dds'


def test_read_level2_ignores_a_string_offset_past_the_pool(make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _int, _ldb2_texture
    data = make_ldb2(textures=0)
    at = data.index(struct.pack('<f', 169.75)) + 4
    grown = data[:at] + _int(1) + _ldb2_texture(4000, b'\x00\x01') + data[at + len(_int(0)):]
    assert not read_level2(grown).textures[0].path
