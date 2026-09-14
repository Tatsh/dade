"""Tests for :mod:`dade.xg2.f3dex2`."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import runpy
import struct

import pytest

from dade.common.exceptions import SelfCheckFailed
from dade.xg2 import f3dex2
from dade.xg2.f3dex2 import (
    MAX_VERTICES,
    Mesh,
    Vertex,
    VertexBuffer,
    demo,
    parse_display_lists,
    parse_pc_display_lists,
    texcoords,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_MODULE_PATH = str(Path(f3dex2.__file__))
_DEMO_VERTS = [
    Vertex(0, 0, 0, 0, 0, 0, 0, 0, 255),
    Vertex(1, 0, 0, 1024, 0, 0, 0, 0, 255),
    Vertex(1, 1, 0, 1024, 1024, 0, 0, 0, 255),
    Vertex(0, 1, 0, 0, 1024, 0, 0, 0, 255),
]
_DEMO_MESH = Mesh(0xFF0, lit=False, vertices=_DEMO_VERTS, triangles=[(0, 1, 2), (2, 3, 0)])


def _vertices(points: list[tuple[int, int]]) -> bytes:
    return b''.join(
        struct.pack('>3hH2h4B', x, y, 0, 0, x * 32 * 32, y * 32 * 32, x, y, 0, 255)
        for x, y in points)


def _flat_model() -> bytes:
    """Build a flat N64 model exercising every geometry opcode the walker handles."""
    header = struct.pack('>2I', 0x05000008, 0)
    commands = (
        (0xD9FDFFFF, 0),  # G_GEOMETRYMODE clearing G_LIGHTING; the triangles come out unlit.
        (0x01004008, 0),  # G_VTX for four vertices; the source is patched in below.
        (0xFD100000, 0x05000200),  # G_SETTIMG naming the palette.
        (0xF0000000, 0),  # G_LOADTLUT. It drops that as the surface.
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
        (0xAC000000, 0),  # A texture descriptor, whose next word specifies the pixels.
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


def test_module_entry_point_runs(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(_MODULE_PATH, run_name='__main__')
    assert 'command decoding verified' in capsys.readouterr().out


@pytest.mark.parametrize(('meshes', 'match'), [
    ([[], []], 'expected one'),
    ([[Mesh(0x123, lit=False, vertices=_DEMO_VERTS, triangles=[(0, 1, 2),
                                                               (2, 3, 0)])], []], 'expected 0xff0'),
    ([[Mesh(0xFF0, lit=False, vertices=_DEMO_VERTS, triangles=[(0, 1, 2)])], []], 'expected 2'),
    ([[Mesh(0xFF0, lit=False, vertices=_DEMO_VERTS[:3], triangles=[(0, 1, 2),
                                                                   (2, 3, 0)])], []], 'expected 4'),
    ([[
        Mesh(0xFF0,
             lit=False,
             vertices=[Vertex(0, 0, 0, 0, 0, 0, 0, 0, 255)] * 4,
             triangles=[(0, 1, 2), (2, 3, 0)])
    ], []], r'expected \(1.0, 0.0\)'), ([[_DEMO_MESH], [_DEMO_MESH]], 'branch past the end')
])
def test_demo_reports_a_wrong_decode(mocker: MockerFixture, meshes: list[list[Mesh]],
                                     match: str) -> None:
    mocker.patch('dade.xg2.f3dex2.parse_display_lists', side_effect=meshes)
    with pytest.raises(SelfCheckFailed, match=match):
        demo()


def test_display_list_calling_itself_stops_at_max_depth() -> None:
    # A call that targets its address pushes a return frame every pass; the walker must cap the
    # stack rather than recurse without bound.
    model = struct.pack('>2I', 0x05000008, 0) + struct.pack('>2I', 0xDE000000, 0x05000008)
    assert parse_display_lists(model) == []


def test_display_list_branch_runs_off_the_end() -> None:
    # A branch (the no-push bit set) hands control on without a return frame, and the target runs to
    # the end of the data without an end marker.
    model = (struct.pack('>2I', 0x05000008, 0) + struct.pack('>2I', 0xDE010000, 0x05000010) +
             struct.pack('>2I', 0, 0))
    assert parse_display_lists(model) == []


def test_vertex_load_without_a_segment_and_a_tile_without_an_image() -> None:
    model = (struct.pack('>2I', 0x05000008, 0) + struct.pack('>2I', 0x01004008, 0) +
             struct.pack('>2I', 0xF5000000, 0) + struct.pack('>2I', 0xDF000000, 0))
    assert parse_display_lists(model) == []


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


def test_entry_table_stops_at_a_foreign_word() -> None:
    # A word in the pointer table that is not a segment-5 address ends the table.
    model = struct.pack('>2I', 0x05000008, 0x40000000) + struct.pack('>2I', 0xDF000000, 0)
    assert parse_display_lists(model) == []


def test_parse_pc_display_lists_reads_a_triangle_pair() -> None:
    table = struct.pack('<I', 0x05000004)
    commands = (
        (0xAC000000, 0),  # A texture descriptor naming the pixels next.
        (0, 0x05000400),  # Its pixel offset.
        (0x04000C00, 0),  # G_VTX loading three vertices.
        (0x03000000, 0),  # G_CULLDL, a valid opcode the geometry walker does not act on.
        (0xB1000204, 0x00000204),  # G_TRI2 drawing two triangles over corners 0, 1, 2.
        (0xDF000000, 0),  # G_ENDDL.
    )
    body = b''.join(struct.pack('<2I', w0, w1) for w0, w1 in commands)
    vertices = b''.join(
        struct.pack('<3hH2h4B', x, y, 0, 0, 0, 0, 255, 255, 255, 255)
        for x, y in ((0, 0), (1, 0), (0, 1)))
    meshes = parse_pc_display_lists(table + body, vertices)
    assert len(meshes) == 1
    assert len(meshes[0].triangles) == 2


def test_parse_pc_display_lists_skips_a_short_entry() -> None:
    # The pointer leads too close to the end for even two commands; it is not walked.
    model = struct.pack('<I', 0x05000004) + struct.pack('<I', 0)
    assert parse_pc_display_lists(model, b'') == []


def test_parse_pc_display_lists_skips_a_data_entry() -> None:
    # The region begins with a word whose top byte is not a known opcode; it is data, not code.
    model = struct.pack('<I', 0x05000004) + struct.pack('<4I', 0, 0, 0, 0)
    assert parse_pc_display_lists(model, b'') == []


def test_parse_pc_display_lists_probe_reaches_the_end() -> None:
    # A run of valid opcodes with no end marker: the probe breaks when it runs off the data, and
    # again when the walker does.
    table = struct.pack('<I', 0x05000004)
    body = struct.pack('<2I', 0x04000000, 0) * 3
    assert parse_pc_display_lists(table + body, b'\x00' * 64) == []


def test_parse_pc_display_lists_probe_scans_the_whole_window() -> None:
    # More valid opcodes than the probe examines; it settles without ever seeing an end marker.
    table = struct.pack('<I', 0x05000004)
    body = struct.pack('<2I', 0x04000000, 0) * 30
    assert parse_pc_display_lists(table + body, b'\x00' * 64) == []


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
