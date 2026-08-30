"""
Export the geometry in ``.EGP2`` and ``.SGP2`` blobs to Wavefront OBJ and MTL.

A blob holds an array of mesh pointers. Each pointer addresses a small block of
``[u32 index][u32 data_offset][u32 quadword_count]``, and that block sits immediately after the
vertex data it describes, so ``data_offset + quadword_count * 16`` equals the block's own address.

Inside a mesh the data is a run of packets. A packet begins with two float4 rows forming its
bounding box (both with ``w`` exactly ``1.0``), then a GIFtag, then 80-byte groups holding four
vertices each: four ``[u, v, x, y]`` rows followed by one row carrying the four ``z`` values. The
low byte of each float in a vertex row carries an RGBA vertex colour, and the fourth low byte is
always ``0x80`` because PlayStation 2 alpha is on a ``0..128`` scale.

The GIFtag is what the hardware itself would have consumed, so it settles how to triangulate: its
NLOOP field is the vertex count and its PRIM field says whether the packet is an independent
triangle list or a strip. Its ``NREG``/``REGS`` fields name the per-vertex registers as ST, RGBAQ,
and XYZ2, matching the decoded layout.

Materials are 84-byte records naming a texture and pointing at its image record. Each material also
owns a run of draw lists that name the meshes drawn with it.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import TYPE_CHECKING, NamedTuple
import logging
import struct

from dade.common.obj import encode_obj

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

__all__ = ('GROUP_SIZE', 'TRIANGLE_LIST', 'TRIANGLE_STRIP', 'Material', 'Mesh', 'MeshPacket',
           'Vertex', 'read_materials', 'read_meshes', 'to_mtl', 'to_obj', 'triangles',
           'write_model')

log = logging.getLogger(__name__)

GROUP_SIZE = 80
"""Size in bytes of one vertex group, which holds four vertices.

:meta hide-value:
"""

_QUADWORD = 16
_MESH_TABLE_AT = 0x64
_MESH_COUNT_AT = 0x20
_MATERIAL_TABLE_AT = 0x50
_MATERIAL_COUNT_AT = 0x14
_STRING_TABLE_AT = 0x54
_MATERIAL_SIZE = 84
_MATERIAL_TEXTURE_AT = 0x10
_MATERIAL_MESHES_AT = 0x58
_PASS_SIZE = 8
_OPAQUE_ALPHA = 0x80
_NLOOP_MASK = 0x7FFF
_PRIM_SHIFT = 47
TRIANGLE_LIST = 3
"""GIFtag PRIM value for an independent triangle list.

:meta hide-value:
"""
TRIANGLE_STRIP = 4
"""GIFtag PRIM value for a triangle strip.

:meta hide-value:
"""
_PREAMBLE_QUADWORDS = 3
_BOX_W = 1.0
_MIN_BOX_EXTENT = 0.001
_TRIANGLE_CORNERS = 3


class Vertex(NamedTuple):
    """One decoded vertex."""

    x: float
    """Position along the X axis."""
    y: float
    """Position along the Y axis."""
    z: float
    """Position along the Z axis."""
    u: float
    """Texture coordinate along U."""
    v: float
    """Texture coordinate along V, in the stored bottom-up orientation."""
    red: int
    """Red channel of the packed vertex colour."""
    green: int
    """Green channel of the packed vertex colour."""
    blue: int
    """Blue channel of the packed vertex colour."""


class MeshPacket(NamedTuple):
    """One draw packet within a mesh."""

    bbox_min: tuple[float, float, float]
    """Lower corner of the packet's bounding box."""
    bbox_max: tuple[float, float, float]
    """Upper corner of the packet's bounding box."""
    vertices: tuple[Vertex, ...]
    """Vertices in the order the packet lists them."""
    primitive: int
    """GS primitive type from the packet's GIFtag: ``3`` is a triangle list, ``4`` a strip."""


class Mesh(NamedTuple):
    """One mesh listed in a geometry blob's mesh table."""

    number: int
    """Index recorded in the mesh's own block."""
    packets: tuple[MeshPacket, ...]
    """Packets making up the mesh."""
    material: int
    """Index of the material this mesh uses, or ``-1`` when no material claims it."""


class Material(NamedTuple):
    """One material defined by a geometry blob."""

    name: str
    """Source texture path, such as ``data/levels/poker_bing/wainscot.tga``."""
    texture_offset: int
    """Byte offset of the material's image record, or ``0`` when it has none."""


def _read_string(data: bytes, at: int) -> str:
    end = data.index(b'\0', at)
    return data[at:end].decode('ascii', 'replace')


def read_materials(data: bytes) -> tuple[Material, ...]:
    """
    Read a geometry blob's material table.

    Parameters
    ----------
    data : bytes
        The whole ``.EGP2`` or ``.SGP2`` blob.

    Returns
    -------
    tuple[Material, ...]
        One entry per material, in table order.
    """
    table, count = (struct.unpack_from('<I', data, at)[0]
                    for at in (_MATERIAL_TABLE_AT, _MATERIAL_COUNT_AT))
    strings = struct.unpack_from('<I', data, _STRING_TABLE_AT)[0]
    materials = []
    for i in range(count):
        record = table + i * _MATERIAL_SIZE
        if record + _MATERIAL_SIZE > len(data):
            break
        name_offset, = struct.unpack_from('<I', data, record)
        texture, = struct.unpack_from('<I', data, record + _MATERIAL_TEXTURE_AT)
        at = strings + name_offset
        materials.append(
            Material(_read_string(data, at) if at < len(data) else f'material_{i}', texture))
    return tuple(materials)


def _read_packets(data: bytes, start: int, quadwords: int) -> Iterator[MeshPacket]:
    """
    Yield the packets stored between *start* and *start + quadwords * 16*.

    A packet is located by its bounding box, two consecutive rows whose ``w`` is exactly ``1.0``.
    The row after them is the packet's GIFtag: its NLOOP field gives the exact vertex count and its
    PRIM field gives the primitive type, so the groups are read by count and triangulated according
    to what the hardware would have drawn.

    Parameters
    ----------
    data : bytes
        The whole geometry blob.
    start : int
        Byte offset of the mesh's vertex data.
    quadwords : int
        Length of that data in 16-byte quadwords.

    Yields
    ------
    MeshPacket
        One packet per bounding box found.
    """
    i = 0
    while i + _PREAMBLE_QUADWORDS < quadwords:
        at = start + i * _QUADWORD
        low = struct.unpack_from('<4f', data, at)
        high = struct.unpack_from('<4f', data, at + _QUADWORD)
        # The marker words are stored as exactly 1.0, so an exact comparison identifies them.
        if not (low[3] == _BOX_W and high[3] == _BOX_W and all(low[j] <= high[j] for j in range(3))
                and any(high[j] - low[j] > _MIN_BOX_EXTENT for j in range(3))):
            i += 1
            continue
        first, second = struct.unpack_from('<2I', data, at + 2 * _QUADWORD)
        tag = first | (second << 32)
        count = tag & _NLOOP_MASK
        primitive = (tag >> _PRIM_SHIFT) & 7
        groups = (count + 3) // 4
        body = i + _PREAMBLE_QUADWORDS
        if not count or body + groups * 5 > quadwords:
            i += 1
            continue
        vertices: list[Vertex] = []
        for g in range(groups):
            group = start + (body + g * 5) * _QUADWORD
            zs = struct.unpack_from('<4f', data, group + 4 * _QUADWORD)
            for k in range(4):
                if len(vertices) == count:
                    break
                row = group + k * _QUADWORD
                u, v, x, y = struct.unpack_from('<4f', data, row)
                vertices.append(Vertex(x, y, zs[k], u, v, data[row], data[row + 4], data[row + 8]))
        yield MeshPacket(low[:3], high[:3], tuple(vertices), primitive)
        i = body + groups * 5


def read_meshes(data: bytes) -> tuple[Mesh, ...]:
    """
    Read every mesh in a geometry blob.

    Meshes are enumerated from the materials' draw lists rather than from the mesh table at header
    word ``0x64``. That table holds only about half of them; the draw lists reference every mesh the
    level actually draws, and each reference also names the material to use. Any table entry the
    lists happen to miss is still included.

    Meshes whose block arithmetic does not close are skipped and logged rather than raising, since a
    blob may list slots it does not use.

    Parameters
    ----------
    data : bytes
        The whole ``.EGP2`` or ``.SGP2`` blob.

    Returns
    -------
    tuple[Mesh, ...]
        One entry per mesh that decoded, in address order.
    """
    table, count = (struct.unpack_from('<I', data, at)[0]
                    for at in (_MESH_TABLE_AT, _MESH_COUNT_AT))
    by_block = _material_by_mesh(data)
    blocks = set(by_block)
    for i in range(count):
        block, = struct.unpack_from('<I', data, table + i * 4)
        if block:
            blocks.add(block)
    meshes = []
    for block in sorted(blocks):
        if block + 12 > len(data):
            continue
        number, start, quadwords = struct.unpack_from('<3I', data, block)
        if start + quadwords * _QUADWORD != block:
            log.warning('The block at 0x%x does not follow its own data.', block)
            continue
        if packets := tuple(_read_packets(data, start, quadwords)):
            meshes.append(Mesh(number, packets, by_block.get(block, -1)))
    return tuple(meshes)


def _material_by_mesh(data: bytes) -> dict[int, int]:
    """
    Map each mesh block address to the material that claims it.

    The table at header word ``0x58`` holds one 16-byte record per material. Its first word is the
    material index and its third points at that material's draw lists. The indices are not simply
    the records' positions: some are skipped, so the stored index has to be used or every material
    after a gap is read with the wrong texture.

    A descriptor is a run of eight-byte ``(count, start)`` pairs, one per render pass, and ``start``
    addresses eight-byte entries in the mesh pointer array.

    The pairs chain: each pass begins where the previous one ended, and the last pass of a material
    ends where the next material's first pass begins, so the mesh entries form a single contiguous
    array partitioned between materials. How many passes a material has varies, so a descriptor is
    read up to the next descriptor rather than for a fixed length.

    Parameters
    ----------
    data : bytes
        The whole geometry blob.

    Returns
    -------
    dict[int, int]
        Mesh block address to material index.
    """
    table, count, meshes = (struct.unpack_from('<I', data, at)[0]
                            for at in (_MATERIAL_MESHES_AT, _MATERIAL_COUNT_AT, _MESH_COUNT_AT))
    entries = []
    for i in range(count):
        record = table + i * 16
        if record + 16 > len(data):
            break
        material, _pad, pointer = struct.unpack_from('<3I', data, record)
        entries.append((material, pointer))
    ordered = sorted({p for _m, p in entries if p})
    out: dict[int, int] = {}
    for i, pointer in entries:
        if not pointer:
            continue
        after = bisect_right(ordered, pointer)
        end = min(ordered[after], len(data)) if after < len(ordered) else min(
            pointer + _PASS_SIZE * 16, len(data))
        for at in range(pointer, end - 7, _PASS_SIZE):
            owned, start = struct.unpack_from('<2I', data, at)
            if owned > meshes or start + owned * 8 > len(data):
                break
            for k in range(owned):
                out.setdefault(struct.unpack_from('<I', data, start + k * 8)[0], i)
    return out


def triangles(count: int, primitive: int) -> Iterator[tuple[int, int, int]]:
    """
    Yield triangle indices for a packet's vertices.

    A strip alternates winding as it advances; a list takes each successive group of three and
    discards a trailing remainder.

    Parameters
    ----------
    count : int
        Number of vertices in the packet.
    primitive : int
        GS primitive type, ``3`` for a triangle list or ``4`` for a strip.

    Yields
    ------
    tuple[int, int, int]
        Zero-based indices into the packet.
    """
    if primitive == TRIANGLE_LIST:
        for i in range(0, count - 2, 3):
            yield (i, i + 1, i + 2)
        return
    for i in range(count - 2):
        yield (i, i + 2, i + 1) if i % 2 else (i, i + 1, i + 2)


def to_obj(meshes: Sequence[Mesh], *, material_library: str | None = None) -> str:
    """
    Encode decoded meshes as Wavefront OBJ text.

    Degenerate strip triangles, which the cooker inserts to stitch strips together, are dropped.
    The V coordinate is flipped so it matches the PNGs written by
    :py:func:`dade.sopranos.texture.convert_geometry`, which are stored top-down.

    Parameters
    ----------
    meshes : Sequence[Mesh]
        Meshes to encode.
    material_library : str | None
        Name emitted in an ``mtllib`` line, if given.

    Returns
    -------
    str
        The OBJ text.
    """
    positions: list[tuple[float, float, float]] = []
    texcoords: list[tuple[float, float]] = []
    faces: list[tuple[int, int, int]] = []
    header = [f'mtllib {material_library}'] if material_library else []
    for mesh in meshes:
        for packet in mesh.packets:
            base = len(positions)
            positions.extend((v.x, v.y, v.z) for v in packet.vertices)
            texcoords.extend((v.u, 1.0 - v.v) for v in packet.vertices)
            faces.extend(
                (base + a, base + b, base + c)
                for a, b, c in triangles(len(packet.vertices), packet.primitive)
                if len({packet.vertices[a][:3], packet.vertices[b][:3], packet.vertices[c][:3]
                        }) == _TRIANGLE_CORNERS)
    return encode_obj(positions, faces, header=header, texcoords=texcoords)


def to_mtl(materials: Sequence[Material], *, texture_dir: str = '') -> str:
    """
    Encode a material table as Wavefront MTL text.

    Parameters
    ----------
    materials : Sequence[Material]
        Materials to encode.
    texture_dir : str
        Prefix prepended to each ``map_Kd`` path.

    Returns
    -------
    str
        The MTL text.
    """
    lines = []
    for i, material in enumerate(materials):
        stem = material.name.rsplit('/', 1)[-1].rsplit('.', 1)[0] or f'material_{i}'
        lines += [f'newmtl {stem or f"material_{i}"}', 'Kd 1.000 1.000 1.000']
        if material.texture_offset:
            lines.append(f'map_Kd {texture_dir}{stem}.png')
        lines.append('')
    return '\n'.join(lines)


def write_model(path: Path, output_dir: Path) -> tuple[Path, ...]:
    """
    Write the OBJ and MTL for one geometry blob.

    Parameters
    ----------
    path : Path
        The ``.EGP2`` or ``.SGP2`` file to read.
    output_dir : Path
        Directory to write into. It is created if missing.

    Returns
    -------
    tuple[Path, ...]
        The files written, empty when the blob has no decodable geometry.
    """
    data = path.read_bytes()
    if not (meshes := read_meshes(data)):
        return ()
    output_dir.mkdir(parents=True, exist_ok=True)
    obj = output_dir / f'{path.stem}.obj'
    mtl = output_dir / f'{path.stem}.mtl'
    obj.write_text(to_obj(meshes, material_library=mtl.name))
    mtl.write_text(to_mtl(read_materials(data), texture_dir=f'{path.stem}_textures/'))
    return (obj, mtl)
