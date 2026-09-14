"""
Geometry extraction from F3DEX2 display lists.

The Extreme-G XG2 builds, on both the N64 and the PC, store a model as a table of segment-5 display
list pointers followed by the command stream those point into. The microcode is F3DEX2, and the
data shows it plainly. The end marker is ``G_ENDDL`` (``0xDF``) rather than F3D's ``0xB8``, vertices
load with ``0x01`` rather than ``0x04``, and a ``G_TRI2`` such as ``06000204 00040600`` decodes as
the triangles ``(0, 1, 2)`` and ``(2, 3, 0)``, a quad split the obvious way that a wrong microcode
guess would not produce.

Only the commands that affect geometry are interpreted. Everything about how a surface is shaded
beyond which image it samples (the combiner, the blender, fog, and lighting) is skipped. None of it
survives the trip into glTF. A primitive is grouped by the pixel address its ``G_SETTIMG``
specified. That is the same key :py:func:`dade.xg2.models.collect_textures` reports a decoded
texture under, and geometry and images therefore meet without either side having to know about the
other.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct

from dade.common.exceptions import SelfCheckFailed, UnreachableState

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .typing import Endian

__all__ = ('MAX_VERTICES', 'Mesh', 'Vertex', 'VertexBuffer', 'parse_display_lists',
           'parse_pc_display_lists')

MAX_VERTICES = 32
"""Slots in the F3DEX2 vertex buffer.

:meta hide-value:
"""

_G_VTX = 0x01
_G_MODIFYVTX = 0x02
_G_CULLDL = 0x03
_G_BRANCH_Z = 0x04
_G_TRI1 = 0x05
_G_TRI2 = 0x06
_G_QUAD = 0x07
_G_TEXTURE = 0xD7
_G_GEOMETRYMODE = 0xD9
_G_LIGHTING = 0x00020000
_G_DL = 0xDE
_G_ENDDL = 0xDF
_G_SETTIMG = 0xFD
_G_SETTILE = 0xF5
_G_LOADTLUT = 0xF0
_PC_G_VTX = 0x04
_PC_G_TRI2 = 0xB1
_PC_TEXTURE = 0xAC
_SEGMENT_5 = 0x05
_VERTEX_SIZE = 16
_COMMAND_SIZE = 8
_TEXCOORD_SHIFT = 32.0
_UNIT_SCALE = 0x10000
_NO_PUSH = 0x01
_MAX_COMMANDS = 1 << 17
_MAX_DEPTH = 16
_F3D_ENDDL = 0xB8
_PC_PROBE_COMMANDS = 24
_PC_OPCODES = frozenset({
    0x03,
    0x04,
    0x05,
    0x06,
    0xAC,
    0xB1,
    0xB6,
    0xB7,
    0xB8,
    0xB9,
    0xBA,
    0xBB,
    0xBC,
    0xBD,
    0xBE,
    0xBF,
    0xE2,
    0xE3,
    0xE6,
    0xE7,
    0xE8,
    0xF0,
    0xF2,
    0xF3,
    0xF4,
    0xF5,
    0xFA,
    0xFB,
    0xFC,
    0xFD,
    0xDF,
})
_DEMO_COUNT = 15
_DEMO_TEXTURE = 0xFF0
_DEMO_TRIANGLES = 2
_DEMO_VERTICES = 4


class Vertex(NamedTuple):
    """One entry of the F3DEX2 vertex buffer, as the microcode stores it."""

    x: int
    """Model-space X in whole units."""
    y: int
    """Model-space Y in whole units."""
    z: int
    """Model-space Z in whole units."""
    s: int
    """Texture S in ``10.5`` fixed point."""
    t: int
    """Texture T in ``10.5`` fixed point."""
    red: int
    """Red, or the packed normal's X when the display list lights the model."""
    green: int
    """Green, or the packed normal's Y."""
    blue: int
    """Blue, or the packed normal's Z."""
    alpha: int
    """Alpha."""


class Mesh(NamedTuple):
    """Every triangle a model draws with one image, under one lighting setting."""

    texture: int | None
    """Pixel offset of the image, matching :py:attr:`dade.xg2.typing.Texture.offset`, or
    :py:obj:`None` for triangles drawn before any image was set."""
    lit: bool
    """Whether ``G_LIGHTING`` was on, deciding what the vertices' four colour bytes store, a packed
    normal when it is and a vertex colour when it is not."""
    vertices: list[Vertex]
    """The vertices the triangles index."""
    triangles: list[tuple[int, int, int]]
    """Corner indices into :py:attr:`vertices`."""


class VertexBuffer:
    """
    The microcode's 32-slot vertex buffer, plus the flattened output built as triangles arrive.

    A display list reloads slots constantly, and a slot index therefore means nothing outside the
    moment it is referenced. Every corner is copied into a per-image output list as its triangle is
    read, and identical corners are folded together so the result is indexed rather than a soup of
    loose triangles.
    """
    def __init__(self) -> None:
        self.slots: list[Vertex | None] = [None] * MAX_VERTICES
        """The 32 vertex slots the microcode indexes, cleared to empty."""
        self._meshes: dict[tuple[int | None, bool], tuple[list[Vertex], dict[Vertex, int],
                                                          list[tuple[int, int, int]]]] = {}

    def load(self, data: bytes, offset: int, count: int, first: int, endian: Endian) -> None:
        """
        Read *count* vertices into the buffer starting at slot *first*.

        Parameters
        ----------
        data : bytes
            The model blob.
        offset : int
            Offset of the vertex array within it.
        count : int
            How many vertices to load.
        first : int
            First slot to fill.
        endian : dade.xg2.typing.Endian
            Byte order of the blob.
        """
        for i in range(count):
            slot = first + i
            at = offset + i * _VERTEX_SIZE
            if not 0 <= slot < MAX_VERTICES or at + _VERTEX_SIZE > len(data):
                continue
            x, y, z, _flag, s, t = struct.unpack_from(f'{endian}3hH2h', data, at)
            red, green, blue, alpha = data[at + 12:at + 16]
            self.slots[slot] = Vertex(x, y, z, s, t, red, green, blue, alpha)

    def triangle(self,
                 texture: int | None,
                 corners: tuple[int, int, int],
                 *,
                 lit: bool = True,
                 tint: tuple[int, int, int] | None = None) -> None:
        """
        Record one triangle drawn with the current image.

        A corner referencing an empty slot means the display list drew before loading. That is a
        mis-parse rather than a behaviour of the game, and the triangle is dropped.

        Parameters
        ----------
        texture : int | None
            Pixel offset of the current image.
        corners : tuple[int, int, int]
            Slot indices of the three corners.
        lit : bool
            Whether ``G_LIGHTING`` was on when the triangle was drawn.
        tint : tuple[int, int, int] | None
            Primitive colour to fold into the vertex colours, for a combiner that multiplies the
            primitive colour by the shade rather than sampling a texture. The product is stored on
            the vertices, letting the result need no separate material, and alpha goes opaque
            because that combiner forces it to one.

        Raises
        ------
        UnreachableState
            If a corner is still empty after the empty ones have been filtered out.
        """
        picked = [self.slots[i] if 0 <= i < MAX_VERTICES else None for i in corners]
        if any(v is None for v in picked):
            return
        if tint is not None:
            picked = [
                v._replace(red=v.red * tint[0] // 0xFF,
                           green=v.green * tint[1] // 0xFF,
                           blue=v.blue * tint[2] // 0xFF,
                           alpha=0xFF) if v is not None else None for v in picked
            ]
        vertices, seen, triangles = self._meshes.setdefault((texture, lit), ([], {}, []))
        indices = []
        for vertex in picked:
            if vertex is None:  # pragma: no cover
                msg = 'A picked corner is empty, but every empty slot was filtered out above.'
                raise UnreachableState(msg)
            found = seen.get(vertex)
            if found is None:
                found = seen[vertex] = len(vertices)
                vertices.append(vertex)
            indices.append(found)
        # A triangle with a repeated corner has no area. The microcode is fed these deliberately to
        # stitch strips together, and glTF has no use for them.
        if len(set(indices)) == len(indices):
            triangles.append((indices[0], indices[1], indices[2]))

    def meshes(self) -> list[Mesh]:
        """
        Return one mesh per image drawn with, in the order each was first used.

        Returns
        -------
        list[Mesh]
            The meshes, skipping any that ended up with no triangles.
        """
        return [
            Mesh(texture, lit, vertices, triangles)
            for (texture, lit), (vertices, _seen, triangles) in self._meshes.items() if triangles
        ]


def _entry_points(data: bytes, endian: Endian) -> list[int]:
    """
    Read the table of display list pointers a flat model begins with.

    The table is not counted, and its entries are in no particular order. The PC models list theirs
    starting at ``0x6BA4`` when the smallest is ``0x20``. The *lowest* address it points at bounds
    the table, the command stream beginning immediately after it. Reading the first entry as the end
    works on most N64 models by luck and truncates the rest.

    A zero word is a hole in the table rather than the end of it, and it is stepped over.

    Parameters
    ----------
    data : bytes
        The model blob.
    endian : dade.xg2.typing.Endian
        Byte order of the blob.

    Returns
    -------
    list[int]
        Offsets of each display list, in table order.
    """
    out: list[int] = []
    end = len(data)
    offset = 0
    while offset + 4 <= end:
        word = struct.unpack_from(f'{endian}I', data, offset)[0]
        offset += 4
        if word == 0:
            continue
        target = word & 0xFFFFFF
        if (word >> 24) != _SEGMENT_5 or not 0 < target < len(data):
            break
        out.append(target)
        end = min(end, target)
    return out


def _commands(data: bytes, start: int, endian: Endian) -> Iterator[tuple[int, int, int]]:
    """
    Walk a display list, following calls and stopping at its end.

    Parameters
    ----------
    data : bytes
        The model blob.
    start : int
        Offset of the display list.
    endian : dade.xg2.typing.Endian
        Byte order of the blob.

    Yields
    ------
    tuple[int, int, int]
        The opcode and the two command words.
    """
    stack = [start]
    budget = _MAX_COMMANDS
    while stack:
        at = stack.pop()
        while at + _COMMAND_SIZE <= len(data) and budget > 0:
            budget -= 1
            w0, w1 = struct.unpack_from(f'{endian}2I', data, at)
            op = w0 >> 24
            at += _COMMAND_SIZE
            if op in {_G_ENDDL, _F3D_ENDDL}:
                break
            if op == _G_DL:
                target = w1 & 0xFFFFFF
                if (w1 >> 24) != _SEGMENT_5 or not 0 < target < len(data):
                    break
                # The low bit of the parameter byte distinguishes a call, returning here, from a
                # branch, returning nowhere.
                if not (w0 >> 16) & _NO_PUSH:
                    if len(stack) >= _MAX_DEPTH:
                        break
                    stack.append(at)
                at = target
                continue
            yield op, w0, w1


def _is_pc_display_list(data: bytes, start: int) -> bool:
    """
    Report whether a table entry leads to a display list rather than to data.

    A PC model's table mixes the two. Of one bike's eight entries, one leads to the command stream
    and the rest to vertices, coordinates, and images. Walking a data region as commands does not
    fail; it invents them, one bike appearing to want a 15 MB vertex bank when the file is 32 KB. An
    entry is therefore only walked once it looks like code.

    Parameters
    ----------
    data : bytes
        The model blob.
    start : int
        Offset the table entry leads to.

    Returns
    -------
    bool
        Whether the entry begins a display list.
    """
    if start + _COMMAND_SIZE * 2 > len(data):
        return False
    seen = set()
    skip = False
    for i in range(_PC_PROBE_COMMANDS):
        at = start + i * _COMMAND_SIZE
        if at + _COMMAND_SIZE > len(data):
            break
        op = data[at + 3]
        if skip:
            # The word after the texture marker's palette stores dimensions, whose top byte is not
            # an opcode at all.
            skip = False
            continue
        if op in {_F3D_ENDDL, _G_ENDDL}:
            break
        if op not in _PC_OPCODES:
            return False
        skip = op == _PC_TEXTURE
        seen.add(op)
    # A display list that never loads a vertex or draws a triangle is not one worth walking.
    return bool(seen & {_PC_G_VTX, _PC_G_TRI2, _G_TRI1})


def parse_pc_display_lists(data: bytes, vertices: bytes) -> list[Mesh]:
    """
    Decode every triangle a PC model draws.

    The Windows port retained the console's display lists but swapped three details. Vertices load
    with F3DEX's ``0x04`` rather than F3DEX2's ``0x01``, triangle pairs come as ``0xB1`` rather than
    ``0x06``, and the whole texture-setup sequence collapses into the four-word ``0xAC`` descriptor
    that :py:func:`dade.xg2.displaylist.parse_pc_descriptors` reads.

    The vertices themselves are not in the model. They live in a separate bank addressed through
    segment 8, and *vertices* is therefore a second buffer rather than a slice of *data*.

    The field layout is taken from the port's interpreter, ``MakeMatN64`` at ``0x0040BF10`` in
    ``xg2pc.exe``, rather than inferred. It byte-swaps the first word before doing anything with it,
    and a command word is therefore read big-endian here with the opcode in its low byte. The vertex
    handler at
    ``0x0040C5E9`` then does ``SHR EAX,0x12 / AND EAX,0x3F`` for the count and
    ``SHR ECX,0x9 / AND ECX,0x7F`` for the first slot.

    Parameters
    ----------
    data : bytes
        The model blob, with the display lists and the textures.
    vertices : bytes
        The vertex bank segment 8 addresses.

    Returns
    -------
    list[Mesh]
        One mesh per image.
    """
    buffer = VertexBuffer()
    texture: int | None = None
    expecting = False
    for start in _entry_points(data, '<'):
        if not _is_pc_display_list(data, start):
            continue
        for op, w0, w1 in _commands(data, start, '<'):
            if expecting:
                # The word after the marker and its palette stores the dimensions, and the one after
                # that the pixels, the key a decoded texture is reported under.
                expecting = False
                texture = w1 & 0xFFFFFF if (w1 >> 24) == _SEGMENT_5 else None
                continue
            if op == _PC_G_VTX:
                swapped = int.from_bytes(w0.to_bytes(4, 'little'), 'big')
                count = (swapped >> 18) & 0x3F
                first = (swapped >> 9) & 0x7F
                buffer.load(vertices, w1 & 0xFFFFFF, count, first, '<')
            elif op == _PC_G_TRI2:
                buffer.triangle(texture, _corners(w0), lit=True)
                buffer.triangle(texture, _corners(w1), lit=True)
            elif op == _G_TRI1:
                buffer.triangle(texture, _corners(w0), lit=True)
            elif op == _PC_TEXTURE:
                expecting = True
    return buffer.meshes()


def parse_display_lists(data: bytes, endian: Endian = '>') -> list[Mesh]:
    """
    Decode every triangle a flat model draws, grouped by the image it draws with.

    Parameters
    ----------
    data : bytes
        A flat model blob, whose segment-5 addresses index into itself.
    endian : dade.xg2.typing.Endian
        Byte order: ``>`` for the N64 builds, ``<`` for the PC port.

    Returns
    -------
    list[Mesh]
        One mesh per image, or an empty list when the blob is not a flat model.
    """
    buffer = VertexBuffer()
    texture: int | None = None
    pending: int | None = None
    mode = _G_LIGHTING
    for start in _entry_points(data, endian):
        for op, w0, w1 in _commands(data, start, endian):
            lit = bool(mode & _G_LIGHTING)
            if op == _G_VTX:
                count = (w0 >> 12) & 0xFF
                first = ((w0 >> 1) & 0x7F) - count
                if (w1 >> 24) == _SEGMENT_5:
                    buffer.load(data, w1 & 0xFFFFFF, count, first, endian)
            elif op == _G_GEOMETRYMODE:
                # The first word records the bits to retain, already inverted, and the second the
                # bits to set.
                mode = (mode & (w0 & 0xFFFFFF)) | w1
            elif op == _G_TRI1:
                buffer.triangle(texture, _corners(w0), lit=lit)
            elif op in {_G_TRI2, _G_QUAD}:
                buffer.triangle(texture, _corners(w0), lit=lit)
                buffer.triangle(texture, _corners(w1), lit=lit)
            elif op == _G_SETTIMG:
                pending = (w1 & 0xFFFFFF) if (w1 >> 24) == _SEGMENT_5 else None
            elif op == _G_LOADTLUT:
                # That image was a palette rather than pixels, and it does not identify the surface.
                pending = None
            elif op == _G_SETTILE and pending is not None:
                texture = pending
    return buffer.meshes()


def _corners(word: int) -> tuple[int, int, int]:
    """
    Read the three slot indices packed into a triangle command word.

    Every index is stored doubled. The microcode uses it as a byte offset into the vertex buffer.

    Parameters
    ----------
    word : int
        The command word with the corners.

    Returns
    -------
    tuple[int, int, int]
        The three slot indices.
    """
    return ((word >> 17) & 0x7F, (word >> 9) & 0x7F, (word >> 1) & 0x7F)


def texcoords(vertex: Vertex, width: int, height: int, scale: float = 1.0) -> tuple[float, float]:
    """
    Convert a vertex's fixed-point texture coordinates to glTF's normalised ones.

    Parameters
    ----------
    vertex : Vertex
        The vertex.
    width : int
        Width of the image in pixels.
    height : int
        Height of the image in pixels.
    scale : float
        Extra factor from ``G_TEXTURE``, one in every model seen so far.

    Returns
    -------
    tuple[float, float]
        The U and V coordinates.
    """
    u = vertex.s / _TEXCOORD_SHIFT * scale / max(width, 1)
    v = vertex.t / _TEXCOORD_SHIFT * scale / max(height, 1)
    return u, v


def demo() -> None:
    """
    Check the command decoding against display lists built by hand.

    Raises
    ------
    SelfCheckFailed
        If a command decodes to a value other than what the encoding dictates.
    """
    # G_TRI2 06000204 00040600 must give (0, 1, 2) and (2, 3, 0), the two halves of a quad.
    if _corners(0x06000204) != (0, 1, 2):  # pragma: no cover
        msg = f'First half of the quad unpacked to {_corners(0x06000204)}, expected (0, 1, 2).'
        raise SelfCheckFailed(msg)
    if _corners(0x00040600 | 0x06000000) != (2, 3, 0):  # pragma: no cover
        msg = (f'Second half of the quad unpacked to {_corners(0x00040600 | 0x06000000)}, '
               'expected (2, 3, 0).')
        raise SelfCheckFailed(msg)
    # G_VTX 0100F01E loads 15 vertices ending at slot 15, and therefore starts at slot 0.
    w0 = 0x0100F01E
    count = (w0 >> 12) & 0xFF
    if count != _DEMO_COUNT:  # pragma: no cover
        msg = f'G_VTX loads {count} vertices, expected {_DEMO_COUNT}.'
        raise SelfCheckFailed(msg)
    if ((w0 >> 1) & 0x7F) - count != 0:  # pragma: no cover
        msg = f'G_VTX ends at slot {(w0 >> 1) & 0x7F}, expected it to start at slot 0.'
        raise SelfCheckFailed(msg)

    header = struct.pack('>2I', 0x05000008, 0)
    # S and T are 10.5 fixed point, making one full wrap of a 32-pixel image 32 * 32.
    vertices = b''.join(
        struct.pack('>3hH2h4B', x, y, 0, 0, x * 32 * 32, y * 32 * 32, 255, 255, 255, 255)
        for x, y in ((0, 0), (1, 0), (1, 1), (0, 1)))
    commands = (
        (0xFD100000, 0x05000FF0),
        (0xF5000100, 0),
        (0x06000204, 0x00040600),
        (0xDF000000, 0),
    )
    # G_VTX loads 4 vertices ending at slot 4, from just past the command stream.
    at = len(header) + (len(commands) + 1) * _COMMAND_SIZE
    body = struct.pack('>2I', 0x01004008, 0x05000000 | at)
    body += b''.join(struct.pack('>2I', w0, w1) for w0, w1 in commands)
    blob = header + body + vertices
    if len(header + body) != at:  # pragma: no cover
        msg = f'Vertices start at {len(header + body)}, but the command points at {at}.'
        raise SelfCheckFailed(msg)
    meshes = parse_display_lists(blob)
    if len(meshes) != 1:
        msg = f'Display list yielded {len(meshes)} meshes, expected one.'
        raise SelfCheckFailed(msg)
    mesh = meshes[0]
    if mesh.texture != _DEMO_TEXTURE:
        msg = f'Mesh texture is {hex(mesh.texture or 0)}, expected {_DEMO_TEXTURE:#x}.'
        raise SelfCheckFailed(msg)
    if len(mesh.triangles) != _DEMO_TRIANGLES:
        msg = f'Mesh has {len(mesh.triangles)} triangles, expected {_DEMO_TRIANGLES}.'
        raise SelfCheckFailed(msg)
    if len(mesh.vertices) != _DEMO_VERTICES:
        msg = f'Mesh has {len(mesh.vertices)} vertices, expected {_DEMO_VERTICES}.'
        raise SelfCheckFailed(msg)
    if texcoords(mesh.vertices[1], 32, 32) != (1.0, 0.0):
        msg = f'Second corner mapped to {texcoords(mesh.vertices[1], 32, 32)}, expected (1.0, 0.0).'
        raise SelfCheckFailed(msg)
    # A branch out of range must end the list rather than run off into the data.
    if parse_display_lists(header + struct.pack('>2I', 0xDE000000, 0x05FFFFFF)):
        msg = 'A branch past the end of the data was followed instead of ending the list.'
        raise SelfCheckFailed(msg)
    print('f3dex2: command decoding verified.')  # ruff: ignore[print]


if __name__ == '__main__':
    demo()
