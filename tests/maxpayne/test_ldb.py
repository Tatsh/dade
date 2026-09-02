from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.maxpayne.ldb import InvalidLevelError, read_geometry, read_level, read_textures

if TYPE_CHECKING:
    from collections.abc import Callable


def test_read_geometry(make_ldb: Callable[..., bytes]) -> None:
    geometry = read_geometry(make_ldb())
    assert len(geometry.vertices) == 7
    assert [p.vertex_count for p in geometry.polygons] == [4, 3]
    assert [p.first_vertex for p in geometry.polygons] == [0, 4]
    assert [p.mesh_index for p in geometry.polygons] == [7, 9]
    assert geometry.polygons[0].normal == (0.0, 1.0, 0.0)


def test_read_geometry_rejects_a_missing_array_marker() -> None:
    with pytest.raises(InvalidLevelError, match='Expected an array marker'):
        read_geometry(b'\x14\x02')


def test_read_geometry_rejects_a_truncated_file() -> None:
    with pytest.raises(InvalidLevelError, match='Expected an array marker'):
        read_geometry(b'')


def test_read_geometry_rejects_too_few_corners(make_ldb: Callable[..., bytes]) -> None:
    level = make_ldb(faces=(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),), mesh_indices=(0,))
    with pytest.raises(InvalidLevelError, match='claims 2 corners'):
        read_geometry(level)


_FACE_0 = b'\x14\x00\x14\x04\x14\x00\x14\x07'
_FACE_1 = b'\x14\x04\x14\x03\x14\x01\x14\x09'


def test_read_geometry_rejects_a_face_outside_the_pool(make_ldb: Callable[..., bytes]) -> None:
    level = make_ldb().replace(_FACE_1, b'\x14\x7f\x14\x03\x14\x01\x14\x09')
    with pytest.raises(InvalidLevelError, match='outside a pool'):
        read_geometry(level)


def test_read_geometry_rejects_an_out_of_step_read(make_ldb: Callable[..., bytes]) -> None:
    level = make_ldb().replace(_FACE_0, b'\x14\x00\x14\x03\x14\x00\x14\x07')
    with pytest.raises(InvalidLevelError, match='out of step'):
        read_geometry(level)


def test_read_textures(make_ldb: Callable[..., bytes]) -> None:
    textures = read_textures(
        make_ldb(textures=(('C:\\A.TGA', 0, b'\x00\x01'), ('D:\\dir\\b.jpg', 4, b'\xff\xd8'))))
    assert [t.path for t in textures] == ['C:\\A.TGA', 'D:\\dir\\b.jpg']
    assert [t.kind for t in textures] == [0, 4]
    assert textures[1].data == b'\xff\xd8'


def test_read_textures_none(make_ldb: Callable[..., bytes]) -> None:
    assert read_textures(make_ldb(textures=())) == ()


def test_read_textures_rejects_a_run_past_the_end(make_ldb: Callable[..., bytes]) -> None:
    level = make_ldb(complete=False, textures=(('C:\\A.TGA', 0, b'\x00\x01'),))
    with pytest.raises(InvalidLevelError, match='but the file ends'):
        read_textures(level[:-1])


def test_read_textures_skips_a_populated_bsp(make_ldb: Callable[..., bytes]) -> None:
    level = make_ldb(bsp=(2, 3), textures=(('C:\\A.TGA', 0, b'\x00\x01'),))
    assert [t.path for t in read_textures(level)] == ['C:\\A.TGA']


def test_read_level(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb())
    assert len(level.geometry.polygons) == 2
    assert level.materials[7].category == 'wood'
    assert level.materials[7].texture == 'A.TGA'
    assert [t.path for t in level.textures] == ['C:\\A.TGA']
    assert level.mesh is not None
    assert len(level.mesh.meshes) == 1
    assert {f.material for f in level.mesh.meshes[0].faces} == {7, 9}


def test_read_level_reads_the_corner_array(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb(triangles=40))
    assert level.mesh is not None
    assert len(level.mesh.corners) == 120
    assert level.mesh.corners[0].position == 0
    assert level.mesh.corners[0].uv[1] == pytest.approx(0.5)


def test_read_level_reads_positions_and_normals(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb(triangles=40))
    assert level.mesh is not None
    mesh = level.mesh.meshes[0]
    assert len(mesh.positions) == len(mesh.normals) == 120
    assert mesh.normals[0] == (0.0, 0.0, 1.0)
    assert mesh.transform == (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)


def test_read_level_without_a_mesh_container(make_ldb: Callable[..., bytes]) -> None:
    assert read_level(make_ldb(triangles=0)).mesh is None


def test_read_level_ignores_a_container_that_is_too_small(make_ldb: Callable[..., bytes]) -> None:
    # Fewer corners than the reader's floor, so the candidate is rejected outright.
    assert read_level(make_ldb(triangles=4)).mesh is None


def test_read_level_resolves_a_material_to_its_image(make_ldb: Callable[..., bytes]) -> None:
    # The material's own name is not the filename; the category table is what names the picture.
    level = read_level(
        make_ldb(materials=((7, 'wood', 'A_128X256.JPG'), (9, 'metal', 'B.JPG')),
                 textures=(('X:\\art\\a_256x256.jpg', 4, b'\xff\xd8fake'),),
                 categories=(('wood', (('A_128X256.JPG', 'X:\\art\\a_256x256.jpg', ''),)),)))
    assert level.materials[7].image == 'X:\\art\\a_256x256.jpg'


def test_read_level_resolves_every_material(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(materials=((7, 'wood', 'A.TGA'),),
                 face_materials=(7,),
                 textures=(('C:\\A.TGA', 0, b'\x00\x01\x02'),)))
    assert [m.image for m in level.materials.values()] == ['C:\\A.TGA']


def test_read_level_reads_a_materials_alpha_mask(make_ldb: Callable[..., bytes]) -> None:
    # The third category path is the alpha mask, not a second guess at the colour.
    level = read_level(
        make_ldb(materials=((7, 'wood', 'A.TGA'), (9, 'metal', 'B.JPG')),
                 textures=(('C:\\A.TGA', 0, b'\x00\x01\x02'), ('C:\\A_alpha.pcx', 3, b'\x0a\x05')),
                 categories=(('wood', (('A.TGA', 'C:\\A.TGA', 'C:\\A_alpha.pcx'),)),)))
    assert level.materials[7].image == 'C:\\A.TGA'
    assert level.materials[7].alpha == 'C:\\A_alpha.pcx'


def test_read_level_leaves_an_opaque_material_without_a_mask(
        make_ldb: Callable[..., bytes]) -> None:
    assert not read_level(make_ldb()).materials[7].alpha


def test_read_level_ignores_a_mask_that_is_the_colour_again(make_ldb: Callable[..., bytes]) -> None:
    # Most entries repeat the colour path in both slots, which means opaque, not self-masked.
    level = read_level(
        make_ldb(materials=((7, 'wood', 'A.TGA'), (9, 'metal', 'B.JPG')),
                 textures=(('C:\\A.TGA', 0, b'\x00\x01\x02'),),
                 categories=(('wood', (('A.TGA', 'C:\\A.TGA', 'C:\\A.TGA'),)),)))
    assert not level.materials[7].alpha


def test_read_level_leaves_an_unnamed_material_without_an_image(
        make_ldb: Callable[..., bytes]) -> None:
    # Nothing in the category table points at an embedded image, so the material draws untextured.
    level = read_level(make_ldb(categories=(('wood', (('A.TGA', 'X:\\gone.jpg', ''),)),)))
    assert not level.materials[7].image
    assert not level.materials[9].image


def test_read_level_reads_the_placements(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb())
    assert [(c.skin, c.placement.name) for c in level.characters] == [('transit_cop', '::room::e1')]
    assert level.characters[0].placement.transform[9:] == (1.0, 2.0, 3.0)
    assert [(i.item, i.placement.name) for i in level.items] == [('ammo_ingram', '::room::ammo')]
    assert level.props is not None
    assert level.props.names == ('::room::door.DO',)
    assert level.props.meshes[0].transform[9:] == (7.0, 8.0, 9.0)


def test_read_level_gives_up_on_an_unwalkable_tail(make_ldb: Callable[..., bytes]) -> None:
    # A count no level could hold means the walk has lost its place, so the tail is abandoned and
    # the level still comes back with everything read before it.
    level = read_level(make_ldb(corrupt='placements'))
    assert level.mesh is not None
    assert level.characters == ()
    assert level.items == ()
    assert level.props is None


def test_read_level_with_categories_and_lightmaps(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(categories=(('wood', (('a', 'C:\\a', ''),)),), lightmaps=((0, 0, b'\x01\x02'),)))
    assert level.mesh is not None
    assert len(level.mesh.meshes) == 1


def test_read_level_rejects_a_missing_map(make_ldb: Callable[..., bytes]) -> None:
    level = bytearray(make_ldb())
    level[level.index(b'\x1f')] = 0x14
    with pytest.raises(InvalidLevelError, match='Expected a map marker'):
        read_level(bytes(level))


def test_read_level_rejects_a_missing_pair(make_ldb: Callable[..., bytes]) -> None:
    level = bytearray(make_ldb())
    level[level.index(b'\x25')] = 0x14
    with pytest.raises(InvalidLevelError, match='Expected a pair marker'):
        read_level(bytes(level))


def test_read_level_rejects_a_missing_index_map(make_ldb: Callable[..., bytes]) -> None:
    level = bytearray(make_ldb())
    second = level.index(b'\x1f', level.index(b'\x1f') + 1)
    level[second] = 0x14
    with pytest.raises(InvalidLevelError, match='Expected a map marker'):
        read_level(bytes(level))


def test_read_level_rejects_a_missing_index_pair(make_ldb: Callable[..., bytes]) -> None:
    level = bytearray(make_ldb())
    second_map = level.index(b'\x1f', level.index(b'\x1f') + 1)
    level[level.index(b'\x25', second_map)] = 0x14
    with pytest.raises(InvalidLevelError, match='Expected a pair marker'):
        read_level(bytes(level))


def test_read_level_rejects_a_texture_past_the_end(make_ldb: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidLevelError, match='but the file ends'):
        read_level(make_ldb(complete=False, textures=(('C:\\A.TGA', 0, b'\x00\x01'),))[:-1])


def test_read_level_skips_a_candidate_with_an_implausible_count(
        make_ldb: Callable[..., bytes]) -> None:
    # An array marker claiming more corners than any level holds is rejected on the count alone,
    # before any corner is read.
    junk = b'\x1c\x02' + struct.pack('<i', 9_000_000)
    level = read_level(make_ldb(junk=junk))
    assert level.mesh is not None
    assert len(level.mesh.corners) == 120


def test_read_level_skips_a_candidate_that_fails_the_probe(make_ldb: Callable[..., bytes]) -> None:
    # A plausible count followed by bytes that are not corners has to fall through to the real
    # container further on.
    junk = b'\x1c\x13' + struct.pack('<h', 200) + b'\x14\x01' * 32
    level = read_level(make_ldb(junk=junk))
    assert level.mesh is not None
    assert len(level.mesh.meshes) == 1


def test_read_level_skips_a_candidate_with_an_implausible_mesh_count(
        make_ldb: Callable[..., bytes], make_mesh_container: Callable[..., bytes]) -> None:
    # The corners read cleanly, so this one is only rejected once the mesh count comes out absurd.
    level = read_level(make_ldb(junk=make_mesh_container(40, (7,), mesh_count=-1)))
    assert level.mesh is not None
    assert len(level.mesh.meshes) == 1


def test_read_level_ignores_an_exit_with_no_partner(make_ldb: Callable[..., bytes]) -> None:
    # A one-sided exit says nothing about how two rooms meet, so it cannot place anything.
    level = read_level(
        make_ldb(meshes=2,
                 world=((('::room::out', '::gone::in', (5.0, 0.0, 0.0)),), ((0, (0,), '::room'),
                                                                            (1, (1,), '::far')))))
    assert level.mesh is not None
    assert level.mesh.meshes[1].transform[9:] == (0.0, 0.0, 0.0)


def test_read_level_places_a_room_through_its_exit(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(meshes=2,
                 world=((('::room::out', '::far::in', (5.0, 1.0, 2.0)),
                         ('::far::in', '::room::out', (-5.0, -1.0, -2.0))), ((0, (0,), '::room'),
                                                                             (1, (1,), '::far')))))
    assert level.mesh is not None
    assert level.mesh.meshes[0].transform[9:] == (0.0, 0.0, 0.0)
    assert level.mesh.meshes[1].transform[9:] == (5.0, 1.0, 2.0)
    # The props and NPCs of a placed room move with it.
    assert level.characters[0].placement.transform[9:] == (1.0, 2.0, 3.0)


def test_read_level_reads_the_lightmaps(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb(lightmaps=((0, 0, b'\x00\x00\x02\x00'), (1, 0, b'\x00\x00\x02'))))
    assert [t.path for t in level.lightmaps] == ['lightmap_0.tga', 'lightmap_1.tga']
    assert level.lightmaps[0].data == b'\x00\x00\x02\x00'


def test_read_level_without_lightmaps(make_ldb: Callable[..., bytes]) -> None:
    assert read_level(make_ldb()).lightmaps == ()


def test_read_level_reads_the_faces_lightmap_field(make_ldb: Callable[..., bytes]) -> None:
    # A face names which of the level's atlases lights it.
    level = read_level(make_ldb())
    assert level.mesh is not None
    assert {f.lightmap for f in level.mesh.meshes[0].faces} == {0}


def test_read_level_reads_the_faces_flags(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb())
    assert level.mesh is not None
    assert {f.flags for f in level.mesh.meshes[0].faces} == {1}
