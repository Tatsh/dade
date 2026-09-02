from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any
import json
import struct

import pytest

from dade.maxpayne.decals import DECAL_STEP
from dade.maxpayne.gltf import GLB_MAGIC, build_glb
from dade.maxpayne.ldb import read_level
from dade.maxpayne.typing import Level, LevelGeometry, Model

if TYPE_CHECKING:
    from collections.abc import Callable


def _parse(glb: bytes) -> tuple[dict[str, Any], bytes]:
    assert glb[:4] == GLB_MAGIC
    version, length = struct.unpack_from('<II', glb, 4)
    assert version == 2
    assert length == len(glb)
    json_length = struct.unpack_from('<I', glb, 12)[0]
    assert glb[16:20] == b'JSON'
    document = json.loads(glb[20:20 + json_length])
    binary_start = 20 + json_length
    binary_length = struct.unpack_from('<I', glb, binary_start)[0]
    assert glb[binary_start + 4:binary_start + 8] == b'BIN\x00'
    return document, glb[binary_start + 8:binary_start + 8 + binary_length]


def _accessor_bytes(document: dict[str, Any], binary: bytes, index: int) -> bytes:
    view = document['bufferViews'][document['accessors'][index]['bufferView']]
    return binary[view['byteOffset']:view['byteOffset'] + view['byteLength']]


def test_build_glb_structure(make_ldb: Callable[..., bytes]) -> None:
    document, binary = _parse(build_glb(read_level(make_ldb()), name='demo'))
    assert document['asset']['version'] == '2.0'
    assert document['scenes'][0]['name'] == 'demo'
    assert document['buffers'][0]['byteLength'] == len(binary)
    assert document['nodes'][0]['name'] == 'demo_0'


def test_build_glb_writes_one_node_per_placed_mesh(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb(placements=False))
    document, _ = _parse(build_glb(level))
    assert level.mesh is not None
    assert len(document['nodes']) == len(level.mesh.meshes)


def test_build_glb_places_architecture_by_its_room(make_ldb: Callable[..., bytes]) -> None:
    # A room reached through an exit is moved by that exit's transform, and so is its mesh.
    document, _ = _parse(
        build_glb(
            read_level(
                make_ldb(meshes=2,
                         world=((('::room::out', '::far::in', (5.0, 0.0, 0.0)),
                                 ('::far::in', '::room::out', (-5.0, 0.0, 0.0))),
                                ((0, (0,), '::room'), (1, (1,), '::far')))))))
    assert document['nodes'][0]['matrix'][12:] == [0, 0, -0, 1]
    assert document['nodes'][1]['matrix'][12:] == [5, 0, -0, 1]


def test_build_glb_mirrors_a_props_transform(make_ldb: Callable[..., bytes]) -> None:
    # A prop is placed by its transform, and the depth mirror negates the Z row, column and offset.
    document, _ = _parse(
        build_glb(read_level(make_ldb(props=(('::room::door.DO', (7.0, 8.0, 9.0)),)))))
    door = next(n for n in document['nodes'] if n['name'] == '::room::door.DO')
    assert door['matrix'] == [1, 0, -0, 0, 0, 1, -0, 0, -0, -0, 1, 0, 7, 8, -9, 1]


def test_build_glb_groups_primitives_by_material(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(face_materials=(7, 9)))))
    assert len(document['meshes'][0]['primitives']) == 2


def test_build_glb_writes_the_games_texture_coordinates(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb())
    document, binary = _parse(build_glb(level))
    coord = document['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_0']
    assert document['accessors'][coord]['type'] == 'VEC2'
    assert level.mesh is not None
    raw = _accessor_bytes(document, binary, coord)
    assert struct.unpack_from('<2f', raw, 0) == pytest.approx(level.mesh.corners[0].uv)


def test_build_glb_mirrors_positions(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb())
    document, binary = _parse(build_glb(level))
    position = document['meshes'][0]['primitives'][0]['attributes']['POSITION']
    raw = _accessor_bytes(document, binary, position)
    assert level.mesh is not None
    original = level.mesh.meshes[0].positions[level.mesh.corners[0].position]
    written = struct.unpack_from('<3f', raw, 0)
    assert written == pytest.approx((original[0], original[1], -original[2]))


def test_build_glb_every_buffer_view_is_aligned(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb())))
    assert all(view['byteOffset'] % 4 == 0 for view in document['bufferViews'])


def test_build_glb_embeds_a_jpeg(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(materials=((7, 'wood', 'A.JPG'), (9, 'metal', 'B.JPG')),
                 textures=(('C:\\A.JPG', 4, b'\xff\xd8fake'),)))
    document, _ = _parse(build_glb(level))
    assert document['images'][0]['mimeType'] == 'image/jpeg'
    assert document['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index'] == 0


def test_build_glb_embeds_a_png(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(materials=((7, 'wood', 'A.PNG'), (9, 'metal', 'B.PNG')),
                 textures=(('C:\\A.PNG', 0, b'\x89PNGfake'),)))
    document, _ = _parse(build_glb(level))
    assert document['images'][0]['mimeType'] == 'image/png'


def test_build_glb_converts_a_targa(make_ldb: Callable[..., bytes]) -> None:
    from PIL import Image
    buffer = BytesIO()
    Image.new('RGB', (2, 2), (10, 20, 30)).save(buffer, format='TGA')
    level = read_level(
        make_ldb(materials=((7, 'wood', 'A.TGA'), (9, 'metal', 'B.TGA')),
                 textures=(('C:\\A.TGA', 0, buffer.getvalue()),)))
    document, _ = _parse(build_glb(level))
    assert document['images'][0]['mimeType'] == 'image/png'


def test_build_glb_skips_an_undecodable_image(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(textures=(('C:\\A.TGA', 0, b'junk'),)))))
    assert 'images' not in document
    assert 'baseColorFactor' in document['materials'][0]['pbrMetallicRoughness']


def test_build_glb_without_textures(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(textures=()))))
    assert 'images' not in document
    assert 'samplers' not in document


def test_build_glb_names_a_material_after_its_image(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb())))
    assert document['materials'][0]['name'] == 'A.TGA'


def test_build_glb_skips_faces_the_engine_does_not_draw(make_ldb: Callable[..., bytes]) -> None:
    hidden = read_level(
        make_ldb(materials=((7, 'dummy', 'A.TGA'), (9, 'charactercollision_nodraw', 'B.TGA')),
                 placements=False))
    document, _ = _parse(build_glb(hidden))
    # Every face is hidden, so the mesh path adds nothing and the BSP fallback takes over.
    assert len(document['nodes']) == 1
    assert 'matrix' not in document['nodes'][0]


def test_build_glb_writes_the_sky_flat(make_ldb: Callable[..., bytes]) -> None:
    # Skybox faces close a level off where it opens to the sky, so dropping them puts a hole
    # through it. They are drawn with one flat emissive colour instead of their placeholder image.
    document, _ = _parse(
        build_glb(
            read_level(
                make_ldb(materials=((7, 'skybox', 'A.TGA'), (9, 'metal', 'B.JPG')),
                         placements=False))))
    sky = [m for m in document['materials'] if m['name'] == 'skybox']
    assert len(sky) == 1
    assert 'baseColorTexture' not in sky[0]['pbrMetallicRoughness']
    # Written unlit so it reads the same from every angle rather than shading like a wall.
    assert 'KHR_materials_unlit' in sky[0]['extensions']
    assert document['extensionsUsed'] == ['KHR_materials_unlit']


def test_build_glb_falls_back_to_the_bsp_faces(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(triangles=0))))
    assert len(document['nodes']) == 1
    assert 'TEXCOORD_0' not in document['meshes'][0]['primitives'][0]['attributes']


def test_build_glb_draws_a_face_whose_material_is_missing(make_ldb: Callable[..., bytes]) -> None:
    # Nothing says the face is hidden, so an unknown identifier has to draw rather than vanish.
    document, _ = _parse(build_glb(read_level(make_ldb(face_materials=(7, 99)))))
    assert len(document['meshes'][0]['primitives']) == 2


def test_build_glb_reuses_a_material_across_meshes(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(meshes=2, placements=False))))
    assert len(document['nodes']) == 2
    assert len(document['materials']) == 2
    assert (document['meshes'][0]['primitives'][0]['material'] == document['meshes'][1]
            ['primitives'][0]['material'])


def test_build_glb_reverses_a_fan_that_faces_the_wrong_way(make_ldb: Callable[..., bytes]) -> None:
    forward = _parse(build_glb(read_level(make_ldb(layout='wind_back'))))
    reversed_ = _parse(build_glb(read_level(make_ldb())))
    a = _accessor_bytes(*forward, forward[0]['meshes'][0]['primitives'][0]['indices'])
    b = _accessor_bytes(*reversed_, reversed_[0]['meshes'][0]['primitives'][0]['indices'])
    assert struct.unpack_from('<3I', a, 0)[::-1] == struct.unpack_from('<3I', b, 0)


def test_build_glb_drops_a_mesh_whose_face_runs_past_the_corners(
        make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(corrupt='faces', placements=False))))
    # The mesh is abandoned, so only the BSP fallback node survives.
    assert len(document['nodes']) == 1
    assert 'matrix' not in document['nodes'][0]


def test_build_glb_drops_a_mesh_whose_corner_runs_past_the_positions(
        make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(corrupt='corners', placements=False))))
    assert len(document['nodes']) == 1
    assert 'matrix' not in document['nodes'][0]


def test_build_glb_rejects_a_level_with_nothing_to_draw() -> None:
    with pytest.raises(ValueError, match='no faces'):
        build_glb(
            Level(geometry=LevelGeometry(polygons=(), vertices=()),
                  materials={},
                  mesh=None,
                  textures=()))


def _png(size: tuple[int, int], colour: tuple[int, int, int]) -> bytes:
    from PIL import Image
    buffer = BytesIO()
    Image.new('RGB', size, colour).save(buffer, format='PNG')
    return buffer.getvalue()


def _grey(size: tuple[int, int], level: int) -> bytes:
    from PIL import Image
    buffer = BytesIO()
    Image.new('L', size, level).save(buffer, format='PNG')
    return buffer.getvalue()


def _gradient(size: tuple[int, int]) -> bytes:
    from PIL import Image
    image = Image.new('L', size)
    image.putdata(
        [(x * 255) // max(size[0] - 1, 1) for _ in range(size[1]) for x in range(size[0])])
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def _masked(**kwargs: object) -> dict[str, object]:
    """Build a level naming a colour image and an alpha mask for material 7."""
    return {
        'materials': ((7, 'leaves', 'PLANT.JPG'), (9, 'metal', 'B.JPG')),
        'categories': (('leaves', (('PLANT.JPG', 'X:\\plant.png', 'X:\\plant_alpha.png'),)),),
        **kwargs
    }


def test_build_glb_cuts_out_a_masked_material(make_ldb: Callable[..., bytes]) -> None:
    # A mask that is only ever black or white is a cut-out, so it alpha-tests rather than blends.
    level = read_level(
        make_ldb(**_masked(textures=(('X:\\plant.png', 0, _png((4, 4), (20, 200, 20))),
                                     ('X:\\plant_alpha.png', 0, _grey((4, 4), 255))))))
    assert level.materials[7].alpha == 'X:\\plant_alpha.png'
    document, _ = _parse(build_glb(level))
    material = next(m for m in document['materials'] if m['name'] == 'PLANT.JPG')
    assert material['alphaMode'] == 'MASK'
    assert material['alphaCutoff'] == pytest.approx(0.5)
    assert material['doubleSided'] is True
    assert 'baseColorTexture' in material['pbrMetallicRoughness']


def test_build_glb_blends_a_gradient_mask(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(**_masked(textures=(('X:\\plant.png', 0, _png((16, 4), (20, 200, 20))),
                                     ('X:\\plant_alpha.png', 0, _gradient((16, 4)))))))
    document, _ = _parse(build_glb(level))
    material = next(m for m in document['materials'] if m['name'] == 'PLANT.JPG')
    assert material['alphaMode'] == 'BLEND'
    assert 'alphaCutoff' not in material


def test_build_glb_resizes_a_mask_to_its_colour(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(**_masked(textures=(('X:\\plant.png', 0, _png((8, 8), (20, 200, 20))),
                                     ('X:\\plant_alpha.png', 0, _grey((4, 4), 255))))))
    document, _ = _parse(build_glb(level))
    assert any(image['name'].endswith('plant_alpha.png') for image in document['images'])


def test_build_glb_does_not_embed_a_mask_on_its_own(make_ldb: Callable[..., bytes]) -> None:
    # The mask is only ever read through the material that names it.
    level = read_level(
        make_ldb(**_masked(textures=(('X:\\plant.png', 0, _png((4, 4), (20, 200, 20))),
                                     ('X:\\plant_alpha.png', 0, _grey((4, 4), 255))))))
    document, _ = _parse(build_glb(level))
    assert not any(image['name'] == 'X:\\plant_alpha.png' for image in document['images'])


def test_build_glb_falls_back_when_a_mask_will_not_decode(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(
        make_ldb(**_masked(textures=(('X:\\plant.png', 0, _png((4, 4), (20, 200, 20))),
                                     ('X:\\plant_alpha.png', 0, b'junk')))))
    document, _ = _parse(build_glb(level))
    material = next(m for m in document['materials'] if m['name'] == 'PLANT.JPG')
    assert 'baseColorFactor' in material['pbrMetallicRoughness']
    assert 'alphaMode' not in material


def test_build_glb_reuses_one_composed_texture(make_ldb: Callable[..., bytes]) -> None:
    # Two materials naming the same pair must not embed the picture twice.
    level = read_level(
        make_ldb(materials=((7, 'leaves', 'PLANT.JPG'), (9, 'leaves', 'PLANT2.JPG')),
                 categories=(('leaves', (('PLANT.JPG', 'X:\\plant.png', 'X:\\plant_alpha.png'),
                                         ('PLANT2.JPG', 'X:\\plant.png', 'X:\\plant_alpha.png'))),),
                 textures=(('X:\\plant.png', 0, _png(
                     (4, 4), (20, 200, 20))), ('X:\\plant_alpha.png', 0, _grey((4, 4), 255)))))
    document, _ = _parse(build_glb(level))
    assert sum(1 for image in document['images'] if ' + ' in image['name']) == 1
    materials = [m for m in document['materials'] if m['name'].startswith('PLANT')]
    assert len({m['pbrMetallicRoughness']['baseColorTexture']['index'] for m in materials}) == 1


def _model(make_model: Callable[..., bytes], **kwargs: object) -> Model:
    from dade.maxpayne.model import read_model
    from dade.maxpayne.typing import TextureImage
    model = read_model(make_model(**kwargs))
    return model._replace(textures=tuple(
        TextureImage(data=_png((4, 4), (10, 20, 30)), kind=0, path=name)
        for name in dict.fromkeys(model.materials.values())))


def test_build_glb_draws_an_npc_with_its_model(make_ldb: Callable[..., bytes],
                                               make_model: Callable[..., bytes]) -> None:
    level = read_level(make_ldb())
    document, _ = _parse(build_glb(level, models={'character:transit_cop': _model(make_model)}))
    node = next(n for n in document['nodes'] if n['name'].startswith('character:'))
    assert 'mesh' in node
    assert node['matrix'][12:] == [1, 2, -3, 1]
    material = document['materials'][document['meshes'][node['mesh']]['primitives'][0]['material']]
    assert material['name'] == 'Skin (skin.png)'
    assert 'baseColorTexture' in material['pbrMetallicRoughness']


def test_build_glb_leaves_a_placement_empty_without_a_model(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb())))
    node = next(n for n in document['nodes'] if n['name'].startswith('character:'))
    assert 'mesh' not in node


def test_build_glb_leaves_a_placement_empty_for_a_model_with_no_faces(
        make_ldb: Callable[..., bytes], make_model: Callable[..., bytes]) -> None:
    empty = _model(make_model, faces=(), coord_faces=(), face_materials=())
    document, _ = _parse(build_glb(read_level(make_ldb()), models={'item:ammo_ingram': empty}))
    node = next(n for n in document['nodes'] if n['name'].startswith('item:'))
    assert 'mesh' not in node


def test_build_glb_shares_one_model_material_between_placements(
        make_ldb: Callable[..., bytes], make_model: Callable[..., bytes]) -> None:
    shared = _model(make_model)
    document, _ = _parse(
        build_glb(read_level(make_ldb()),
                  models={
                      'character:transit_cop': shared,
                      'item:ammo_ingram': shared
                  }))
    drawn = [n for n in document['nodes'] if n['name'].startswith(('character:', 'item:'))]
    indices = {document['meshes'][n['mesh']]['primitives'][0]['material'] for n in drawn}
    assert len(drawn) == 2
    assert len(indices) == 1


def test_build_glb_falls_back_when_a_model_names_no_image(make_ldb: Callable[..., bytes],
                                                          make_model: Callable[..., bytes]) -> None:
    from dade.maxpayne.model import read_model
    bare = read_model(make_model())
    document, _ = _parse(build_glb(read_level(make_ldb()), models={'character:transit_cop': bare}))
    node = next(n for n in document['nodes'] if n['name'].startswith('character:'))
    material = document['materials'][document['meshes'][node['mesh']]['primitives'][0]['material']]
    assert 'baseColorFactor' in material['pbrMetallicRoughness']


def test_build_glb_names_each_mesh_of_a_multipart_model(make_ldb: Callable[..., bytes],
                                                        make_model: Callable[..., bytes]) -> None:
    from dade.maxpayne.model import read_model
    one = read_model(make_model())
    both = one._replace(meshes=one.meshes + one.meshes)
    document, _ = _parse(build_glb(read_level(make_ldb()), models={'character:transit_cop': both}))
    named = [n['name'] for n in document['nodes'] if n['name'].startswith('character:')]
    assert named == ['character:transit_cop ::room::e1 #0', 'character:transit_cop ::room::e1 #1']


def test_build_glb_skips_a_models_empty_mesh(make_ldb: Callable[..., bytes],
                                             make_model: Callable[..., bytes]) -> None:
    from dade.maxpayne.model import read_model
    one = read_model(make_model())
    hollow = read_model(make_model(faces=(), coord_faces=(), face_materials=()))
    mixed = one._replace(meshes=one.meshes + hollow.meshes)
    document, _ = _parse(build_glb(read_level(make_ldb()), models={'character:transit_cop': mixed}))
    assert len([n for n in document['nodes'] if n['name'].startswith('character:')]) == 1


_SWING = ((0.0, 4.0, 0.0), (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), 2)
"""A clip that slides its prop four units up, in `make_ldb`'s ``motion`` shape."""


def _clip(document: dict[str, Any], name: str) -> dict[str, Any]:
    return next(a for a in document['animations'] if a['name'].endswith(name))


def _sampler_values(document: dict[str, Any], binary: bytes, accessor: int,
                    size: int) -> list[tuple[float, ...]]:
    raw = _accessor_bytes(document, binary, accessor)
    return [struct.unpack_from(f'<{size}f', raw, at) for at in range(0, len(raw), 4 * size)]


def test_build_glb_animates_a_prop(make_ldb: Callable[..., bytes]) -> None:
    # A prop that only slides gets no rotation channel; the level drives the two separately.
    document, _ = _parse(build_glb(read_level(make_ldb(motion=_SWING))))
    clip = _clip(document, 'clip0')
    assert [c['target']['path'] for c in clip['channels']] == ['translation']
    node = document['nodes'][clip['channels'][0]['target']['node']]
    assert node['name'] == '::room::door.DO'
    # A node carrying a matrix cannot be animated, so an animated prop is written as separate
    # translation, rotation and scale.
    assert 'matrix' not in node
    assert node['translation'] == [7, 8, -9]


def test_build_glb_drives_both_channels_of_a_prop_that_slides_and_turns(
        make_ldb: Callable[..., bytes], bases: dict[str, Any]) -> None:
    document, _ = _parse(
        build_glb(read_level(make_ldb(motion=((0.0, 4.0, 0.0), bases['half_turn'], 2)))))
    clip = _clip(document, 'clip0')
    assert [c['target']['path'] for c in clip['channels']] == ['translation', 'rotation']


def test_build_glb_starts_a_clip_where_the_prop_rests(make_ldb: Callable[..., bytes],
                                                      bases: dict[str, Any]) -> None:
    # The first keyframe has to equal the node's own placement or the prop jumps when a clip starts.
    document, binary = _parse(
        build_glb(read_level(make_ldb(motion=((0.0, 4.0, 0.0), bases['half_turn'], 2)))))
    clip = _clip(document, 'clip0')
    node = document['nodes'][clip['channels'][0]['target']['node']]
    sampler = clip['samplers'][clip['channels'][0]['sampler']]
    first = _sampler_values(document, binary, sampler['output'], 3)[0]
    assert first == pytest.approx(node['translation'])
    rotation = clip['samplers'][clip['channels'][1]['sampler']]
    assert _sampler_values(document, binary, rotation['output'],
                           4)[0] == pytest.approx(node['rotation'])


def test_build_glb_carries_a_clip_to_its_end(make_ldb: Callable[..., bytes]) -> None:
    document, binary = _parse(build_glb(read_level(make_ldb(motion=_SWING))))
    clip = _clip(document, 'clip0')
    sampler = clip['samplers'][clip['channels'][0]['sampler']]
    values = _sampler_values(document, binary, sampler['output'], 3)
    assert values[-1] == pytest.approx([7, 12, -9])


def test_build_glb_times_a_clip_over_its_duration(make_ldb: Callable[..., bytes]) -> None:
    document, binary = _parse(build_glb(read_level(make_ldb(motion=_SWING))))
    clip = _clip(document, 'clip0')
    sampler = clip['samplers'][clip['channels'][0]['sampler']]
    times = _sampler_values(document, binary, sampler['input'], 1)
    assert times[0] == pytest.approx((0.0,))
    assert times[-1] == pytest.approx((1.0,))


def test_build_glb_leaves_a_still_prop_on_a_matrix(make_ldb: Callable[..., bytes]) -> None:
    # A clip whose two poses are the same moves nothing, so it is not worth a glTF animation.
    document, _ = _parse(build_glb(read_level(make_ldb())))
    assert 'animations' not in document
    node = next(n for n in document['nodes'] if n['name'] == '::room::door.DO')
    assert 'matrix' in node


def test_build_glb_turns_a_prop_about_its_axis(make_ldb: Callable[..., bytes],
                                               bases: dict[str, Any]) -> None:
    # Half a turn is the case a quaternion cannot read straight off the matrix diagonal.
    document, binary = _parse(
        build_glb(read_level(make_ldb(motion=((0.0, 1.0, 0.0), bases['half_turn'], 2)))))
    clip = _clip(document, 'clip0')
    rotation = clip['samplers'][clip['channels'][1]['sampler']]
    values = _sampler_values(document, binary, rotation['output'], 4)
    assert values[0] == pytest.approx((0.0, 0.0, 0.0, 1.0))
    assert abs(values[-1][1]) == pytest.approx(1.0)
    assert all(abs(sum(v * v for v in value) - 1.0) < 1e-5 for value in values)


def test_build_glb_walks_a_wide_turn_along_its_arc(make_ldb: Callable[..., bytes],
                                                   bases: dict[str, Any]) -> None:
    # Halfway through half a turn is a quarter turn, which straight interpolation would not give.
    document, binary = _parse(
        build_glb(read_level(make_ldb(motion=((0.0, 1.0, 0.0), bases['half_turn'], 3)))))
    clip = _clip(document, 'clip0')
    rotation = clip['samplers'][clip['channels'][1]['sampler']]
    middle = _sampler_values(document, binary, rotation['output'], 4)[1]
    assert abs(middle[1]) == pytest.approx(0.5 ** 0.5, abs=1e-4)


def test_build_glb_keeps_a_reflected_prop_placed(make_ldb: Callable[..., bytes],
                                                 bases: dict[str, Any]) -> None:
    # A left-handed basis is no rotation at all, so it has to survive as a negative scale.
    document, _ = _parse(
        build_glb(read_level(make_ldb(motion=((0.0, 1.0, 0.0), bases['reflected'], 2)))))
    clip = _clip(document, 'clip0')
    node = document['nodes'][clip['channels'][0]['target']['node']]
    assert node['scale'][0] == pytest.approx(1.0)


def test_build_glb_thins_a_long_curve(make_ldb: Callable[..., bytes]) -> None:
    # A shipped door carries 256 samples of a smooth ease; the motion does not need them.
    document, binary = _parse(build_glb(read_level(make_ldb(motion=(_SWING[0], _SWING[1], 50)))))
    clip = _clip(document, 'clip0')
    times = _sampler_values(document, binary, clip['samplers'][0]['input'], 1)
    assert len(times) <= 24
    assert times[-1] == pytest.approx((1.0,))


def test_build_glb_walks_a_small_turn_straight(make_ldb: Callable[..., bytes],
                                               bases: dict[str, Any]) -> None:
    # Two degrees is worth a channel but far too close to take the long way round.
    document, binary = _parse(
        build_glb(read_level(make_ldb(motion=((0.0, 0.0, 0.0), bases['tilt'], 3)))))
    clip = _clip(document, 'clip0')
    assert [c['target']['path'] for c in clip['channels']] == ['rotation']
    values = _sampler_values(document, binary, clip['samplers'][0]['output'], 4)
    assert all(abs(sum(v * v for v in value) - 1.0) < 1e-5 for value in values)


def test_build_glb_settles_a_prop_whose_clips_drive_nothing(make_ldb: Callable[..., bytes],
                                                            bases: dict[str, Any]) -> None:
    # The prop ends somewhere else, but only in size, which no channel carries.
    document, _ = _parse(
        build_glb(read_level(make_ldb(motion=((0.0, 0.0, 0.0), bases['stretched'], 2)))))
    assert 'animations' not in document
    node = next(n for n in document['nodes'] if n['name'] == '::room::door.DO')
    assert 'matrix' in node
    assert 'translation' not in node


def test_build_glb_lights_a_face_with_its_atlas(make_ldb: Callable[..., bytes]) -> None:
    # The atlas goes in the occlusion slot on the second coordinate set.
    document, _ = _parse(
        build_glb(read_level(make_ldb(lightmaps=((0, 0, _png((4, 4), (200, 200, 200))),)))))
    material = next(m for m in document['materials'] if 'occlusionTexture' in m)
    assert material['occlusionTexture']['texCoord'] == 1
    assert material['name'].endswith('+ lightmap 0')
    assert all('TEXCOORD_1' in p['attributes'] for m in document['meshes'] for p in m['primitives'])


def test_build_glb_writes_the_second_coordinate_set(make_ldb: Callable[..., bytes]) -> None:
    level = read_level(make_ldb(lightmaps=((0, 0, _png((4, 4), (200, 200, 200))),)))
    document, binary = _parse(build_glb(level))
    coord = document['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_1']
    assert level.mesh is not None
    raw = _accessor_bytes(document, binary, coord)
    assert struct.unpack_from('<2f', raw, 0) == pytest.approx(level.mesh.corners[0].lightmap_uv)


def test_build_glb_shares_one_atlas_between_materials(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(
        build_glb(
            read_level(
                make_ldb(face_materials=(7, 9), lightmaps=((0, 0, _png((4, 4),
                                                                       (200, 200, 200))),)))))
    lit = [m for m in document['materials'] if 'occlusionTexture' in m]
    assert len(lit) == 2
    assert len({m['occlusionTexture']['index'] for m in lit}) == 1


def test_build_glb_without_an_atlas_for_a_face(make_ldb: Callable[..., bytes]) -> None:
    # The face names atlas nought but the level ships none, so nothing is attached.
    document, _ = _parse(build_glb(read_level(make_ldb())))
    assert not any('occlusionTexture' in m for m in document['materials'])


def test_build_glb_skips_an_undecodable_atlas(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(build_glb(read_level(make_ldb(lightmaps=((0, 0, b'junk'),)))))
    assert not any('occlusionTexture' in m for m in document['materials'])


def test_build_glb_lifts_a_face_off_the_one_it_covers(make_ldb: Callable[..., bytes]) -> None:
    # The triangles lie in one plane over the same ground, the way a level lays graffiti on a
    # wall, and draw with different materials, so one has to come off the other or a depth buffer
    # cannot tell which is in front.
    document, binary = _parse(
        build_glb(read_level(make_ldb(face_materials=(7, 9), layout='stacked'))))
    heights: set[float] = set()
    for primitive in document['meshes'][0]['primitives']:
        raw = _accessor_bytes(document, binary, primitive['attributes']['POSITION'])
        heights.update(
            struct.unpack_from('<3f', raw, corner * 12)[1] for corner in range(len(raw) // 12))
    # One face keeps the plane and each face laid over it rises another step.
    assert sorted(heights)[:3] == pytest.approx([0.0, DECAL_STEP, 2 * DECAL_STEP])


def test_build_glb_leaves_a_face_nothing_covers_alone(make_ldb: Callable[..., bytes]) -> None:
    document, binary = _parse(build_glb(read_level(make_ldb(face_materials=(7,)))))
    position = document['meshes'][0]['primitives'][0]['attributes']['POSITION']
    raw = _accessor_bytes(document, binary, position)
    heights = [struct.unpack_from('<3f', raw, corner * 12)[1] for corner in range(6)]
    assert heights == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]


def test_build_glb_shares_one_sky_between_materials(make_ldb: Callable[..., bytes]) -> None:
    document, _ = _parse(
        build_glb(
            read_level(
                make_ldb(materials=((7, 'skybox', 'A.TGA'), (9, 'skybox', 'B.JPG')),
                         face_materials=(7, 9),
                         placements=False))))
    assert len([m for m in document['materials'] if m['name'] == 'skybox']) == 1


def test_build_glb_keeps_a_face_with_no_side_as_written(make_ldb: Callable[..., bytes]) -> None:
    # Every corner is on one line, so nothing in the fan says which way the face points and the
    # exporter has to leave the order alone rather than read a direction out of noise.
    document, binary = _parse(build_glb(read_level(make_ldb(layout='collinear'))))
    indices = document['meshes'][0]['primitives'][0]['indices']
    raw = _accessor_bytes(document, binary, indices)
    assert struct.unpack_from('<3I', raw, 0) == (0, 1, 2)
