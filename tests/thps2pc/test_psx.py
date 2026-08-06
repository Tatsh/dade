"""Tests for :mod:`destin.thps2pc.psx`."""
from __future__ import annotations

from destin.thps2pc.psx import Scene
from destin.thps2pc.test_utils import SectorSpec, face_record, psx_scene
import pytest


def test_parse_reads_header(scene: Scene) -> None:
    assert scene.version == 0x00020004
    assert len(scene.sectors) == 2
    assert len(scene.descriptors) == 2


def test_parse_rejects_short_input() -> None:
    with pytest.raises(ValueError, match=r'too small'):
        Scene.parse(b'\x00\x00\x00')


def test_sector_counts(scene: Scene) -> None:
    sector = scene.sectors[0]
    assert (sector.count_a, sector.count_b, sector.vertex_count) == (3, 1, 4)
    assert sector.num_faces == 2
    assert sector.faces_end > sector.faces_offset


def test_vertices_are_local_by_default(scene: Scene) -> None:
    assert scene.vertices(scene.sectors[0])[1] == (100, 0, 0)


def test_vertices_apply_an_origin(scene: Scene) -> None:
    assert scene.vertices(scene.sectors[0], (5, 6, 7))[0] == (5, 6, 7)


def test_placement_maps_sequence_to_position(scene: Scene) -> None:
    assert scene.placement() == {0: (0, 0, 0), 1: (500, 0, 500)}


def test_chunks_end_with_the_terminator(scene: Scene) -> None:
    chunks = list(scene.chunks())
    assert chunks[0].id == 0x52454948
    assert chunks[-1].id == -1


def test_texture_checksums(scene: Scene) -> None:
    assert scene.texture_checksums() == (0xDEADBEEF, 0xCAFEF00D)


def test_faces_decode_uvs_and_texture_index(scene: Scene) -> None:
    first, second = list(scene.faces(scene.sectors[0]))
    assert first.corners == (0, 1, 2)
    assert first.uvs == ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    assert first.texture_index == 0
    assert second.corners == (0, 1, 2, 3)
    assert second.texture_index == 1


def test_face_layer_properties(scene: Scene) -> None:
    face = next(iter(scene.faces(scene.sectors[0])))
    assert face.is_textured
    assert face.layer == 0x00
    assert not face.is_hidden


def test_hidden_face_is_detected() -> None:
    record = face_record((0, 1, 2), flags=0x11 | 0x80)
    parsed = Scene.parse(
        psx_scene(sectors=(SectorSpec(vertices=((0, 0, 0),) * 3, faces=(record,), count_b=0),)))
    face = next(iter(parsed.faces(parsed.sectors[0])))
    assert face.is_hidden
    assert face.layer == 0x80


def test_untextured_face_has_no_uvs() -> None:
    record = face_record((0, 1, 2), flags=0x10)
    parsed = Scene.parse(
        psx_scene(sectors=(SectorSpec(vertices=((0, 0, 0),) * 3, faces=(record,), count_b=0),)))
    face = next(iter(parsed.faces(parsed.sectors[0])))
    assert not face.is_textured
    assert face.uvs == ()
    assert face.texture_index == -1


@pytest.mark.parametrize(('flags', 'length', 'by_flag', 'by_length'), [(0x01, 7, 4, 3),
                                                                       (0x11, 8, 3, 4),
                                                                       (0x11, 7, 3, 3),
                                                                       (0x01, 8, 4, 4)])
def test_corner_source_readings_can_disagree(flags: int, length: int, by_flag: int,
                                             by_length: int) -> None:
    record = face_record((0, 1, 2, 3)[:4], flags=flags, length=length)
    parsed = Scene.parse(
        psx_scene(sectors=(SectorSpec(vertices=((0, 0, 0),) * 4, faces=(record,), count_b=0),)))
    sector = parsed.sectors[0]
    assert len(next(iter(parsed.faces(sector))).corners) == by_flag
    assert len(next(iter(parsed.faces(sector, corner_source='length'))).corners) == by_length


def test_faces_stop_at_a_zero_length_record() -> None:
    record = face_record((0, 1, 2), flags=0x11) + bytes(8)
    spec = SectorSpec(vertices=((0, 0, 0),) * 3, faces=(record,), count_b=0)
    parsed = Scene.parse(psx_scene(sectors=(spec,)))
    assert len(list(parsed.faces(parsed.sectors[0]))) == 1


def test_faces_reject_an_unknown_corner_source(scene: Scene) -> None:
    with pytest.raises(ValueError, match=r'Unknown corner source'):
        list(scene.faces(scene.sectors[0], corner_source='guess'))


def test_triangles_reject_an_unknown_triangulation(scene: Scene) -> None:
    with pytest.raises(ValueError, match=r'Unknown triangulation'):
        list(scene.triangles(scene.sectors[0], triangulation='spiral'))


@pytest.mark.parametrize(('triangulation', 'expected'), [('strip', (1, 3, 2)), ('fan', (0, 2, 3))])
def test_quad_triangulation_slots(scene: Scene, triangulation: str, expected: tuple[int, int,
                                                                                    int]) -> None:
    slots = [
        slot for face, slot in scene.triangles(scene.sectors[0], triangulation=triangulation)
        if len(face.corners) == 4
    ]
    assert slots == [(0, 1, 2), expected]


def test_triangle_faces_emit_a_single_triangle(scene: Scene) -> None:
    emitted = [slot for face, slot in scene.triangles(scene.sectors[0]) if len(face.corners) == 3]
    assert emitted == [(0, 1, 2)]


def test_sectors_with_a_zero_offset_are_skipped() -> None:
    data = bytearray(psx_scene(sectors=(SectorSpec(vertices=((0, 0, 0),), faces=(), count_b=0),)))
    data[0x10:0x14] = b'\x00\x00\x00\x00'
    assert Scene.parse(bytes(data)).sectors == ()
