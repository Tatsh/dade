"""
Reader for the props and characters stored in ``.SGP2`` libraries.

A ``.SGP2`` file is a whole level's cast: doors, furniture, vehicles, and people. After the file
header come the embedded texture records, then a chain of named sections, one per object. Each
section's header gives its own length at ``0x0C`` and a string-table offset at ``0x08``, so the
chain is walked by adding the length.

A section is not a single mesh. It is a list of named items -- ``VITO_BODY``, ``VITO_HAIR_s4``,
``*BODY17`` -- each of which owns a small command list that names the material to draw it with. The
layout below is taken from the game's own accessors rather than guessed: ``t_SGP2`` reaches its
tables through one-line functions that add a header field to the section pointer, so
``FUN_001c6ab8`` gives ``section + section[0x54]`` for the items, ``FUN_001854e0`` gives
``section + section[0x50]`` for the materials, and the renderer at ``FUN_001c3938`` walks the
commands, switching material whenever it meets opcode 1.

Geometry is packetised the same way as in a ``.EGP2`` level, behind the same GIFtag, but the vertex
layout differs: two quadwords per vertex rather than the level format's four-vertex groups. The
first holds the position and the second the texture coordinate. Positions are object-local, so each
section sits at the origin rather than in world space; the level's ``.OLV`` says where each one
stands.

The GIFtag advertises three or four registers, which would be forty-eight or sixty-four bytes of
output, while the data is thirty-two bytes per vertex. There is no contradiction: what follows the
tag is the input VU1 transforms, not the output it sends to the GS.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import math
import re
import struct

from .model import TRIANGLE_LIST, TRIANGLE_STRIP

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = (
    'ITEM_SIZE',
    'MATERIAL_SIZE',
    'VERTEX_SIZE',
    'PropGroup',
    'PropItem',
    'PropSection',
    'PropVertex',
    'is_alternate',
    'read_items',
    'read_materials',
    'read_packets',
    'read_sections',
    'wardrobe_key',
)

log = logging.getLogger(__name__)

VERTEX_SIZE = 32
"""Bytes per vertex: one quadword of position, one of texture coordinate.

:meta hide-value:
"""

MATERIAL_SIZE = 0x34
"""Bytes per material: a word, then three sixteen-byte texture slots.

:meta hide-value:
"""

ITEM_SIZE = 20
"""Bytes per item record.

:meta hide-value:
"""

_SECTION_START_AT = 0x0C
_STRING_OFFSET_AT = 0x08
_SECTION_SIZE_AT = 0x0C
_MATERIAL_COUNT_AT = 0x3E
_ITEM_COUNT_AT = 0x40
_MATERIAL_TABLE_AT = 0x50
_ITEM_TABLE_AT = 0x54
_ITEM_NAME_AT = 0x00
_ITEM_SIZE_AT = 0x08
_ITEM_GEOMETRY_AT = 0x0C
_COMMAND_SIZE = 16
_COMMAND_LIST_AT = 0x10
_COMMAND_COUNT_AT = 0x0C
_SET_MATERIAL = 1
_END_GROUP = frozenset({7, 8, 0x1007, 0x1008})
_MATERIAL_SLOTS = 3
_SLOT_SIZE = 16
_SLOTS_AT = 4
_QUADWORD = 16
_CHUNK_HEADER_SIZE = 16
_MIN_LIBRARY_SIZE = 0x10
_NLOOP_MASK = 0x7FFF
_PRIM_SHIFT = 47
_NREG_SHIFT = 60
_EXPECTED_NREG = frozenset({3, 4})
_MAX_NLOOP = 4096
_COORDINATE_LIMIT = 1e5
_NAME_LIMIT = 120
_ALTERNATE_MARK = '*'
_DIGITS = re.compile(r'\d+')


class PropVertex(NamedTuple):
    """One vertex of a prop."""

    x: float
    """Object-local position along X."""
    y: float
    """Object-local position along Y."""
    z: float
    """Object-local position along Z."""
    u: float
    """Texture coordinate along U."""
    v: float
    """Texture coordinate along V."""


class PropGroup(NamedTuple):
    """One run of packets drawn with a single material."""

    material: int
    """Index into the section's material table."""
    packets: tuple[tuple[int, tuple[PropVertex, ...]], ...]
    """The GS primitive type and vertices of each packet."""


class PropItem(NamedTuple):
    """One named piece of an object, such as a body, a head, or one of several jackets."""

    name: str
    """The item's name, for example ``VITO_BODY`` or ``*BODY17``."""
    groups: tuple[PropGroup, ...]
    """The item's draw groups, in order."""


class PropSection(NamedTuple):
    """One named object inside a ``.SGP2`` library."""

    name: str
    """Full object path, such as ``.../satriales_doors/satriales_doors``."""
    offset: int
    """Byte offset of the section within the file."""
    size: int
    """Length of the section in bytes."""


def read_sections(data: bytes) -> tuple[PropSection, ...]:
    """
    Walk a ``.SGP2`` library's chain of object sections.

    Parameters
    ----------
    data : bytes
        The whole ``.SGP2`` file.

    Returns
    -------
    tuple[PropSection, ...]
        One entry per object, in file order.
    """
    if len(data) < _MIN_LIBRARY_SIZE:
        return ()
    at = struct.unpack_from('<I', data, _SECTION_START_AT)[0]
    sections = []
    while at + _CHUNK_HEADER_SIZE <= len(data):
        size = struct.unpack_from('<I', data, at + _SECTION_SIZE_AT)[0]
        strings = struct.unpack_from('<I', data, at + _STRING_OFFSET_AT)[0]
        if not size or at + size > len(data):
            break
        name_at = at + strings
        if name_at >= len(data):
            break
        end = data.find(b'\0', name_at)
        if end < 0:
            break
        sections.append(PropSection(data[name_at:end].decode('ascii', 'replace'), at, size))
        at += size
    return tuple(sections)


def _name(section: bytes, at: int) -> str:
    """
    Read a NUL-terminated name from a section.

    Parameters
    ----------
    section : bytes
        The section's bytes.
    at : int
        Offset of the name within the section.

    Returns
    -------
    str
        The name, empty when the offset does not point at one.
    """
    if not 0 < at < len(section):
        return ''
    end = section.find(b'\0', at)
    if not 0 < end - at <= _NAME_LIMIT:
        return ''
    return section[at:end].decode('ascii', 'replace')


def is_alternate(name: str) -> bool:
    """
    Report whether an item is one of several interchangeable pieces.

    A crowd character is dressed at random from a wardrobe held in the one model: the bum trucker
    carries both ``*BODY17`` and ``*BODY18``, and two pairs of shoes, all occupying the same space.
    The game shows one of each by passing the renderer a bitmask of the items to draw. The star is
    the cooker's mark for a piece that takes part in that choice.

    Parameters
    ----------
    name : str
        The item's name.

    Returns
    -------
    bool
        ``True`` when the item is one of an interchangeable set.
    """
    return name.startswith(_ALTERNATE_MARK)


def wardrobe_key(name: str) -> str:
    """
    Give the set an interchangeable item belongs to.

    ``*BODY17`` and ``*BODY18`` are two jackets for the same torso, so both answer ``BODY``. Every
    digit goes, not just the trailing ones, because a wardrobe numbers its alternatives in the
    middle of the name as readily as at the end: a business woman offers ``*HEAD7_Face_0`` beside
    ``*HEAD08_Face_0``, and both are the one head.

    Parameters
    ----------
    name : str
        The item's name.

    Returns
    -------
    str
        A key shared by the alternatives for one piece.
    """
    return _DIGITS.sub('', name.lstrip(_ALTERNATE_MARK))


def read_materials(section: bytes) -> tuple[tuple[str, ...], ...]:
    """
    Read a section's material table.

    Each material names up to three maps: the base colour, and where present the reflection and
    damage overlays the game blends over it.

    Parameters
    ----------
    section : bytes
        The section's bytes.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Per material, the texture names it references, base colour first.
    """
    if len(section) < _ITEM_TABLE_AT + 4:
        return ()
    count = struct.unpack_from('<H', section, _MATERIAL_COUNT_AT)[0]
    table = struct.unpack_from('<I', section, _MATERIAL_TABLE_AT)[0]
    if not table or table + count * MATERIAL_SIZE > len(section):
        return ()
    out = []
    for index in range(count):
        record = table + index * MATERIAL_SIZE
        names = []
        for slot in range(_MATERIAL_SLOTS):
            at = struct.unpack_from('<I', section, record + _SLOTS_AT + slot * _SLOT_SIZE)[0]
            if (found := _name(section, at)):
                names.append(found)
        out.append(tuple(names))
    return tuple(out)


def read_items(section: bytes) -> tuple[PropItem, ...]:
    """
    Read a section's items and the material each of their draw groups uses.

    An item points at a block of geometry, which opens with a small header giving where its command
    list starts and how long it is. Walking that list yields the groups: opcode 1 names the material
    to use from here on, and opcodes 7, 8, 0x1007 and 0x1008 close a group, carrying the byte offset
    and quadword length of the packets it covers. Summed over an item, the triangle counts those
    commands report match the item's own total for every one of the game's 8440 items.

    Parameters
    ----------
    section : bytes
        The section's bytes.

    Returns
    -------
    tuple[PropItem, ...]
        One entry per item that draws anything, in file order.
    """
    if len(section) < _ITEM_TABLE_AT + 4:
        return ()
    count = struct.unpack_from('<H', section, _ITEM_COUNT_AT)[0]
    table = struct.unpack_from('<I', section, _ITEM_TABLE_AT)[0]
    if not table or table + count * ITEM_SIZE > len(section):
        return ()
    items = []
    for index in range(count):
        record = table + index * ITEM_SIZE
        if not struct.unpack_from('<I', section, record + _ITEM_SIZE_AT)[0]:
            continue
        geometry = record + struct.unpack_from('<i', section, record + _ITEM_GEOMETRY_AT)[0]
        if not 0 <= geometry < len(section) - _COMMAND_LIST_AT:
            continue
        commands = geometry + _COMMAND_LIST_AT + struct.unpack_from('<I', section, geometry)[0]
        total = struct.unpack_from('<I', section, geometry + _COMMAND_COUNT_AT)[0]
        if total > _MAX_NLOOP or commands + total * _COMMAND_SIZE > len(section):
            continue
        name = _name(section, record + struct.unpack_from('<i', section, record + _ITEM_NAME_AT)[0])
        material = 0
        groups = []
        for step in range(total):
            at = commands + step * _COMMAND_SIZE
            opcode = struct.unpack_from('<H', section, at)[0]
            if opcode == _SET_MATERIAL:
                material = struct.unpack_from('<I', section, at + 4)[0]
            elif opcode in _END_GROUP:
                start, length = struct.unpack_from('<2I', section, at + 4)
                packets = tuple(
                    read_packets(section, geometry + start, geometry + start + length * _QUADWORD))
                if packets:
                    groups.append(PropGroup(material, packets))
        if groups:
            items.append(PropItem(name, tuple(groups)))
    return tuple(items)


def read_packets(section: bytes,
                 start: int = 0,
                 end: int | None = None) -> Iterator[tuple[int, tuple[PropVertex, ...]]]:
    """
    Yield the draw packets in a stretch of a section.

    Packets are found by their GIFtag rather than by walking a table, because the tag is
    self-describing: its NLOOP field gives the vertex count, PRIM the primitive type, and NREG the
    per-vertex register count, which is three or four here -- the four-register form pads with a NOP
    and carries the same thirty-two byte vertex. A candidate is accepted only when the whole vertex
    block fits and every coordinate is finite and of a sane magnitude, which rejects the occasional
    word that looks like a tag by chance.

    Parameters
    ----------
    section : bytes
        The section's bytes.
    start : int
        Where to begin.
    end : int | None
        Where to stop, defaulting to the end of the section.

    Yields
    ------
    tuple[int, tuple[PropVertex, ...]]
        The GS primitive type and the packet's vertices.
    """
    limit = len(section) if end is None else min(end, len(section))
    at = max(start, 0)
    while at + _CHUNK_HEADER_SIZE <= limit:
        low, high = struct.unpack_from('<2I', section, at)
        tag = low | (high << 32)
        count = tag & _NLOOP_MASK
        primitive = (tag >> _PRIM_SHIFT) & 7
        finish = at + _CHUNK_HEADER_SIZE + count * VERTEX_SIZE
        # A packet belongs to the group whose range its tag starts in, and the last one in a group
        # may run a few bytes past the length the command reports, so only the tag is bounded.
        if (not (low >> 15) & 1 or not 0 < count < _MAX_NLOOP
                or primitive not in {TRIANGLE_LIST, TRIANGLE_STRIP}
                or (tag >> _NREG_SHIFT) & 0xF not in _EXPECTED_NREG or finish > len(section)):
            at += 4
            continue
        vertices = []
        for i in range(count):
            row = at + _CHUNK_HEADER_SIZE + i * VERTEX_SIZE
            x, y, z, _w = struct.unpack_from('<4f', section, row)
            u, v, _a, _b = struct.unpack_from('<4f', section, row + 16)
            if not all(math.isfinite(value) for value in (x, y, z, u, v)):
                break
            if max(abs(x), abs(y), abs(z)) > _COORDINATE_LIMIT:
                break
            vertices.append(PropVertex(x, y, z, u, v))
        if len(vertices) != count:
            at += 4
            continue
        yield primitive, tuple(vertices)
        at = finish
