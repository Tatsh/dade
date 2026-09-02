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


def test_read_level2_reads_a_prop(make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _ldb2_machine, _ldb2_prop
    level = read_level2(make_ldb2(machines=(_ldb2_machine(),), props=(_ldb2_prop(),)))
    assert level.props is not None
    assert len(level.props.meshes) == 1
    assert level.props.names == ('prop0_0',)


def test_read_level2_places_a_prop_by_its_state_machine(make_ldb2: Callable[..., bytes]) -> None:
    # A dynamic mesh carries no transform: it names a state machine, and that is where it stands.
    from .conftest import _ldb2_machine, _ldb2_prop
    level = read_level2(
        make_ldb2(machines=(_ldb2_machine(), _ldb2_machine((5.0, 6.0, 7.0))),
                  props=(_ldb2_prop(machine=1),)))
    assert level.props is not None
    assert level.props.meshes[0].transform[9:] == (5.0, 6.0, 7.0)


def test_read_level2_falls_back_when_a_prop_names_no_state_machine(
        make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _ldb2_prop
    level = read_level2(make_ldb2(props=(_ldb2_prop(machine=9),)))
    assert level.props is not None
    assert level.props.meshes[0].transform[9:] == (0.0, 0.0, 0.0)


def test_read_level2_shares_a_prefabs_geometry(make_ldb2: Callable[..., bytes]) -> None:
    # A prefab is written once. The second copy carries no mesh at all, and a reader that expects
    # one loses its place for the rest of the file.
    from .conftest import _ldb2_machine, _ldb2_prop
    level = read_level2(
        make_ldb2(machines=(_ldb2_machine(),),
                  props=(_ldb2_prop(prefab=3), _ldb2_prop(prefab=3, geometry=False))))
    assert level.props is not None
    assert len(level.props.meshes) == 1


def test_read_level2_rereads_a_prefab_that_is_lit_on_its_own(
        make_ldb2: Callable[..., bytes]) -> None:
    # A second copy with its own lighting writes its mesh again, but not its collision.
    from .conftest import _ldb2_machine, _ldb2_prop
    level = read_level2(
        make_ldb2(machines=(_ldb2_machine(),),
                  props=(_ldb2_prop(prefab=3), _ldb2_prop(prefab=3, lightmapped=True, share=True))))
    assert level.props is not None
    assert len(level.props.meshes) == 2


def test_read_level2_rereads_a_prefabs_collision_when_it_is_not_shared(
        make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _ldb2_machine, _ldb2_prop
    level = read_level2(
        make_ldb2(machines=(_ldb2_machine(),),
                  props=(_ldb2_prop(prefab=3), _ldb2_prop(prefab=3, lightmapped=True,
                                                          share=False))))
    assert level.props is not None
    assert len(level.props.meshes) == 2


def test_read_level2_reads_a_props_clips(make_ldb2: Callable[..., bytes]) -> None:
    from .conftest import _ldb2_animation, _ldb2_machine, _ldb2_prop
    level = read_level2(
        make_ldb2(machines=(_ldb2_machine(),),
                  props=(_ldb2_prop(animations=(_ldb2_animation(),)),)))
    assert level.props is not None
    clip = level.props.animations[0][0]
    assert clip.duration == pytest.approx(1.5)
    assert clip.end[9:] == (1.0, 0.0, 0.0)
    assert len(clip.distance) == 2


def test_read_level2_rejects_a_level_that_ends_early(make_ldb2: Callable[..., bytes]) -> None:
    # Cut so the file stops exactly where the prop count belongs, rather than part way through it.
    with pytest.raises(InvalidLevel2Error, match='ends at'):
        read_level2(make_ldb2()[:-4])


def test_read_level2_walks_a_populated_tail(make_ldb2: Callable[..., bytes]) -> None:
    # Nothing between the rooms and the props is drawn, but every one of them has to be stepped
    # over exactly or the props are read from the wrong offset.
    from .conftest import _ldb2_machine, _ldb2_prop
    level = read_level2(
        make_ldb2(machines=(_ldb2_machine(),), props=(_ldb2_prop(),), populated=True))
    assert level.props is not None
    assert len(level.props.meshes) == 1


def test_read_level2_drops_a_clip_with_no_transform(make_ldb2: Callable[..., bytes]) -> None:
    # A clip whose start is a number rather than a transform moves nothing, so it is not written.
    from .conftest import _ldb2_animation, _ldb2_machine, _ldb2_prop
    level = read_level2(
        make_ldb2(machines=(_ldb2_machine(),),
                  props=(_ldb2_prop(animations=(_ldb2_animation(placed=False),)),)))
    assert level.props is not None
    assert level.props.animations[0] == ()
