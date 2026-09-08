"""
Extreme-G (N64) level geometry.

The first game does not store its levels as display lists, and it does not store a vertex array
either. It stores a **bytecode**, LZHUF-compressed, which ``LoadLevelResources`` walks once at load
time to build the display lists the RSP then draws every frame. Nothing in the ROM assembles a
``G_VTX`` command outside that function, which is what makes the level data look empty to a
display-list walker.

The interpreter here is a transcription of that loader, at ``0x8004FDB8``-``0x80051900`` in the
Extreme-G ROM. Its dispatch is a jump table at ``0x8004BA98`` indexed by a byte from the stream:
zero ends the level, one to fifteen select a handler. Only the handlers that carry geometry are
acted on; the rest are still *decoded*, because every opcode consumes a fixed number of bytes and
skipping one by the wrong amount desynchronises everything after it.

Vertices arrive ten bytes at a time and are not self-describing: the position is three big-endian
``s16``, then one byte indexes the level's ``t4`` table for the texture coordinates, then three
bytes give a colour. Triangles are a sixteen-bit word holding three five-bit indices into the
thirty-two-slot vertex buffer, which the loader doubles on its way into ``G_TRI1``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import struct

from dade.common.exceptions import SelfCheckFailed

from .f3dex2 import Vertex, VertexBuffer
from .images import decode_ci, decode_i8, read_tlut
from .lzhuf import LzhufError, decompress_lzhuf
from .offsets import XG1_GLOBAL_TEXTURE_BANK_POINTER
from .rom import read_u32, xg1_level_banks
from .typing import Endian, Texture

if TYPE_CHECKING:
    from .f3dex2 import Mesh

__all__ = (
    'LEVEL_HEADER_SIZE',
    'XG1',
    'XG2',
    'XG2PC',
    'Dialect',
    'DrawState',
    'LevelHeader',
    'TextureDescriptor',
    'bank_texture_key',
    'decode_level_geometry',
    'decode_level_textures',
    'read_bank_descriptors',
    'read_header',
    'read_texture_bank',
    'read_textures',
)

log = logging.getLogger(__name__)

LEVEL_HEADER_SIZE = 0x44
"""Size of a level container header.

:meta hide-value:
"""

_END = 0
_OP_VERTICES = 1
_OP_TEXTURE = 2
_OP_PRIM_COLOR = 3
_OP_TRI1 = 4
_OP_TRI2 = 5
_OP_NORMALS = 8
_OP_MODIFY_ST = 9
_OP_TEXTURED_COMBINE = 6
_OP_FLAT_COMBINE = 7
_OP_SHARED_BANK = 12
_OP_LEVEL_BANK = 13
_OP_MAX = 15
# Bytes each opcode takes off the stream after its own dispatch byte, counted from the number of
# DecodeLzhufByte calls in each handler. Vertices are the one variable-length case.
_OPERAND_BYTES = {
    _OP_TEXTURE: 1,
    _OP_PRIM_COLOR: 3,
    _OP_TRI1: 2,
    _OP_TRI2: 4,
    6: 0,
    7: 0,
    9: 2,
    10: 0,
    11: 0,
    12: 1,
    13: 1,
    14: 0,
    15: 0,
}
_VERTEX_BYTES = 10
_NORMAL_BYTES = 6
_INDEX_BITS = 5
_INDEX_MASK = (1 << _INDEX_BITS) - 1
_UV_RECORD = 4
_TEXTURE_RECORD = 12
_OBJECT_RECORD = 0x28
_SIGN_16 = 0x8000
_MAX_TEXTURES = 256
_TLUT_ENTRIES = 256
_CI4_TLUT_ENTRIES = 16
_CI8_DEPTH = 8
# Bits per pixel each format tag means. A descriptor proves which is which: a 32 by 32 image with
# format 1 leaves 0x400 bytes before its palette and one with format 2 leaves 0x200, so format 1 is
# eight bits a pixel and format 2 is four.
_FORMAT_DEPTH = {1: 8, 2: 4}
_BANK_TABLE = 8
_BANK_RECORD = 8
_MAX_BANK_SIZE = 0x200000
_MAX_TEXTURE_SIDE = 256
_TLUT_BYTES = _TLUT_ENTRIES * 2
# Bank textures share the mesh keyspace with the level pool's pixel offsets, so they are tagged with
# the bank's own ROM offset to keep the two apart.
_BANK_KEY_SHIFT = 32


class Dialect(NamedTuple):
    """How one game lays out its level header and its geometry bytecode."""

    header_size: int
    """Bytes of header the loader reads."""
    fields: tuple[int, int, int, int, int, int, int, int, int]
    """Word indices of objects, object count, t1, t1 count, r2, r2 size, t4, t4 count, and
    stream."""
    stream_size_field: int
    """Word index of the decompressed size of the geometry stream."""
    max_opcode: int
    """Highest opcode the loader's range check allows."""
    operands: dict[int, int]
    """Bytes each fixed-length opcode takes after its dispatch byte."""
    triangle_flags: bool
    """Whether a triangle opcode is preceded by a visibility byte, as XG2's is."""
    endian: Endian
    """Byte order of every multi-byte field, in the header and in the bytecode alike."""
    banked_textures: bool
    """Whether opcodes twelve and thirteen bind textures from the two shared banks.

    Extreme-G's handlers at ``0x80050E20`` and ``0x8005136C`` are the same routine over different
    globals, and neither reads the level's own descriptor table: each indexes an eight-byte record
    in a bank the loader put there, one shared by every level and one chosen per level. Levels that
    lean on them draw a large share of their track through these opcodes.
    """
    texture_scale: float
    """Factor the game's own ``G_TEXTURE`` applies to every texture coordinate.

    Extreme-G issues ``gsSPTexture(0x8000, 0x8000, ...)`` -- a half -- which the coordinates bear
    out: the ``t4`` table steps by 2048, and halving that lands a 32-pixel texture on 0.5 to 31.5
    texels, the usual inset that samples pixel centres. Without it every level draws its textures
    at twice the size and tiled. XG2 measures the same way.
    """
    region_fields: tuple[int, int] | None = None
    """Word indices of the track region's offset and decompressed size.

    The region holds the spline, the collision grid, the sprites, and the entity stream. It is
    :py:obj:`None` for a game that lays the region out differently, as XG2 does: its section offsets
    sit at words 12, 14, and 16 with no counts beside them.
    """


XG1 = Dialect(header_size=0x44,
              fields=(0, 1, 3, 4, 5, 6, 13, 14, 15),
              stream_size_field=16,
              max_opcode=15,
              operands={
                  2: 1,
                  3: 3,
                  6: 0,
                  7: 0,
                  9: 2,
                  10: 0,
                  11: 0,
                  12: 1,
                  13: 1,
                  14: 0,
                  15: 0
              },
              triangle_flags=False,
              endian='>',
              banked_textures=True,
              texture_scale=0.5,
              region_fields=(7, 8))
"""Extreme-G. Fifteen opcodes, dispatched through the table at ``0x8004BA98``.

:meta hide-value:
"""

XG2 = Dialect(header_size=0x50,
              fields=(1, 2, 4, 5, 6, 7, 14, 15, 16),
              stream_size_field=17,
              max_opcode=20,
              operands={
                  2: 1,
                  3: 3,
                  6: 0,
                  7: 0,
                  9: 2,
                  10: 0,
                  11: 0,
                  12: 1,
                  13: 1,
                  14: 0,
                  15: 0,
                  16: 0,
                  17: 0,
                  18: 0,
                  19: 0,
                  20: 2
              },
              triangle_flags=True,
              endian='>',
              banked_textures=False,
              texture_scale=0.5)
"""Extreme-G XG2. Twenty opcodes, dispatched through the table at ``0x8004BC10``. Its triangles
carry a leading visibility byte and its vertices load through F3DEX2 rather than F3D.

:meta hide-value:
"""

XG2PC = XG2._replace(endian='<')
"""Extreme-G XG2 for Windows, whose ``.pcb`` tracks are the console levels with their multi-byte
fields byte-swapped.

The content is otherwise identical: ``aqua1.pcb`` declares 286 objects and a ``0x57D63`` byte
stream, the same as the ROM's level at ``0x1107E0``, and the two streams differ only in the order
of each halfword. Nothing else about the format changes, so the same interpreter reads both.

:meta hide-value:
"""


class LevelHeader(NamedTuple):
    """The parts of a level container header this module needs."""

    objects: int
    """ROM offset, relative to the container, of the object records."""
    object_count: int
    """Number of objects, each :py:data:`_OBJECT_RECORD` bytes."""
    textures: int
    """Offset of the ``t1`` texture descriptor table."""
    texture_count: int
    """Number of descriptors, each :py:data:`_TEXTURE_RECORD` bytes."""
    pixels: int
    """Offset of the ``r2`` pixel and palette pool."""
    pixels_size: int
    """Size of that pool once decompressed."""
    coords: int
    """Offset of the ``t4`` texture coordinate table."""
    coords_count: int
    """Number of coordinate pairs."""
    stream: int
    """Offset of the LZHUF geometry bytecode."""
    stream_size: int
    """Size of that bytecode once decompressed."""
    region: int = 0
    """Offset of the track region, zero when the dialect has none."""
    region_size: int = 0
    """Size of that region once decompressed."""


class DrawState(NamedTuple):
    """What the display list has selected: an image, a colour, and which of the two combiners."""

    texture: int | None
    """Pixel offset of the bound image, or :py:obj:`None` before one is chosen."""
    primitive: tuple[int, int, int] | None
    """Colour from the most recent ``G_SETPRIMCOLOR``, used by the flat combiner."""
    flat: bool
    """Whether the flat combiner is selected, which draws ``PRIMITIVE * SHADE`` and no texture."""


class TextureDescriptor(NamedTuple):
    """One 12-byte ``t1`` record."""

    width: int
    """Width in pixels."""
    height: int
    """Height in pixels."""
    pixel_format: int
    """Format tag; the loader compares it against one when choosing its tile setup."""
    pixels: int
    """Offset of the pixels within the ``r2`` pool."""
    palette: int
    """Offset of the palette within the ``r2`` pool."""


def read_header(rom: bytes, base: int, dialect: Dialect = XG1) -> LevelHeader:
    """
    Read a level container header.

    Parameters
    ----------
    rom : bytes
        The whole ROM image, which must be the original rather than the extended one: the extended
        ROM overwrites ``0x14A0``-``0x51498`` with the decompressed code segment.
    base : int
        Offset of the container.
    dialect : Dialect
        Which game's header layout to read.

    Returns
    -------
    LevelHeader
        The fields this module uses.
    """
    words = struct.unpack_from(f'{dialect.endian}{dialect.header_size // 4}I', rom, base)
    picked = [words[i] for i in dialect.fields]
    region, region_size = ((words[i] for i in dialect.region_fields) if dialect.region_fields else
                           (0, 0))
    return LevelHeader(objects=picked[0],
                       object_count=picked[1],
                       textures=picked[2],
                       texture_count=picked[3],
                       pixels=picked[4],
                       pixels_size=picked[5],
                       coords=picked[6],
                       coords_count=picked[7],
                       stream=picked[8],
                       stream_size=words[dialect.stream_size_field],
                       region=region,
                       region_size=region_size)


def read_textures(rom: bytes,
                  base: int,
                  header: LevelHeader,
                  dialect: Dialect = XG1) -> list[TextureDescriptor]:
    """
    Decode the ``t1`` descriptor table.

    Width and height are single bytes, not halfwords: the first record of level 5 reads
    ``20 20 01 00`` with its pixels at zero and its palette at ``0x400``, and 32 by 32 pixels is
    exactly the ``0x400`` bytes that gap allows.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    base : int
        Offset of the container.
    header : LevelHeader
        Its header.
    dialect : Dialect
        Supplies the byte order of the two offsets in each record.

    Returns
    -------
    list[TextureDescriptor]
        One entry per descriptor, empty when the table will not decompress.
    """
    size = header.texture_count * _TEXTURE_RECORD
    if not header.textures or not 0 < header.texture_count < _MAX_TEXTURES:
        return []
    try:
        table = decompress_lzhuf(rom, base + header.textures, size)
    except LzhufError:
        log.warning('The texture table of the container at 0x%X will not decompress.', base)
        return []
    out = []
    for index in range(header.texture_count):
        width, height, pixel_format, _flags, pixels, palette = struct.unpack_from(
            f'{dialect.endian}4B2I', table, index * _TEXTURE_RECORD)
        out.append(TextureDescriptor(width, height, pixel_format, pixels, palette))
    return out


def _coordinates(rom: bytes, base: int, header: LevelHeader,
                 dialect: Dialect) -> list[tuple[int, int]]:
    """
    Decode the ``t4`` table a vertex's one coordinate byte indexes.

    Returns
    -------
    list[tuple[int, int]]
        The S and T pair of each entry.
    """
    size = header.coords_count * _UV_RECORD
    if not header.coords or not size:
        return []
    try:
        table = decompress_lzhuf(rom, base + header.coords, size)
    except LzhufError:
        return []
    return [
        struct.unpack_from(f'{dialect.endian}2h', table, i * _UV_RECORD)
        for i in range(header.coords_count)
    ]


def _wrap(value: int) -> int:
    """
    Truncate a value to a signed halfword the way a ``sh`` store does.

    Returns
    -------
    int
        The wrapped value.
    """
    value &= 0xFFFF
    return value - 0x10000 if value >= _SIGN_16 else value


def _triangle(word: int) -> tuple[int, int, int]:
    """
    Unpack the three five-bit vertex indices a triangle word holds.

    Returns
    -------
    tuple[int, int, int]
        The three slot indices.
    """
    return ((word >> (2 * _INDEX_BITS)) & _INDEX_MASK, (word >> _INDEX_BITS) & _INDEX_MASK,
            word & _INDEX_MASK)


def decode_level_geometry(rom: bytes, base: int, dialect: Dialect = XG1) -> list[Mesh]:
    """
    Run a level's geometry bytecode and return its triangles.

    Parameters
    ----------
    rom : bytes
        The whole ROM image, original rather than extended.
    base : int
        Offset of the level container.
    dialect : Dialect
        :py:data:`XG1` or :py:data:`XG2`.

    Returns
    -------
    list[dade.xg2.f3dex2.Mesh]
        One mesh per texture the level draws with, empty when the bytecode will not decompress.
    """
    header = read_header(rom, base, dialect)
    if not header.stream or not header.stream_size:
        return []
    try:
        code = decompress_lzhuf(rom, base + header.stream, header.stream_size)
    except LzhufError as e:
        log.warning('The geometry stream of the container at 0x%X is truncated: %s', base, e)
        return []
    coords = _coordinates(rom, base, header, dialect)
    descriptors = read_textures(rom, base, header, dialect)
    banks = {
        opcode: [texture.offset for texture in read_texture_bank(rom, offset)]
        for opcode, offset in _level_banks(rom, base, dialect).items()
    }
    buffer = VertexBuffer()
    at = 0
    # The loader builds one display list for the whole level, so the texture a `set texture` opcode
    # chose stays in force until the next one, across object boundaries. Resetting it per object
    # leaves most of a track drawing untextured.
    state = DrawState(None, None, flat=False)
    for index in range(header.object_count):
        origin = _load_box(rom, base + header.objects + index * _OBJECT_RECORD, buffer,
                           dialect.endian)
        at, state = _run_object(code, at, buffer, coords, origin, descriptors, dialect, state,
                                banks)
        if at >= len(code):
            break
    return buffer.meshes()


def _level_banks(rom: bytes, base: int, dialect: Dialect) -> dict[int, int]:
    """
    Find the bank each of the two bank opcodes reads, as ROM offsets keyed by opcode.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    base : int
        Offset of the level container.
    dialect : Dialect
        Only :py:data:`XG1` has these opcodes.

    Returns
    -------
    dict[int, int]
        Empty for a dialect without banks, or for a container the level table does not list.
    """
    if not dialect.banked_textures:
        return {}
    level = xg1_level_banks(rom).get(base)
    if level is None:
        return {}
    return {
        _OP_SHARED_BANK: read_u32(rom, XG1_GLOBAL_TEXTURE_BANK_POINTER),
        _OP_LEVEL_BANK: level,
    }


def _load_box(rom: bytes, at: int, buffer: VertexBuffer, endian: Endian) -> tuple[int, int, int]:
    """
    Fill slots 0 to 7 with an object's bounding box and return where it sits.

    A record holds an origin and two further points, and the loader keeps only their differences
    from the origin. Corner ``i`` then takes its X from bit 0, its Y from bit 1, and its Z from bit
    2, which is a box.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    at : int
        Offset of the 0x28-byte record.
    buffer : dade.xg2.f3dex2.VertexBuffer
        Buffer whose first eight slots are filled.
    endian : dade.xg2.typing.Endian
        Byte order of the record.

    Returns
    -------
    tuple[int, int, int]
        The object's position, which its geometry is relative to.
    """
    if at + _OBJECT_RECORD > len(rom):
        return (0, 0, 0)
    values = struct.unpack_from(f'{endian}9i', rom, at)
    origin = values[0], values[1], values[2]
    # The loader subtracts as words and stores the result as a halfword, so a difference that does
    # not fit wraps. Keeping that wrap is what makes the corners agree with the game's.
    spans = [_wrap(values[3 + i] - origin[i % 3]) for i in range(6)]
    corners = ((spans[0], spans[3]), (spans[1], spans[4]), (spans[2], spans[5]))
    # These eight corners are a cull volume, not geometry: the loader follows them with G_CULLDL
    # (`lui v0,0xbe00` at 0x8004FE94), which tests them against the frustum and skips the object
    # when none are visible. Drawing them would paper the level in huge boxes, so only the origin
    # they are measured from is kept.
    del corners
    buffer.slots[:] = [None] * len(buffer.slots)
    return origin


def _load_vertices(code: bytes, at: int, count: int, buffer: VertexBuffer,
                   coords: list[tuple[int, int]], origin: tuple[int, int,
                                                                int], endian: Endian) -> int:
    """
    Read *count* vertices into the buffer's first slots.

    A vertex is ten bytes: three big-endian halfwords of position, one byte indexing the ``t4``
    table for its texture coordinates, then three of colour.

    Parameters
    ----------
    code : bytes
        The decompressed bytecode.
    at : int
        Offset of the first vertex.
    count : int
        How many to read.
    buffer : dade.xg2.f3dex2.VertexBuffer
        Buffer to fill.
    coords : list[tuple[int, int]]
        The ``t4`` texture coordinate table.
    origin : tuple[int, int, int]
        Added to each position.
    endian : dade.xg2.typing.Endian
        Byte order of the position halfwords.

    Returns
    -------
    int
        Offset just past the vertices.
    """
    for slot in range(count):
        if at + _VERTEX_BYTES > len(code):
            return len(code)
        x, y, z = struct.unpack_from(f'{endian}3h', code, at)
        index = code[at + 6]
        s, t = coords[index] if index < len(coords) else (0, 0)
        if slot < len(buffer.slots):
            # The loader stores alpha as zero because this game shades from the primitive colour
            # and the texture rather than from vertex alpha. Carrying that zero into glTF would
            # make every surface invisible, so it is written opaque.
            buffer.slots[slot] = Vertex(x + origin[0], y + origin[1], z + origin[2], s, t,
                                        code[at + 7], code[at + 8], code[at + 9], 0xFF)
        at += _VERTEX_BYTES
    return at


def _run_object(code: bytes, at: int, buffer: VertexBuffer, coords: list[tuple[int, int]],
                origin: tuple[int, int,
                              int], descriptors: list[TextureDescriptor], dialect: Dialect,
                state: DrawState, banks: dict[int, list[int]]) -> tuple[int, DrawState]:
    """
    Interpret one object's geometry, stopping at its terminator.

    Parameters
    ----------
    code : bytes
        The decompressed bytecode.
    at : int
        Where this object's bytecode begins.
    buffer : dade.xg2.f3dex2.VertexBuffer
        Vertex buffer and triangle sink.
    coords : list[tuple[int, int]]
        The ``t4`` texture coordinate table.
    origin : tuple[int, int, int]
        Added to every position, so the level comes out as one scene.
    descriptors : list[TextureDescriptor]
        The ``t1`` table, used to turn a texture opcode's index into a pixel offset.
    dialect : Dialect
        Which game's opcode set to interpret.
    state : DrawState
        Texture, primitive colour and combine mode in force on entry, carried over from the
        previous object.
    banks : dict[int, list[int]]
        Texture keys each bank opcode can select, in record order.

    Returns
    -------
    tuple[int, DrawState]
        Where the next object's bytecode begins, and the drawing state left in force.
    """
    end = len(code)
    texture, primitive, flat = state
    # XG2 puts a visibility byte in front of every triangle, which selects the geometry variant a
    # track shows. Everything it can show is wanted here, so the byte is stepped over rather than
    # tested.
    flags = 1 if dialect.triangle_flags else 0
    while at < end:
        opcode = code[at]
        at += 1
        if opcode == _END or opcode > dialect.max_opcode:
            break
        if opcode == _OP_VERTICES:
            count = code[at] if at < end else 0
            at = _load_vertices(code, at + 1, count, buffer, coords, origin, dialect.endian)
            continue
        if opcode == _OP_TEXTURE:
            index = code[at] if at < end else None
            texture = (descriptors[index].pixels
                       if index is not None and index < len(descriptors) else None)
            at += 1
            continue
        if opcode == _OP_PRIM_COLOR:
            if at + 3 <= end:
                primitive = (code[at], code[at + 1], code[at + 2])
            at += 3
            continue
        if opcode in {_OP_TEXTURED_COMBINE, _OP_FLAT_COMBINE}:
            # Two G_SETCOMBINE words: opcode 6 is TEXEL0 * SHADE with the texture's alpha, opcode 7
            # is PRIMITIVE * SHADE forced opaque, which draws no texture at all.
            flat = opcode == _OP_FLAT_COMBINE
            continue
        if opcode in banks:
            # A bank opcode names a record rather than a descriptor, and the loader drops the whole
            # command when the record is out of range, leaving the previous texture bound.
            keys = banks[opcode]
            index = code[at] if at < end else len(keys)
            if index < len(keys):
                texture = keys[index]
            at += 1
            continue
        if opcode == _OP_TRI1:
            if at + flags + 2 <= end:
                word = struct.unpack_from(f'{dialect.endian}H', code, at + flags)[0]
                buffer.triangle(None if flat else texture,
                                _triangle(word),
                                lit=False,
                                tint=primitive if flat else None)
            at += flags + 2
            continue
        if opcode == _OP_TRI2:
            if at + flags + 4 <= end:
                first, second = struct.unpack_from(f'{dialect.endian}2H', code, at + flags)
                buffer.triangle(None if flat else texture,
                                _triangle(first),
                                lit=False,
                                tint=primitive if flat else None)
                buffer.triangle(None if flat else texture,
                                _triangle(second),
                                lit=False,
                                tint=primitive if flat else None)
            at += flags + 4
            continue
        if opcode == _OP_MODIFY_ST:
            # G_MODIFYVTX with G_MWO_POINT_ST: retarget one loaded vertex's texture coordinates at
            # another entry of the t4 table.
            #
            # The loader halves both before writing, which is the game applying its own
            # `gsSPTexture(0x8000, ...)` by hand: this command writes straight into the vertex
            # cache, past the point where the RSP would have scaled a loaded vertex. The table
            # entry is therefore stored here as it stands, and the same scale is applied to every
            # vertex once, when the coordinates are normalised. Halving here as well quartered
            # these corners and left one corner of a wall out of step with the other three.
            if at + 2 <= end:
                slot, entry = code[at], code[at + 1]
                current = buffer.slots[slot] if slot < len(buffer.slots) else None
                if current is not None and entry < len(coords):
                    s, t = coords[entry]
                    buffer.slots[slot] = current._replace(s=s, t=t)
            at += 2
            continue
        if opcode == _OP_NORMALS:
            # Like the vertex opcode, a count followed by that many records: three halfwords each,
            # written into the array `hdr+0x2C` sizes at six bytes apiece.
            at += 1 + (code[at] if at < end else 0) * _NORMAL_BYTES
            continue
        at += dialect.operands.get(opcode, 0)
    return at, DrawState(texture, primitive, flat)


def demo() -> None:
    """
    Check the triangle unpacking against the shifts the loader uses.

    Raises
    ------
    SelfCheckFailed
        If a word unpacks to the wrong corners, or an opcode has no operand length.
    """
    # The loader forms each corner as ((word >> n) & 0x1F) * 2, so the halves must line up.
    for word, expected in ((0x0000, (0, 0, 0)), (0x7FFF, (31, 31, 31)), (0x0421, (1, 1, 1)),
                           ((5 << 10) | (9 << 5) | 17, (5, 9, 17))):
        if _triangle(word) != expected:
            msg = f'Word {word:#06x} unpacked to {_triangle(word)}, expected {expected}.'
            raise SelfCheckFailed(msg)
    # Every opcode the jump table dispatches must have a known operand length, or the stream
    # desynchronises the first time one appears. The two variable-length ones and the triangles are
    # handled in the interpreter rather than the table.
    handled = {_OP_VERTICES, _OP_TRI1, _OP_TRI2, _OP_NORMALS}
    for dialect in (XG1, XG2):
        for opcode in range(1, dialect.max_opcode + 1):
            if opcode not in handled and opcode not in dialect.operands:
                msg = f'Opcode {opcode:#04x} has no operand length in the {dialect} table.'
                raise SelfCheckFailed(msg)
    print('xg1_level: triangle unpacking and operand table hold.')  # ruff: ignore[print]


if __name__ == '__main__':
    demo()


def bank_texture_key(bank: int, index: int) -> int:
    """
    Key a bank texture so it cannot collide with a level pool's pixel offsets.

    Parameters
    ----------
    bank : int
        ROM offset of the bank.
    index : int
        Record number within it.

    Returns
    -------
    int
        A key for :py:attr:`dade.xg2.typing.Texture.offset`.
    """
    return (bank << _BANK_KEY_SHIFT) | index


def read_bank_descriptors(bank: bytes) -> list[tuple[int, int, int]]:
    """
    Read the descriptor table at the front of a decompressed texture bank.

    The loader indexes this table without a count, so its end is taken from the first record that
    cannot describe an image. The palette offset in the header confirms where the table stops being
    read: it equals the end of the last record's pixels.

    Parameters
    ----------
    bank : bytes
        The decompressed bank.

    Returns
    -------
    list[tuple[int, int, int]]
        Each record's pixel offset, width, and height.
    """
    out = []
    at = _BANK_TABLE
    while at + _BANK_RECORD <= len(bank):
        pixels = struct.unpack_from('>I', bank, at)[0]
        width, height = struct.unpack_from('>2H', bank, at + 4)
        if (pixels == 0 or pixels >= len(bank) or not 0 < width <= _MAX_TEXTURE_SIDE
                or not 0 < height <= _MAX_TEXTURE_SIDE):
            break
        out.append((pixels, width, height))
        at += _BANK_RECORD
    return out


def read_texture_bank(rom: bytes, offset: int) -> list[Texture]:
    """
    Decode a shared texture bank, the source the bytecode's two bank opcodes draw from.

    A bank sits behind its own decompressed size and is LZHUF-compressed. Expanded it is a word
    holding the palette's offset, a word the loader never reads, then eight-byte records of a pixel
    offset, a width, and a height. Every image is eight-bit colour indices against the one 256-entry
    palette the header points at, which sits last and closes the bank exactly -- 33048 plus 512 is
    the global bank's 33560 bytes, and 66080 plus 512 is the largest level bank's 66592.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    offset : int
        ROM offset of the bank.

    Returns
    -------
    list[dade.xg2.typing.Texture]
        The decoded images, in record order and keyed by :py:func:`bank_texture_key`.
    """
    size = struct.unpack_from('>I', rom, offset)[0]
    if not 0 < size < _MAX_BANK_SIZE:
        return []
    try:
        bank = decompress_lzhuf(rom, offset + 4, size)
    except LzhufError:
        log.warning('The texture bank at 0x%X will not decompress.', offset)
        return []
    descriptors = read_bank_descriptors(bank)
    if not descriptors or descriptors[0][0] < _BANK_TABLE + len(descriptors) * _BANK_RECORD:
        return []
    palette_offset = struct.unpack_from('>I', bank, 0)[0]
    pixels_end = max(pixels + width * height for pixels, width, height in descriptors)
    palette = None
    if palette_offset == pixels_end and palette_offset + _TLUT_BYTES <= len(bank):
        palette = read_tlut(bank, palette_offset, _TLUT_ENTRIES)
    out = []
    for index, (pixels, width, height) in enumerate(descriptors):
        if pixels + width * height > len(bank):
            continue
        key = bank_texture_key(offset, index)
        rgba = (decode_ci(bank, pixels, width, height, palette, _CI8_DEPTH, width)
                if palette else decode_i8(bank[pixels:pixels + width * height], width, height))
        out.append(Texture('ci8', key, width, height, rgba))
    return out


def decode_level_textures(rom: bytes, base: int, dialect: Dialect = XG1) -> list[Texture]:
    """
    Decode a level's textures out of its ``r2`` pool.

    Each descriptor names its pixels and its palette as offsets into that pool. Format one is
    eight-bit colour indices against a 256-entry palette, which is what the loader's own tile setup
    assumes and what the sizes bear out.

    Parameters
    ----------
    rom : bytes
        The whole ROM image, original rather than extended.
    base : int
        Offset of the level container.
    dialect : Dialect
        :py:data:`XG1` or :py:data:`XG2`.

    Returns
    -------
    list[dade.xg2.typing.Texture]
        The decoded images, keyed by their pixel offset.
    """
    header = read_header(rom, base, dialect)
    descriptors = read_textures(rom, base, header, dialect)
    out: list[Texture] = [
        texture for offset in _level_banks(rom, base, dialect).values()
        for texture in read_texture_bank(rom, offset)
    ]
    if not descriptors or not header.pixels_size:
        return out
    try:
        pool = decompress_lzhuf(rom, base + header.pixels, header.pixels_size)
    except LzhufError:
        return out
    seen: set[int] = set()
    for entry in descriptors:
        if entry.pixels in seen or entry.pixel_format not in _FORMAT_DEPTH:
            continue
        depth = _FORMAT_DEPTH[entry.pixel_format]
        width, height = entry.width or 1, entry.height or 1
        row_bytes = width * depth // 8
        entries = _TLUT_ENTRIES if depth == _CI8_DEPTH else _CI4_TLUT_ENTRIES
        if entry.pixels + row_bytes * height > len(pool):
            continue
        if entry.palette + entries * 2 > len(pool):
            continue
        # The palette is RGBA5551 halfwords, so it follows the build's byte order. Reading the
        # Windows tracks big-endian swaps every entry and leaves the colours washed out.
        palette = read_tlut(pool, entry.palette, entries, dialect.endian)
        seen.add(entry.pixels)
        out.append(
            Texture('ci8' if depth == _CI8_DEPTH else 'ci4', entry.pixels, width, height,
                    decode_ci(pool, entry.pixels, width, height, palette, depth, row_bytes)))
    return out
