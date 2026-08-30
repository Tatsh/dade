from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.sopranos.model import (
    TRIANGLE_LIST,
    TRIANGLE_STRIP,
    Material,
    read_materials,
    read_meshes,
    to_mtl,
    to_obj,
    triangles,
    write_model,
)

from .conftest import build_geometry, mesh_packet

if TYPE_CHECKING:
    from pathlib import Path

_TRIANGLE = [(0.0, 0.0, 0.0, 0.25, 0.5), (1.0, 0.0, 0.0, 0.75, 0.5), (0.0, 1.0, 0.0, 0.25, 0.9)]
_QUAD = [*_TRIANGLE, (1.0, 1.0, 0.0, 0.75, 0.9), (2.0, 0.0, 0.0, 0.9, 0.5)]


def _blob() -> bytes:
    return build_geometry([('art/wall.tga', 0x100)], [(7, [mesh_packet(_TRIANGLE)])], {0: 0})


def test_read_materials_reads_names_and_texture_offsets() -> None:
    assert read_materials(_blob()) == (Material('art/wall.tga', 0x100),)


def test_read_materials_stops_at_a_record_past_the_end() -> None:
    data = bytearray(_blob())
    struct.pack_into('<I', data, 0x14, 4)
    assert len(read_materials(bytes(data))) < 4


def test_read_materials_falls_back_when_a_name_is_out_of_range() -> None:
    data = bytearray(_blob())
    struct.pack_into('<I', data, 0x54, 0xFFFFFF)
    assert read_materials(bytes(data))[0].name == 'material_0'


def test_read_meshes_decodes_packets_and_their_material() -> None:
    mesh, = read_meshes(_blob())
    assert mesh.number == 7
    assert mesh.material == 0
    assert [(v.x, v.y, v.z) for v in mesh.packets[0].vertices] == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                                                                   (0.0, 1.0, 0.0)]


def test_read_meshes_reads_more_than_four_vertices() -> None:
    blob = build_geometry([('a.tga', 1)], [(1, [mesh_packet(_QUAD)])], {0: 0})
    mesh, = read_meshes(blob)
    assert len(mesh.packets[0].vertices) == len(_QUAD)


def test_read_meshes_leaves_an_unclaimed_mesh_without_a_material() -> None:
    blob = build_geometry([('a.tga', 1)], [(1, [mesh_packet(_TRIANGLE)])])
    assert read_meshes(blob)[0].material == -1


def test_read_meshes_skips_a_block_past_the_end() -> None:
    # No material claims the mesh, so the table is the only way it could be found.
    data = bytearray(build_geometry([('a.tga', 1)], [(1, [mesh_packet(_TRIANGLE)])]))
    table = struct.unpack_from('<I', data, 0x64)[0]
    struct.pack_into('<I', data, table, 0xFFFFFF)
    assert read_meshes(bytes(data)) == ()


def test_read_meshes_claims_every_mesh_a_material_draws() -> None:
    blob = build_geometry([('a.tga', 1)], [(1, [mesh_packet(_TRIANGLE)]),
                                           (2, [mesh_packet(_TRIANGLE)])], {
                                               0: 0,
                                               1: 0
                                           })
    assert [mesh.material for mesh in read_meshes(blob)] == [0, 0]


def test_read_meshes_warns_when_a_block_does_not_follow_its_data(
        caplog: pytest.LogCaptureFixture) -> None:
    data = bytearray(_blob())
    table = struct.unpack_from('<I', data, 0x64)[0]
    block = struct.unpack_from('<I', data, table)[0]
    struct.pack_into('<I', data, block + 8, 99)
    with caplog.at_level('WARNING'):
        assert read_meshes(bytes(data)) == ()
    assert 'does not follow its own data' in caplog.text


def test_read_meshes_ignores_a_table_slot_holding_zero() -> None:
    data = bytearray(_blob())
    struct.pack_into('<I', data, 0x20, 2)
    # The extra slot reads as zero, which is not an address.
    assert len(read_meshes(bytes(data))) == 1


def test_material_mapping_stops_at_a_record_past_the_end() -> None:
    data = bytearray(_blob())
    struct.pack_into('<I', data, 0x58, len(data) - 8)
    assert read_meshes(bytes(data))[0].material == -1


def test_material_mapping_stops_on_an_impossible_pass() -> None:
    data = bytearray(_blob())
    owners = struct.unpack_from('<I', data, 0x58)[0]
    pointer = struct.unpack_from('<I', data, owners + 8)[0]
    struct.pack_into('<I', data, pointer, 0xFFFF)
    assert read_meshes(bytes(data))[0].material == -1


def test_packets_are_skipped_when_the_body_would_overrun() -> None:
    data = bytearray(_blob())
    table = struct.unpack_from('<I', data, 0x64)[0]
    block = struct.unpack_from('<I', data, table)[0]
    start = struct.unpack_from('<I', data, block + 4)[0]
    # A tag claiming far more vertices than the mesh's data can hold.
    struct.pack_into('<I', data, start + 32, 500 | 0x8000)
    assert read_meshes(bytes(data)) == ()


@pytest.mark.parametrize(('count', 'primitive', 'expected'), [(3, TRIANGLE_LIST, [(0, 1, 2)]),
                                                              (4, TRIANGLE_LIST, [(0, 1, 2)]),
                                                              (4, TRIANGLE_STRIP, [(0, 1, 2),
                                                                                   (1, 3, 2)]),
                                                              (2, TRIANGLE_STRIP, [])])
def test_triangles(*, count: int, expected: list[tuple[int, int, int]], primitive: int) -> None:
    assert list(triangles(count, primitive)) == expected


def test_to_obj_flips_v_and_names_the_library() -> None:
    text = to_obj(read_meshes(_blob()), material_library='thing.mtl')
    assert text.startswith('mtllib thing.mtl')
    assert 'vt 0.250000 0.500000' in text


def test_to_obj_drops_degenerate_triangles() -> None:
    flat = [(0.0, 0.0, 0.0, 0.0, 0.0)] * 3
    blob = build_geometry([('a.tga', 1)], [(1, [mesh_packet(flat, TRIANGLE_STRIP)])])
    assert 'f ' not in to_obj(read_meshes(blob))


def test_to_mtl_maps_a_texture_only_when_there_is_one() -> None:
    text = to_mtl([Material('art/wall.tga', 0x100),
                   Material('art/none.tga', 0)],
                  texture_dir='tex/')
    assert 'map_Kd tex/wall.png' in text
    assert 'map_Kd tex/none.png' not in text


def test_to_mtl_names_an_unnamed_material() -> None:
    assert 'newmtl material_0' in to_mtl([Material('', 0)])


def test_write_model_writes_an_obj_and_mtl(tmp_path: Path) -> None:
    source = tmp_path / 'mesh.egp2'
    source.write_bytes(_blob())
    obj, mtl = write_model(source, tmp_path / 'out')
    assert obj.name == 'mesh.obj'
    assert mtl.read_text().startswith('newmtl wall')


def test_write_model_writes_nothing_without_geometry(tmp_path: Path) -> None:
    source = tmp_path / 'mesh.egp2'
    source.write_bytes(build_geometry([], [], {}))
    assert write_model(source, tmp_path / 'out') == ()
    assert not (tmp_path / 'out').exists()


def test_material_mapping_reads_each_materials_own_run_of_passes() -> None:
    # With two materials the first one's passes end where the second's begin, so the run is read
    # to its true length rather than to a guessed limit.
    blob = build_geometry([('a.tga', 1), ('b.tga', 2)], [(1, [mesh_packet(_TRIANGLE)]),
                                                         (2, [mesh_packet(_TRIANGLE)])], {
                                                             0: 0,
                                                             1: 1
                                                         })
    assert [mesh.material for mesh in read_meshes(blob)] == [0, 1]
