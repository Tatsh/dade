from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import math
import struct

import pytest

from dade.sopranos.gltf import GLB_MAGIC, build_glb, build_prop_glb, write_glb, write_prop_glb
from dade.sopranos.olv import Placement
from dade.sopranos.texture import iter_geometry_textures

from .conftest import (
    FORMAT_RGBA,
    build_geometry,
    build_image,
    build_library,
    build_section,
    mesh_packet,
    prop_packet,
)

if TYPE_CHECKING:
    from pathlib import Path

_TRIANGLE = [(0.0, 0.0, 0.0, 0.25, 0.5), (1.0, 0.0, 0.0, 0.75, 0.5), (0.0, 1.0, 0.0, 0.25, 0.9)]
_PROP_TRIANGLE = [(0.0, 0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0, 1.0)]
_PACKET_BODY_AT = 48
_ROW = 16
_GROUP = 80


def opaque_pixels(colour: tuple[int, int, int] = (200, 40, 40)) -> bytes:
    """
    Give four opaque pixels of one colour.

    Parameters
    ----------
    colour : tuple[int, int, int]
        The red, green, and blue channels.

    Returns
    -------
    bytes
        Sixteen bytes of RGBA.
    """
    return bytes([*colour, 0x80]) * 4


def paint(packet: bytes, colour: tuple[int, int, int]) -> bytes:
    """
    Give a packet's vertices a colour.

    Vertex colour lives in the low byte of the U, V, and X floats, so it is written there.

    Parameters
    ----------
    packet : bytes
        A packet from :py:func:`~tests.sopranos.conftest.mesh_packet`.
    colour : tuple[int, int, int]
        The red, green, and blue channels.

    Returns
    -------
    bytes
        The packet with every vertex painted.
    """
    raw = bytearray(packet)
    for at in range(_PACKET_BODY_AT, len(raw) - _ROW, _GROUP):
        for row in range(4):
            for channel, value in enumerate(colour):
                raw[at + row * _ROW + channel * 4] = value
    return bytes(raw)


def level(images: list[bytes] | None = None,
          packets: list[bytes] | None = None,
          *,
          claimed: bool = True) -> bytes:
    """
    Build a level blob whose material points at its first embedded image.

    Parameters
    ----------
    images : list[bytes] | None
        Image records to embed.
    packets : list[bytes] | None
        Packets for the single mesh.
    claimed : bool
        Give the mesh a material.

    Returns
    -------
    bytes
        The blob.
    """
    images = [build_image('art/wall.tga', 2, 2, FORMAT_RGBA, opaque_pixels())
              ] if images is None else images
    packets = [paint(mesh_packet(_TRIANGLE), (200, 40, 40))] if packets is None else packets
    blob = bytearray(
        build_geometry([('art/wall.tga', 0)], [(1, packets)], {0: 0} if claimed else {}, images))
    found = list(iter_geometry_textures(bytes(blob)))
    if found:
        table = struct.unpack_from('<I', blob, 0x50)[0]
        struct.pack_into('<I', blob, table + 0x10, found[0].data_offset - 0x80)
    return bytes(blob)


def document(glb: bytes) -> dict[str, Any]:
    """
    Read a GLB's JSON chunk.

    Parameters
    ----------
    glb : bytes
        The file.

    Returns
    -------
    dict[str, Any]
        The glTF document.
    """
    length = struct.unpack_from('<I', glb, 12)[0]
    parsed: dict[str, Any] = json.loads(glb[20:20 + length])
    return parsed


def test_build_glb_writes_a_container_with_both_chunks() -> None:
    glb = build_glb(level())
    assert glb is not None
    assert struct.unpack_from('<3I', glb)[0] == GLB_MAGIC
    assert struct.unpack_from('<I', glb, 8)[0] == len(glb)
    doc = document(glb)
    assert doc['asset']['generator'] == 'dade'
    assert doc['materials'][0]['name'] == 'wall.tga'
    assert doc['images'][0]['mimeType'] == 'image/png'


def test_build_glb_names_the_generator() -> None:
    glb = build_glb(level(), generator='thing')
    assert glb is not None
    assert document(glb)['asset']['generator'] == 'thing'


def test_build_glb_can_draw_both_faces() -> None:
    glb = build_glb(level(), double_sided=True)
    assert glb is not None
    assert document(glb)['materials'][0]['doubleSided'] is True


def test_build_glb_gives_up_without_meshes() -> None:
    assert build_glb(build_geometry([], [], {})) is None


def test_build_glb_gives_up_when_every_triangle_is_degenerate() -> None:
    flat = [(0.0, 0.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0, 0.0), (0.0, 2.0, 0.0, 0.0, 0.0)]
    packet = mesh_packet([flat[0], flat[0], flat[0], flat[1], flat[2]])
    assert build_glb(level(packets=[packet])) is None


def test_build_glb_leaves_a_mesh_without_a_material_unassigned() -> None:
    glb = build_glb(level(claimed=False))
    assert glb is not None
    assert 'material' not in document(glb)['meshes'][0]['primitives'][0]


def test_build_glb_replaces_a_texture_coordinate_that_is_not_finite() -> None:
    packet = bytearray(mesh_packet(_TRIANGLE))
    struct.pack_into('<f', packet, _PACKET_BODY_AT, float('nan'))
    glb = build_glb(level(packets=[bytes(packet)]))
    assert glb is not None
    doc = document(glb)
    accessor = doc['accessors'][doc['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_0']]
    assert accessor['count'] == 3


def test_build_glb_blends_a_plain_white_glow_sprite() -> None:
    white = build_image('art/bloom.tga', 2, 2, FORMAT_RGBA, bytes([255, 255, 255, 0x80]) * 4)
    glb = build_glb(level(images=[white]))
    assert glb is not None
    assert document(glb)['materials'][0]['alphaMode'] == 'BLEND'


@pytest.mark.parametrize('name', ['art/add_neon.tga', 'art/sub_shade.tga'])
def test_build_glb_blends_an_overlay_decal(*, name: str) -> None:
    overlay = build_image(name, 2, 2, FORMAT_RGBA, opaque_pixels((10, 20, 30)))
    glb = build_glb(level(images=[overlay]))
    assert glb is not None
    assert document(glb)['materials'][0]['alphaMode'] == 'BLEND'


def test_build_glb_masks_a_cut_out_texture() -> None:
    pixels = bytes([200, 40, 40, 0x80, 200, 40, 40, 0x00, 200, 40, 40, 0x00, 200, 40, 40, 0x00])
    cut = build_image('art/fence.tga', 2, 2, FORMAT_RGBA, pixels)
    glb = build_glb(level(images=[cut]))
    assert glb is not None
    assert document(glb)['materials'][0]['alphaMode'] == 'MASK'


def test_build_glb_blends_a_translucent_texture() -> None:
    pixels = bytes([200, 40, 40, 0x40] * 4)
    glass = build_image('art/glass.tga', 2, 2, FORMAT_RGBA, pixels)
    glb = build_glb(level(images=[glass]))
    assert glb is not None
    assert document(glb)['materials'][0]['alphaMode'] == 'BLEND'


def test_build_glb_gives_a_black_mesh_its_own_shadow_material() -> None:
    black = [(0.0, 0.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0, 0.0), (0.0, 2.0, 0.0, 0.0, 0.0)]
    glb = build_glb(level(packets=[mesh_packet(black)]))
    assert glb is not None
    doc = document(glb)
    material = doc['materials'][doc['meshes'][0]['primitives'][0]['material']]
    assert material['name'] == 'shadow'
    assert material['alphaMode'] == 'BLEND'


def _library() -> bytes:
    image = build_image('body.tga', 2, 2, FORMAT_RGBA, opaque_pixels())
    section = build_section('lib/guy', [('body.tga',)],
                            [('GUY_BODY', [(0, [prop_packet(_PROP_TRIANGLE)])]),
                             ('*BODY17', [(0, [prop_packet(_PROP_TRIANGLE)])]),
                             ('*BODY18', [(0, [prop_packet(_PROP_TRIANGLE)])])])
    return build_library([section], [image])


def test_build_glb_places_a_prop_where_the_level_puts_it() -> None:
    placement = Placement('iGuy', 'guy', 10.0, 20.0, 30.0, math.pi / 2)
    glb = build_glb(level(), libraries=[_library()], placements=[placement])
    assert glb is not None
    node = next(n for n in document(glb)['nodes'] if n.get('name') == 'iGuy')
    assert node['translation'] == [10.0, 30.0, -20.0]
    assert math.isclose(node['rotation'][1], math.sin(math.pi / 4))


def test_build_glb_wears_one_of_each_interchangeable_piece() -> None:
    placement = Placement('iGuy', 'guy', 10.0, 20.0, 0.0, 0.0)
    glb = build_glb(level(), libraries=[_library()], placements=[placement])
    assert glb is not None
    doc = document(glb)
    mesh = doc['meshes'][next(n for n in doc['nodes'] if n.get('name') == 'iGuy')['mesh']]
    # The body plus one of the two jackets, never both.
    assert len(mesh['primitives']) == 2


def test_build_glb_skips_a_placement_with_no_position() -> None:
    placement = Placement('iStub', 'guy', 0.0, 0.0, 0.0, 0.0)
    glb = build_glb(level(), libraries=[_library()], placements=[placement])
    assert glb is not None
    assert not any(n.get('name') == 'iStub' for n in document(glb)['nodes'])


def test_build_glb_skips_a_placement_no_library_holds() -> None:
    placement = Placement('iGhost', 'nobody', 1.0, 2.0, 3.0, 0.0)
    glb = build_glb(level(), libraries=[_library()], placements=[placement])
    assert glb is not None
    assert not any(n.get('name') == 'iGhost' for n in document(glb)['nodes'])


def test_build_glb_reuses_one_mesh_for_repeated_placements() -> None:
    placements = [
        Placement('iOne', 'guy', 1.0, 2.0, 0.0, 0.0),
        Placement('iTwo', 'guy', 3.0, 4.0, 0.0, 0.0)
    ]
    glb = build_glb(level(), libraries=[_library()], placements=placements)
    assert glb is not None
    doc = document(glb)
    nodes = [n for n in doc['nodes'] if n.get('name') in {'iOne', 'iTwo'}]
    assert len({node['mesh'] for node in nodes}) == 1


def test_build_glb_leaves_a_prop_unassigned_when_its_texture_is_missing() -> None:
    section = build_section('lib/guy', [('absent.tga',)],
                            [('GUY_BODY', [(0, [prop_packet(_PROP_TRIANGLE)])])])
    placement = Placement('iGuy', 'guy', 1.0, 2.0, 3.0, 0.0)
    glb = build_glb(level(), libraries=[build_library([section])], placements=[placement])
    assert glb is not None
    doc = document(glb)
    mesh = doc['meshes'][next(n for n in doc['nodes'] if n.get('name') == 'iGuy')['mesh']]
    assert 'material' not in mesh['primitives'][0]


def test_build_prop_glb_gives_each_object_a_node() -> None:
    glb = build_prop_glb(_library())
    assert glb is not None
    doc = document(glb)
    assert [node['name'] for node in doc['nodes']] == ['guy']
    assert doc['materials'][0]['name'] == 'body.tga'


def test_build_prop_glb_gives_up_on_an_empty_library() -> None:
    assert build_prop_glb(build_library([])) is None


def test_build_prop_glb_gives_up_when_a_section_draws_nothing() -> None:
    section = build_section('lib/x', [('a.tga',)], [('thing', [(0, [])])])
    assert build_prop_glb(build_library([section])) is None


def test_build_prop_glb_leaves_a_missing_texture_unassigned() -> None:
    section = build_section('lib/x', [('absent.tga',)],
                            [('thing', [(0, [prop_packet(_PROP_TRIANGLE)])])])
    glb = build_prop_glb(build_library([section]))
    assert glb is not None
    assert 'material' not in document(glb)['meshes'][0]['primitives'][0]


def test_build_glb_leaves_a_material_plain_when_no_image_backs_it() -> None:
    packet = paint(mesh_packet(_TRIANGLE), (200, 40, 40))
    blob = build_geometry([('art/wall.tga', 0)], [(1, [packet])], {0: 0})
    glb = build_glb(blob)
    assert glb is not None
    doc = document(glb)
    assert 'baseColorTexture' not in doc['materials'][0]['pbrMetallicRoughness']
    assert 'textures' not in doc


def test_build_prop_glb_keeps_skin_solid_even_when_it_looks_cut_out() -> None:
    pixels = bytes([200, 150, 120, 128, 200, 150, 120, 0, 200, 150, 120, 0, 200, 150, 120, 0])
    skin = build_image('tony_body.tga', 2, 2, FORMAT_RGBA, pixels)
    section = build_section('lib/tony', [('tony_body.tga',)],
                            [('TONY', [(0, [prop_packet(_PROP_TRIANGLE)])])])
    glb = build_prop_glb(build_library([section], [skin]))
    assert glb is not None
    assert document(glb)['materials'][0]['alphaMode'] == 'OPAQUE'


def test_build_prop_glb_drops_a_degenerate_triangle_but_keeps_its_neighbour() -> None:
    same = (0.0, 0.0, 0.0, 0.0, 0.0)
    packet = prop_packet([same, same, same, *_PROP_TRIANGLE])
    section = build_section('lib/x', [('a.tga',)], [('thing', [(0, [packet])])])
    glb = build_prop_glb(build_library([section]))
    assert glb is not None
    doc = document(glb)
    indices = doc['accessors'][doc['meshes'][0]['primitives'][0]['indices']]
    assert indices['count'] == 3


def test_build_prop_glb_drops_a_group_whose_triangles_are_all_degenerate() -> None:
    same = (0.0, 0.0, 0.0, 0.0, 0.0)
    section = build_section('lib/x', [('a.tga',)],
                            [('thing', [(0, [prop_packet([same, same, same])])])])
    assert build_prop_glb(build_library([section])) is None


def test_build_glb_renders_a_librarys_images_once_for_all_its_textures() -> None:
    first = build_image('shirt.tga', 2, 2, FORMAT_RGBA, opaque_pixels((20, 60, 200)))
    second = build_image('shoes.tga', 2, 2, FORMAT_RGBA, opaque_pixels((10, 10, 10)))
    section = build_section('lib/guy', [('shirt.tga',), ('shoes.tga',)],
                            [('SHIRT', [(0, [prop_packet(_PROP_TRIANGLE)])]),
                             ('SHOES', [(1, [prop_packet(_PROP_TRIANGLE)])])])
    placement = Placement('iGuy', 'guy', 1.0, 2.0, 3.0, 0.0)
    glb = build_glb(level(),
                    libraries=[build_library([section], [first, second])],
                    placements=[placement])
    assert glb is not None
    doc = document(glb)
    mesh = doc['meshes'][next(n for n in doc['nodes'] if n.get('name') == 'iGuy')['mesh']]
    assert len({entry['material'] for entry in mesh['primitives']}) == 2


def test_build_glb_skips_a_placement_whose_prototype_draws_nothing() -> None:
    section = build_section('lib/x', [('a.tga',)], [('thing', [(0, [])])])
    placement = Placement('iEmpty', 'x', 1.0, 2.0, 3.0, 0.0)
    glb = build_glb(level(), libraries=[build_library([section])], placements=[placement])
    assert glb is not None
    assert not any(n.get('name') == 'iEmpty' for n in document(glb)['nodes'])


def test_write_glb_writes_beside_the_source(tmp_path: Path) -> None:
    source = tmp_path / 'mesh.egp2'
    source.write_bytes(level())
    written, = write_glb(source, tmp_path / 'out')
    assert written.name == 'mesh.glb'
    assert written.read_bytes()[:4] == b'glTF'


def test_write_glb_writes_nothing_without_geometry(tmp_path: Path) -> None:
    source = tmp_path / 'mesh.egp2'
    source.write_bytes(build_geometry([], [], {}))
    assert write_glb(source, tmp_path / 'out') == ()
    assert not (tmp_path / 'out').exists()


def test_write_prop_glb_names_the_file_for_props(tmp_path: Path) -> None:
    source = tmp_path / 'cast.sgp2'
    source.write_bytes(_library())
    written, = write_prop_glb(source, tmp_path / 'out')
    assert written.name == 'cast_props.glb'


def test_write_prop_glb_writes_nothing_without_geometry(tmp_path: Path) -> None:
    source = tmp_path / 'cast.sgp2'
    source.write_bytes(build_library([]))
    assert write_prop_glb(source, tmp_path / 'out') == ()
