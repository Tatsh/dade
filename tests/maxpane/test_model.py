from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.maxpane.model import InvalidModelError, read_model

if TYPE_CHECKING:
    from collections.abc import Callable


def test_read_model_tagged(make_model: Callable[..., bytes]) -> None:
    model = read_model(make_model())
    assert model.search == ('textures', '../sharedtextures')
    assert model.materials == {'Skin': 'skin.png'}
    mesh = model.meshes[0]
    assert mesh.name == 'body'
    assert len(mesh.positions) == 3
    assert mesh.faces[0].positions == (0, 1, 2)
    assert mesh.materials == ('Skin',)


def test_read_model_packed(make_model: Callable[..., bytes]) -> None:
    # An object writes packed arrays and a flat index buffer; a skin writes tagged, face-indexed
    # ones. Both have to come out the same shape.
    model = read_model(make_model(packed=True))
    mesh = model.meshes[0]
    assert len(mesh.positions) == 3
    assert len(mesh.normals) == 3
    assert mesh.faces[0].positions == (0, 1, 2)


def test_read_model_stands_the_model_up(make_model: Callable[..., bytes]) -> None:
    # Models are Z-up and the game is Y-up, so the exporter's Z becomes the game's Y.
    model = read_model(make_model(positions=((1.0, 2.0, 3.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))))
    assert model.meshes[0].positions[0] == (1.0, -3.0, 2.0)


def test_read_model_keeps_texture_v_as_stored(make_model: Callable[..., bytes]) -> None:
    # The stored triple is (u, v, 0) with v running negative, and it is used as written: negating
    # it puts a face's mouth on its forehead.
    model = read_model(make_model(coords=((0.25, -0.75, 0.0), (0.0, 0.0, 0.0), (1.0, -1.0, 0.0))))
    assert model.meshes[0].coords[0] == pytest.approx((0.25, -0.75))


def test_read_model_reads_the_normals_of_a_packed_mesh(make_model: Callable[..., bytes]) -> None:
    assert read_model(make_model(packed=True)).meshes[0].normals[0] == (0.0, -1.0, 0.0)


def test_read_model_leaves_a_tagged_mesh_without_normals(make_model: Callable[..., bytes]) -> None:
    assert read_model(make_model()).meshes[0].normals == ()


def test_read_model_uses_the_per_face_material(make_model: Callable[..., bytes]) -> None:
    model = read_model(
        make_model(faces=((0, 1, 2), (2, 1, 0)),
                   coord_faces=((0, 1, 2), (2, 1, 0)),
                   materials=(('Skin', 'skin.png'), ('Cloth', 'cloth.png')),
                   face_materials=(1, 0)))
    assert [f.material for f in model.meshes[0].faces] == [1, 0]


def test_read_model_falls_back_to_the_first_material(make_model: Callable[..., bytes]) -> None:
    # A mesh that names its materials but not a per-face list draws entirely with the first.
    model = read_model(make_model(face_materials=()))
    assert model.meshes[0].faces[0].material == 0


def test_read_model_ignores_a_material_index_past_the_end(make_model: Callable[..., bytes]) -> None:
    model = read_model(make_model(face_materials=(7,)))
    assert model.meshes[0].faces[0].material == 0


def test_read_model_drops_a_face_indexing_a_missing_position(
        make_model: Callable[..., bytes]) -> None:
    model = read_model(make_model(faces=((0, 1, 9),), coord_faces=((0, 1, 2),)))
    assert model.meshes[0].faces == ()


def test_read_model_drops_a_face_that_is_not_a_triangle(make_model: Callable[..., bytes]) -> None:
    model = read_model(make_model(faces=((0, 1),), coord_faces=((0, 1),)))
    assert model.meshes[0].faces == ()


def test_read_model_falls_back_when_a_coordinate_index_is_missing(
        make_model: Callable[..., bytes]) -> None:
    model = read_model(make_model(coord_faces=((0, 1, 9),)))
    assert model.meshes[0].faces[0].coords == (0, 0, 0)


def test_read_model_rejects_a_file_that_is_not_chunked() -> None:
    with pytest.raises(InvalidModelError, match='Not a chunked model'):
        read_model(b'\x14\x02')


def test_read_model_rejects_an_empty_file() -> None:
    with pytest.raises(InvalidModelError, match='Not a chunked model'):
        read_model(b'')


def test_read_model_rejects_a_chunk_running_past_the_end(make_model: Callable[..., bytes]) -> None:
    data = bytearray(make_model())
    struct.pack_into('<I', data, 9, len(data) * 4)
    with pytest.raises(InvalidModelError, match='claims'):
        read_model(bytes(data))


def test_read_model_rejects_an_implausible_count() -> None:
    positions = b'\x0c' + struct.pack('<3I', 0x00010006, 0, 18) + b'\x02' + struct.pack('<i', -1)
    mesh = b'\x0c' + struct.pack('<3I', 0x00010005, 1, 13 + len(positions)) + positions
    with pytest.raises(InvalidModelError, match='Implausible element count'):
        read_model(mesh)


def test_read_model_without_a_texture_chunk(make_model: Callable[..., bytes]) -> None:
    # A material naming no image still has to appear, so the face it draws falls back to a colour.
    data = make_model()
    assert read_model(data.replace(b'Map #0', b'Map #1')).materials == {'Skin': 'skin.png'}


def _chunk(identifier: int, version: int, body: bytes) -> bytes:
    return b'\x0c' + struct.pack('<3I', identifier, version, len(body) + 13) + body


def test_read_model_rejects_a_vector_that_is_not_one() -> None:
    positions = b'\x14\x01' + b'\x14\x00'
    mesh = _chunk(0x00010005, 1, _chunk(0x00010006, 0, positions))
    with pytest.raises(InvalidModelError, match='Expected a vector'):
        read_model(mesh)


def test_read_model_stops_reading_faces_at_a_foreign_chunk() -> None:
    faces = b'\x14\x02' + _chunk(0x00010008, 0, b'\x14\x03\x14\x00\x14\x00\x14\x00')
    faces += _chunk(0x00010000, 0, b'')
    mesh = _chunk(0x00010005, 1, _chunk(0x00010007, 0, faces))
    assert read_model(mesh).meshes[0].faces == ()


def test_read_model_ignores_a_library_chunk_that_is_not_a_material() -> None:
    library = b'\x0d\x14\x00' + b'\x14\x01' + _chunk(0x00010000, 0, b'')
    assert read_model(_chunk(0x0001000F, 0, library)).materials == {}


def test_read_model_ignores_a_material_chunk_that_is_not_a_texture() -> None:
    material = b'\x0d\x14\x04Coat' + _chunk(0x00010000, 0, b'') + _chunk(
        0x00010011, 1, b'\x0d\x14\x00\x14\x00\x14\x00\x14\x01\x0d\x14\x05a.png')
    library = b'\x0d\x14\x00\x14\x01' + _chunk(0x00010010, 1, material)
    assert read_model(_chunk(0x0001000F, 0, library)).materials == {'Coat': 'a.png'}


def test_read_model_reads_a_material_naming_no_file() -> None:
    texture = b'\x0d\x14\x00\x14\x00\x14\x00\x14\x00'
    material = b'\x0d\x14\x04Coat' + _chunk(0x00010011, 1, texture)
    library = b'\x0d\x14\x00\x14\x01' + _chunk(0x00010010, 1, material)
    assert read_model(_chunk(0x0001000F, 0, library)).materials == {'Coat': ''}


def test_read_model_steps_over_a_string_before_a_texture_chunk() -> None:
    texture = b'\x0d\x14\x00\x14\x00\x14\x00\x14\x01\x0d\x14\x05a.png'
    material = b'\x0d\x14\x04Coat\x0d\x14\x04note' + _chunk(0x00010011, 1, texture)
    library = b'\x0d\x14\x00\x14\x01' + _chunk(0x00010010, 1, material)
    assert read_model(_chunk(0x0001000F, 0, library)).materials == {'Coat': 'a.png'}


def test_read_model_gives_up_on_an_unknown_tag_before_a_texture_chunk() -> None:
    material = b'\x0d\x14\x04Coat\x7f'
    library = b'\x0d\x14\x00\x14\x01' + _chunk(0x00010010, 1, material)
    assert read_model(_chunk(0x0001000F, 0, library)).materials == {'Coat': ''}


def test_read_model_ignores_a_chunk_it_does_not_know(make_model: Callable[..., bytes]) -> None:
    assert read_model(make_model() + _chunk(0x00010012, 5, b'\x14\x00')).meshes


def test_read_model_ignores_a_mesh_chunk_it_does_not_know() -> None:
    mesh = _chunk(0x00010000, 1, b'\x0d\x14\x04legs\x0d\x14\x00')
    mesh += _chunk(0x0001000B, 0, b'\x14\x00')
    assert read_model(_chunk(0x00010005, 1, mesh)).meshes[0].name == 'legs'


def test_read_model_rejects_a_chunk_header_cut_short(make_model: Callable[..., bytes]) -> None:
    # Enough of a header to say `chunk` and not enough to say how long, which used to raise
    # `struct.error` past the reader's own error type.
    with pytest.raises(InvalidModelError, match='runs past the end'):
        read_model(make_model()[:5])


def test_read_model_drops_a_face_indexing_backwards(make_model: Callable[..., bytes]) -> None:
    # A negative index is in range for Python and would quietly pick a vertex off the far end.
    model = read_model(make_model(faces=((0, 1, -1),)))
    assert model.meshes[0].faces == ()


def test_read_model_ignores_a_negative_texture_coordinate_index(
        make_model: Callable[..., bytes]) -> None:
    model = read_model(make_model(coord_faces=((0, 1, -2),)))
    assert model.meshes[0].faces[0].coords == (0, 0, 0)
