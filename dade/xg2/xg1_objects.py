"""
Extreme-G (N64) track objects: the power-up pads and the flame columns.

A level's track region ends with a typed entity stream. The parser at ``0x8009F310`` reads a type
byte, calls one of twenty handlers, and advances by the size the handler returns; every record is 32
bytes carrying an ``s32`` position, which its spawner confirms by loading ``+0x08``, ``+0x0C``, and
``+0x10`` into the object's x, y, and z.

Type zero is the generic object. Its sub-type byte indexes a table of id lists, an id from that list
indexes a model table, and the model is an F3DEX display list. All of that lives in a second code
segment the ROM keeps LZHUF compressed and which runs at ``0x8009B898``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import math
import struct

from dade.common.exceptions import UnreachableState

from .lzhuf import LzhufError, decompress_lzhuf
from .typing import Texture
from .xg1_level import XG1, read_header

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .xg1_level import Dialect

__all__ = ('GLOW_ALPHA', 'GLOW_STEPS', 'GLOW_TEXTURE_KEY', 'ICON_TICKS', 'OBJECT_LIFT', 'TICK_HZ',
           'Entity', 'ObjectModel', 'ObjectPlacement', 'face_colour', 'glow_model', 'glow_textures',
           'is_flame', 'object_placements', 'pickup_swing', 'read_code_segment', 'read_entities',
           'read_object_models')

SEGMENT_ROM = 0x2F484
"""ROM offset of the second code segment.

:meta hide-value:
"""
SEGMENT_SIZE = 0xB8128
"""Its decompressed size.

:meta hide-value:
"""
SEGMENT_BASE = 0x8009B898
"""Where it runs.

:meta hide-value:
"""
# Set by the spawner at 0x8009FC50: a sub-type picks an id list, and an id picks a model.
_SUBTYPE_LISTS = 0x80106994
_MODEL_TABLE = 0x80106B04
_MODEL_RECORD = 12
_SUBTYPE_COUNT = 96
_LIST_MAX = 8
# The entity stream, at the track region's +0x40 pointer.
_ENTITY_POINTER = 0x40
_ENTITY_RECORD = 32
_ENTITY_POSITION = 8
_ENTITY_MAX = 1024
_OBJECT_TYPE = 0
# F3DEX, the same microcode the level geometry uses.
_G_VTX = 0x04
_G_DL = 0x06
_G_TRI2 = 0xB1
_G_ENDDL = 0xB8
_G_TRI1 = 0xBF
_G_SETPRIMCOLOR = 0xFA
_DL_DEPTH = 4
_VERTEX_SIZE = 16
_VERTEX_SLOTS = 32
_COMMAND_MAX = 512
_BYTE_MAX = 0xFF

OBJECT_LIFT = 100
"""How far the draw path lifts an icon above its record's position.

``0x800A0BE8`` loads 100.0 and passes ``(0, 100, 0)`` to the matrix helper at ``0x80054B64``.

:meta hide-value:
"""
TICK_HZ = 30
"""Ticks a second everything animated here is counted in.

The update runs once a displayed frame and the game runs at thirty: a capture shows 29 to 30 frames
a second against 59 VI.

:meta hide-value:
"""
ICON_TICKS = 161
"""Ticks an icon is shown for before the cycle steps on.

:meta hide-value:
"""
GLOW_STEPS = 64
"""Steps the glow's scroll is baked at.

The update adds 4 to the object's ``+0xD0`` each frame and the draw turns that into the tile's T
origin as ``(-value >> 1) & 0xFFF`` in 10.2 fixed point, which is half a texel a frame: a 32-texel
texture wraps every 64 frames.

:meta hide-value:
"""

# The two lights point in exactly opposite directions. The spawner packs each one's direction by
# multiplying the object's facing vector at +0x94 by a constant, and those constants are +127 and
# -127: the same axis, opposed, scaled into a signed byte. That also settles what +0x94 holds, a
# unit direction rather than Euler angles, since only a unit vector packs that way.
_AMBIENT = 0x80
_LIGHTS = (((0x00, 0xFF, 0x00), (0, 0, 1)), ((0xFF, 0xFF, 0xFF), (0, 0, -1)))
# The icon's update at 0x800A037C pushes the turn rate against the sign of the angle, so each axis
# swings about zero under a constant restoring push. The angles start at 20 with no rate, and only X
# and Z are driven: the rate for Y is written once at spawn and never touched.
_SPIN_START = 20
_SPIN_PUSH_X = 0.02
_SPIN_PUSH_Z = 0.05
# What an object draws, decided from its model id at 0x800A02EC. Mode two draws no icon and turns
# its glow red, which is the flame columns standing along a track rather than anything collectable.
_MODE_ICON_LIMIT = 0x36
_MODE_FLAME_ID = 0x37
# The glow every pickup sits inside, drawn by the same routine in a second pass. Its list sets the
# blend and texture state and defers to 0x80146120, ten vertices making a folded strip of upright
# panels. The draw sets its primitive colour at 0x800A0F28: red when the mode is two, green
# otherwise, straight from 0xFF000000 and 0x00FF0000.
_GLOW_LIST = 0x801064F0
_GLOW_COLOUR = (0x3C, 0xF0, 0x3C)
_FLAME_COLOUR = (0xF0, 0x3C, 0x3C)
# The glow draws through two 32 by 32 four-bit intensity textures. The setup list at 0x80106478
# loads them onto separate tiles and the scroll names tile one only, so the mottled cloud slides
# while the soft blob stands still, and multiplying by the blob thins the glow towards the top.
_GLOW_MASK_SOURCE = 0x80146160
_GLOW_CLOUD_SOURCE = 0x80146360
_GLOW_TEXTURE_SIDE = 32

GLOW_ALPHA = 0xFF
"""Alpha the glow's vertices carry.

:meta hide-value:
"""
GLOW_TEXTURE_KEY = -0x10000000
"""Key the first baked glow image takes; each later step is one lower.

:meta hide-value:
"""


class Entity(NamedTuple):
    """One record of a level's entity stream."""

    type: int
    """Type byte, which selects the handler that reads the rest of the record."""
    subtype: int
    """Sub-type byte, which for a type zero object selects its list of models."""
    x: int
    """World X."""
    y: int
    """World Y."""
    z: int
    """World Z."""


class ObjectModel(NamedTuple):
    """One display list decoded out of the second code segment."""

    id: int
    """The id this model was reached by, which decides the object's mode."""
    positions: tuple[tuple[int, int, int], ...]
    """Model-space corner positions, one per index."""
    coords: tuple[tuple[int, int], ...]
    """Texture coordinates in 10.5 fixed point. Only the glow uses them."""
    normals: tuple[tuple[float, float, float], ...]
    """The model's own unit normals."""
    indices: tuple[int, ...]
    """Corner indices, three to a triangle."""
    red: int
    """Primitive colour red."""
    green: int
    """Primitive colour green."""
    blue: int
    """Primitive colour blue."""


class ObjectPlacement(NamedTuple):
    """One placed object, with everything needed to draw it."""

    x: int
    """World X of the record."""
    y: int
    """World Y of the record."""
    z: int
    """World Z of the record."""
    icons: tuple[ObjectModel, ...]
    """The models the object cycles through, empty for a flame column."""
    glow: tuple[int, int, int]
    """Primitive colour the glow panels take."""


def read_entities(rom: bytes, base: int, dialect: Dialect = XG1) -> list[Entity]:
    """
    Read a level's entity stream.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    base : int
        Offset of the level container.
    dialect : dade.xg2.xg1_level.Dialect
        Supplies the byte order and where the track region sits.

    Returns
    -------
    list[Entity]
        Every record, empty when the level has no track region.
    """
    header = read_header(rom, base, dialect)
    if not header.region or not header.region_size:
        return []
    try:
        region = decompress_lzhuf(rom, base + header.region, header.region_size)
    except LzhufError:
        return []
    at = struct.unpack_from(f'{dialect.endian}I', region, _ENTITY_POINTER)[0]
    if not at or at >= len(region):
        return []
    return [
        Entity(region[record], region[record + 1],
               *struct.unpack_from(f'{dialect.endian}3i', region, record + _ENTITY_POSITION))
        for record in range(at,
                            len(region) - _ENTITY_RECORD + 1, _ENTITY_RECORD)
    ][:_ENTITY_MAX]


def read_code_segment(rom: bytes) -> bytes:
    """
    Decompress the second code segment, which every level's objects are drawn from.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    bytes
        The segment, empty when it will not decompress.
    """
    try:
        return decompress_lzhuf(rom, SEGMENT_ROM, SEGMENT_SIZE)
    except LzhufError:
        return b''


def _read_intensity(segment: bytes, vram: int) -> bytes | None:
    """
    Read one 32 by 32 four-bit intensity image out of the segment.

    Returns
    -------
    bytes | None
        One byte a texel, or :py:obj:`None` when the address is outside the segment.
    """
    at = vram - SEGMENT_BASE
    texels = _GLOW_TEXTURE_SIDE * _GLOW_TEXTURE_SIDE
    if at < 0 or at + texels // 2 > len(segment):
        return None
    packed = segment[at:at + texels // 2]
    # Four bits an intensity, two to a byte, widened by repeating the nibble.
    return bytes(
        (packed[i >> 1] >> 4 if i % 2 == 0 else packed[i >> 1] & 0xF) * 0x11 for i in range(texels))


def glow_textures(segment: bytes, steps: int = GLOW_STEPS) -> list[Texture]:
    """
    Bake one image per step of the glow's scroll.

    The cloud is shifted against the fixed mask rather than the texture coordinates sliding, which
    is what keeps the mask still. A step is half a texel, so the rows either side are mixed rather
    than jumped between.

    Parameters
    ----------
    segment : bytes
        The decompressed second code segment.
    steps : int
        How many steps to bake.

    Returns
    -------
    list[dade.xg2.typing.Texture]
        The baked images, empty when either source is missing.
    """
    mask = _read_intensity(segment, _GLOW_MASK_SOURCE)
    cloud = _read_intensity(segment, _GLOW_CLOUD_SOURCE)
    if mask is None or cloud is None:
        return []
    side = _GLOW_TEXTURE_SIDE
    out = []
    for step in range(steps):
        shift = (step / steps) * side
        whole = math.floor(shift)
        blend = shift - whole
        pixels = bytearray(side * side * 4)
        for y in range(side):
            near = ((y + whole) % side) * side
            far = ((y + whole + 1) % side) * side
            for x in range(side):
                value = cloud[near + x] * (1 - blend) + cloud[far + x] * blend
                at = (y * side + x) * 4
                pixels[at:at + 3] = b'\xff\xff\xff'
                # The mask is left at its own scale rather than stretched to full: it peaks around
                # 119, and pushing that to 255 clamps most of the sheet solid and throws away the
                # falloff that makes the glow a haze instead of a box. Half rounds up rather than to
                # even, which is what puts every odd step of the blend on the same value the browser
                # viewer produces.
                pixels[at + 3] = math.floor(value * mask[y * side + x] / _BYTE_MAX + 0.5)
        out.append(Texture('i8', GLOW_TEXTURE_KEY - step, side, side, bytes(pixels)))
    return out


def _load_vertices(segment: bytes, word0: int, word1: int,
                   buffer: list[tuple[int, int, int] | None], texel: list[tuple[int, int]],
                   normal: list[tuple[float, float, float]]) -> None:
    """
    Run one ``G_VTX`` into the slot buffers.

    Parameters
    ----------
    segment : bytes
        The decompressed second code segment.
    word0 : int
        The command's first word: bits 0 to 9 are the block's length in bytes less one, and bits 10
        to 15 the slot it ends at.
    word1 : int
        Address the vertices are read from.
    buffer : list[tuple[int, int, int] | None]
        Positions, filled in place.
    texel : list[tuple[int, int]]
        Texture coordinates, filled in place.
    normal : list[tuple[float, float, float]]
        Unit normals, filled in place.
    """
    count = ((word0 & 0x3FF) + 1) // _VERTEX_SIZE
    end = (word0 >> 10) & 0x3F
    first = end - count
    source = word1 - SEGMENT_BASE
    if first < 0 or end > _VERTEX_SLOTS or source < 0 or source + count * _VERTEX_SIZE > len(
            segment):
        return
    for i in range(count):
        at = source + i * _VERTEX_SIZE
        buffer[first + i] = struct.unpack_from('>3h', segment, at)
        texel[first + i] = struct.unpack_from('>2h', segment, at + 8)
        packed = struct.unpack_from('>3b', segment, at + 12)
        scale = math.hypot(*packed) or 1
        normal[first + i] = (packed[0] / scale, packed[1] / scale, packed[2] / scale)


def _decode_model(segment: bytes, vram: int, depth: int = 0) -> ObjectModel | None:
    """
    Run one F3DEX display list out of the segment.

    Returns
    -------
    ObjectModel | None
        The model, or :py:obj:`None` when it draws nothing.

    Raises
    ------
    UnreachableState
        If a vertex slot is still empty after the empty ones have been filtered out.
    """
    if depth > _DL_DEPTH:
        return None
    # Vertices land in a slot buffer at a destination slot rather than in a list: a display list may
    # load several blocks, and the triangles index the buffer.
    buffer: list[tuple[int, int, int] | None] = [None] * _VERTEX_SLOTS
    texel: list[tuple[int, int]] = [(0, 0)] * _VERTEX_SLOTS
    normal: list[tuple[float, float, float]] = [(0.0, 1.0, 0.0)] * _VERTEX_SLOTS
    positions: list[tuple[int, int, int]] = []
    coords: list[tuple[int, int]] = []
    normals: list[tuple[float, float, float]] = []
    indices: list[int] = []
    red = green = blue = _BYTE_MAX
    for step in range(_COMMAND_MAX):
        at = vram - SEGMENT_BASE + step * 8
        if at < 0 or at + 8 > len(segment):
            break
        word0, word1 = struct.unpack_from('>2I', segment, at)
        command = word0 >> 24
        if command == _G_ENDDL:
            break
        if command == _G_VTX:
            _load_vertices(segment, word0, word1, buffer, texel, normal)
        elif command in {_G_TRI1, _G_TRI2}:
            # A triangle is resolved against the buffer as it stands now. A later G_VTX reloads the
            # same slots, so deferring the lookup gives every earlier triangle the wrong vertices.
            for word in ((word0, word1) if command == _G_TRI2 else (word1,)):
                slots = tuple(((word >> shift) & _BYTE_MAX) >> 1 for shift in (16, 8, 0))
                if any(slot >= _VERTEX_SLOTS or buffer[slot] is None for slot in slots):
                    continue
                indices += [len(positions), len(positions) + 1, len(positions) + 2]
                for slot in slots:
                    corner = buffer[slot]
                    if corner is None:  # pragma: no cover
                        msg = f'Vertex slot {slot} is empty, but the check above ruled that out.'
                        raise UnreachableState(msg)
                    positions.append(corner)
                    coords.append(texel[slot])
                    normals.append(normal[slot])
        elif command == _G_DL:
            if (nested := _decode_model(segment, word1, depth + 1)) is not None:
                first = len(positions)
                positions += nested.positions
                coords += nested.coords
                normals += nested.normals
                indices += [first + index for index in nested.indices]
        elif command == _G_SETPRIMCOLOR:
            red, green, blue = ((word1 >> 24) & _BYTE_MAX, (word1 >> 16) & _BYTE_MAX,
                                (word1 >> 8) & _BYTE_MAX)
    if not positions:
        return None
    return ObjectModel(0, tuple(positions), tuple(coords), tuple(normals), tuple(indices), red,
                       green, blue)


def read_object_models(segment: bytes) -> list[tuple[ObjectModel, ...]]:
    """
    Read every model a sub-type cycles through, indexed by sub-type.

    The update at ``0x800A01D8`` keeps an index at ``+0xD5`` into this list and steps it on a timer,
    wrapping at the list's ``-1`` terminator, so a pickup shows each icon in turn rather than one of
    several variants.

    Parameters
    ----------
    segment : bytes
        The decompressed second code segment.

    Returns
    -------
    list[tuple[ObjectModel, ...]]
        One cycle per sub-type.
    """
    cache: dict[int, ObjectModel | None] = {}
    out: list[tuple[ObjectModel, ...]] = []
    for subtype in range(_SUBTYPE_COUNT):
        frames: list[ObjectModel] = []
        out.append(())
        list_at = _SUBTYPE_LISTS + subtype * 4 - SEGMENT_BASE
        if list_at < 0 or list_at + 4 > len(segment):
            continue
        entries = struct.unpack_from('>I', segment, list_at)[0] - SEGMENT_BASE
        if entries < 0 or entries + 2 > len(segment):
            continue
        for step in range(_LIST_MAX):
            if entries + step * 2 + 2 > len(segment):
                break
            identifier = struct.unpack_from('>h', segment, entries + step * 2)[0]
            if identifier < 0:
                break
            record = _MODEL_TABLE + identifier * _MODEL_RECORD - SEGMENT_BASE
            if record < 0 or record + 4 > len(segment):
                break
            vram = struct.unpack_from('>I', segment, record)[0]
            if vram not in cache:
                cache[vram] = _decode_model(segment, vram)
            # The id decides the mode, so it travels with the model rather than the display list,
            # which several ids share.
            if (model := cache[vram]) is not None:
                frames.append(model._replace(id=identifier))
        out[subtype] = tuple(frames)
    return out


def is_flame(model: ObjectModel | None) -> bool:
    """
    Say whether a model is a flame column rather than a pickup.

    Parameters
    ----------
    model : ObjectModel | None
        The first model of an object's cycle.

    Returns
    -------
    bool
        True when the object draws no icon and its glow is red.
    """
    return model is not None and model.id >= _MODE_ICON_LIMIT and model.id == _MODE_FLAME_ID


def object_placements(entities: Sequence[Entity],
                      models: Sequence[tuple[ObjectModel, ...]]) -> list[ObjectPlacement]:
    """
    Pair every placed object with the models it draws.

    Parameters
    ----------
    entities : collections.abc.Sequence[Entity]
        The level's entity stream.
    models : collections.abc.Sequence[tuple[ObjectModel, ...]]
        Cycles indexed by sub-type.

    Returns
    -------
    list[ObjectPlacement]
        One entry per drawable object, in stream order.
    """
    out = []
    for entity in entities:
        if entity.type != _OBJECT_TYPE or entity.subtype >= len(models):
            continue
        if not (cycle := models[entity.subtype]):
            continue
        flame = is_flame(cycle[0])
        out.append(
            ObjectPlacement(entity.x, entity.y, entity.z, () if flame else cycle,
                            _FLAME_COLOUR if flame else _GLOW_COLOUR))
    return out


def glow_model(segment: bytes) -> ObjectModel | None:
    """
    Decode the folded strip of upright panels every object's glow is drawn with.

    Parameters
    ----------
    segment : bytes
        The decompressed second code segment.

    Returns
    -------
    ObjectModel | None
        The panels, or :py:obj:`None` when the list will not decode.
    """
    return _decode_model(segment, _GLOW_LIST)


def face_colour(model: ObjectModel, triangle: int) -> tuple[int, int, int]:
    """
    Light one of an icon's faces the way its draw path does.

    The normal is taken from the face itself rather than from the stored per-vertex ones: lighting
    an icon from those shades smoothly across each edge and the shape reads as rounded, while these
    icons are flat plates whose faces should stay distinct.

    Parameters
    ----------
    model : ObjectModel
        The model the face belongs to.
    triangle : int
        Index of the first of the face's three corner indices.

    Returns
    -------
    tuple[int, int, int]
        The lit colour.
    """
    corners = [model.positions[model.indices[triangle + i]] for i in range(3)]
    a = [corners[1][i] - corners[0][i] for i in range(3)]
    b = [corners[2][i] - corners[0][i] for i in range(3)]
    face = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    scale = math.hypot(*face) or 1
    unit = [value / scale for value in face]
    # Ambient plus each light by how squarely the face meets it, all in the hardware's 0 to 255 and
    # clamped there before it modulates the primitive colour, which is what keeps a lit face at full
    # rather than letting two lights drive it past white.
    channels = [float(_AMBIENT)] * 3
    for colour, direction in _LIGHTS:
        lit = max(sum(unit[i] * direction[i] for i in range(3)), 0)
        for i in range(3):
            channels[i] += colour[i] * lit
    red, green, blue = (
        math.floor(base * min(value, _BYTE_MAX) / _BYTE_MAX + 0.5)
        for base, value in zip((model.red, model.green, model.blue), channels, strict=True))
    return red, green, blue


def _swing(frames: float, start: float, push: float) -> float:
    """
    Say where a constant-push swing has got to after *frames*.

    The motion is four parabolic arcs: down to zero, on to the far side, back to zero, and home.

    Returns
    -------
    float
        The angle in degrees.
    """
    quarter = math.sqrt((2 * start) / push)
    at = frames % (quarter * 4)
    if at < quarter:
        return start - 0.5 * push * at * at
    if at < quarter * 2:
        u = at - quarter
        return -push * quarter * u + 0.5 * push * u * u
    if at < quarter * 3:
        u = at - quarter * 2
        return -start + 0.5 * push * u * u
    u = at - quarter * 3
    return push * quarter * u - 0.5 * push * u * u


def pickup_swing(seconds: float) -> tuple[float, float]:
    """
    Give an icon's two swinging angles at a moment.

    Parameters
    ----------
    seconds : float
        Time since the level loaded.

    Returns
    -------
    tuple[float, float]
        The X and Z angles in radians.
    """
    frames = seconds * TICK_HZ
    return (math.radians(_swing(frames, _SPIN_START, _SPIN_PUSH_X)),
            math.radians(_swing(frames, _SPIN_START, _SPIN_PUSH_Z)))
