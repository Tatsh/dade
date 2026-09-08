"""Tests for :mod:`dade.xg2.f3dex2`."""
from __future__ import annotations

import struct

from dade.xg2.f3dex2 import (
    MAX_VERTICES,
    Vertex,
    VertexBuffer,
    demo,
    parse_display_lists,
    parse_pc_display_lists,
    texcoords,
)


def _vertices(points: list[tuple[int, int]]) -> bytes:
    return b''.join(
        struct.pack('>3hH2h4B', x, y, 0, 0, x * 32 * 32, y * 32 * 32, x, y, 0, 255)
        for x, y in points)


def _flat_model() -> bytes:
    """Build a flat N64 model exercising every geometry opcode the walker handles."""
    header = struct.pack('>2I', 0x05000008, 0)
    commands = (
        (0xD9FDFFFF, 0),  # G_GEOMETRYMODE clearing G_LIGHTING, so the triangles come out unlit.
        (0x01004008, 0),  # G_VTX for four vertices; the source is patched in below.
        (0xFD100000, 0x05000200),  # G_SETTIMG naming the palette.
        (0xF0000000, 0),  # G_LOADTLUT, which drops that as the surface.
        (0xFD100000, 0x05000400),  # G_SETTIMG naming the pixels.
        (0xF5000000, 0),  # G_SETTILE, binding them.
        (0x05000204, 0),  # G_TRI1 over corners 0, 1, 2.
        (0x07040600, 0x00000204),  # G_QUAD over (2, 3, 0) and (0, 1, 2).
        (0xDE000000, 0),  # G_DL calling the sub-list; its target is patched in below.
        (0xDF000000, 0),  # G_ENDDL.
    )
    vertex_at = len(header) + len(commands) * 8
    vertices = _vertices([(0, 0), (1, 0), (1, 1), (0, 1)])
    sub_at = vertex_at + len(vertices)
    patched = list(commands)
    patched[1] = (0x01004008, 0x05000000 | vertex_at)
    patched[8] = (0xDE000000, 0x05000000 | sub_at)
    body = b''.join(struct.pack('>2I', w0, w1) for w0, w1 in patched)
    sub = struct.pack('>2I', 0xDF000000, 0)
    return header + body + vertices + sub


def _pc_model() -> tuple[bytes, bytes]:
    """Build a Windows model and the vertex bank segment 8 points it at."""
    table = struct.pack('<I', 0x05000004)
    commands = (
        (0xAC000000, 0),  # A texture descriptor, whose next word names the pixels.
        (0, 0x05000400),  # Consumed as that descriptor's pixel offset.
        (0x04000C00, 0),  # G_VTX loading three vertices from bank offset zero.
        (0x05000204, 0),  # G_TRI1 over corners 0, 1, 2.
        (0xDF000000, 0),  # G_ENDDL.
    )
    body = b''.join(struct.pack('<2I', w0, w1) for w0, w1 in commands)
    vertices = b''.join(
        struct.pack('<3hH2h4B', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
        for x, y in ((0, 0), (1, 0), (0, 1)))
    return table + body, vertices


def test_demo_holds() -> None:
    demo()


def test_parse_display_lists_walks_every_opcode() -> None:
    meshes = parse_display_lists(_flat_model())
    assert len(meshes) == 1
    mesh = meshes[0]
    assert mesh.texture == 0x400
    assert not mesh.lit
    assert len(mesh.triangles) == 3


def test_parse_display_lists_of_a_non_model() -> None:
    assert parse_display_lists(b'\x00' * 32) == []


def test_parse_pc_display_lists_reads_the_bank() -> None:
    model, vertices = _pc_model()
    meshes = parse_pc_display_lists(model, vertices)
    assert len(meshes) == 1
    assert meshes[0].texture == 0x400
    assert len(meshes[0].triangles) == 1


def test_vertex_buffer_drops_a_triangle_over_empty_slots() -> None:
    buffer = VertexBuffer()
    buffer.triangle(0, (0, 1, 2))
    assert buffer.meshes() == []


def test_vertex_buffer_folds_the_primitive_tint_into_the_colours() -> None:
    buffer = VertexBuffer()
    buffer.load(_vertices([(1, 0), (0, 1), (1, 1)]), 0, 3, 0, '>')
    buffer.triangle(0x40, (0, 1, 2), lit=False, tint=(0xFF, 0x80, 0x00))
    mesh = buffer.meshes()[0]
    assert mesh.vertices[0].alpha == 0xFF
    assert mesh.vertices[0].green == 0


def test_vertex_buffer_drops_a_degenerate_triangle() -> None:
    buffer = VertexBuffer()
    buffer.load(_vertices([(1, 0), (0, 1), (1, 1)]), 0, 3, 0, '>')
    buffer.triangle(0, (0, 0, 1))
    assert buffer.meshes() == []


def test_vertex_buffer_ignores_an_out_of_range_slot() -> None:
    buffer = VertexBuffer()
    buffer.load(_vertices([(1, 0)]), 0, 1, MAX_VERTICES, '>')
    assert buffer.slots[0] is None


def test_texcoords_normalise_to_the_image_size() -> None:
    assert texcoords(Vertex(0, 0, 0, 32 * 32, 0, 0, 0, 0, 0), 32, 32) == (1.0, 0.0)
