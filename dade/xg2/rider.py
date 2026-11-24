r"""
The skinned mesh of an Extreme-G XG2 rider.

A rider is a flat model whose eight header pointers each identify a region, in this order:

* the display list;
* the number of vertices it draws;
* for each of those, the index of the bind position it is skinned from;
* the bind positions, three 16-bit values each;
* for each drawn vertex, its texture coordinates, at half the scale the display list samples;
* for each bind position, its normal, three signed bytes;
* the skeleton :py:mod:`dade.xg2.skeleton` reads;
* the skin, magic ``WEM\x85``.

The game skins on the CPU, in ``RenderSceneAnimationResource`` (``0x800AE674`` in the N64 build,
``0x004A3C80`` in the Windows one). It transforms every bind position by the pose of its bone,
writes the results into a vertex buffer, and points segment 8 at that buffer before calling the
display list. The geometry therefore exists only at run time. Without the skin, a converter finds
no vertices at all.

The skin is a run of groups, one per bone:
``[u16 rigid count][u16 blend count][s16 bone][u16 first rigid position]``, then one
``[u16 position][u16 weight]`` pair per blended position. A group moves its rigid range by its
bone alone. Each blend then mixes the bone's transform of a position into the position already
computed, ``(bone * (0x10000 - weight) + previous * weight) >> 16``. That is linear blend
skinning, and it maps onto glTF's joint weights exactly.

Positions are stored in the bind pose in model space, not relative to their bone. A bone's pose is
the identity at rest, and the rest pose is therefore the bind pose. On the first N64 rider, the
shin's positions centre at a height of -7506, below the knee pivot at -4905. The knee pivot in turn
sits below the hip at zero.

Only the N64 build is read. The Windows port stores the same regions, little-endian except for the
skeleton and the skin, but its display lists use opcodes (``0xA7``, ``0xAD``, ``0xAE``, and
F3DEX's ``G_TRI1``) that :py:func:`dade.xg2.f3dex2.parse_pc_display_lists` does not decode yet.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import math
import struct

from .f3dex2 import parse_display_lists
from .skeleton import parse_skeleton

if TYPE_CHECKING:
    from .f3dex2 import Mesh
    from .skeleton import Skeleton

__all__ = ('MAX_INFLUENCES', 'SKIN_MAGIC', 'Rider', 'parse_rider')

log = logging.getLogger(__name__)

SKIN_MAGIC = b'WEM\x85'
"""Magic introducing a rider's skin.

:meta hide-value:
"""
MAX_INFLUENCES = 4
"""Joints a vertex is weighted to at most, the four glTF's ``JOINTS_0`` stores.

:meta hide-value:
"""
_POINTERS = 8
_SEGMENT_MASK = 0xFFFFFF
_SKIN_HEADER = 8
_GROUP_SIZE = 8
_BLEND_SIZE = 4
_BLEND_ONE = 0x10000
_VERTEX_SIZE = 16
_NORMAL_UNIT = 127
# The bind position's index is passed through the display-list parser in the vertex's alpha byte.
# Riders draw lit, and the parser reads the colour bytes as a normal, not as colour.
_MAX_POSITIONS = 0x100
_NO_POSITION = 0xFFFF


class Rider(NamedTuple):
    """A rider's skinned geometry and the skeleton that drives it."""

    meshes: list[Mesh]
    """The triangles, one mesh per image, positioned in the bind pose."""
    weights: list[list[tuple[tuple[int, ...], tuple[float, ...]]]]
    """For each mesh vertex, :py:data:`MAX_INFLUENCES` joints and the weight of each.

    Joint 0 is the skeleton's root and joint *n* is bone *n - 1*. An unused slot has joint 0 and
    a weight of zero.
    """
    skeleton: Skeleton
    """The skeleton the joints belong to."""


def _skin(model: bytes, at: int, count: int, bones: int) -> list[dict[int, float]] | None:
    """
    Read the weights the skin gives each bind position.

    Parameters
    ----------
    model : bytes
        The rider.
    at : int
        Offset of the skin.
    count : int
        Number of bind positions.
    bones : int
        Number of bones in the skeleton.

    Returns
    -------
    list[dict[int, float]] | None
        Per position, its weight on each joint, or :py:obj:`None` when the skin is malformed or
        identifies a bone the skeleton lacks. A position outside every group is given wholly to
        the root.
    """
    if model[at:at + 4] != SKIN_MAGIC or at + _SKIN_HEADER > len(model):
        return None
    weights: list[dict[int, float]] = [{0: 1.0} for _ in range(count)]
    groups = struct.unpack_from('>h', model, at + 6)[0]
    at += _SKIN_HEADER
    for _ in range(groups):
        if at + _GROUP_SIZE > len(model):
            return None
        rigid, blends, bone, first = struct.unpack_from('>HHhH', model, at)
        at += _GROUP_SIZE
        if not 0 <= bone < bones:
            return None
        joint = bone + 1
        if first != _NO_POSITION:
            for position in range(first, min(first + rigid, count)):
                weights[position] = {joint: 1.0}
        if at + blends * _BLEND_SIZE > len(model):
            return None
        for position, weight in struct.iter_unpack('>2H', model[at:at + blends * _BLEND_SIZE]):
            if position < count:
                kept = weight / _BLEND_ONE
                mixed = {key: value * kept for key, value in weights[position].items()}
                mixed[joint] = mixed.get(joint, 0.0) + 1.0 - kept
                weights[position] = mixed
        at += blends * _BLEND_SIZE
    return weights


def _influences(weights: dict[int, float]) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """
    Reduce a position's weights to the strongest :py:data:`MAX_INFLUENCES`, summing to one.

    Parameters
    ----------
    weights : dict[int, float]
        Weight per joint.

    Returns
    -------
    tuple[tuple[int, ...], tuple[float, ...]]
        The joints and their weights, padded with joint 0 at weight zero.
    """
    # ponytail: drops all but the four strongest influences; the shipped riders blend two at most.
    strongest = sorted(weights.items(), key=lambda item: -item[1])[:MAX_INFLUENCES]
    total = sum(weight for _, weight in strongest) or 1.0
    padding = MAX_INFLUENCES - len(strongest)
    return (tuple(joint for joint, _ in strongest) + (0,) * padding,
            tuple(weight / total for _, weight in strongest) + (0.0,) * padding)


def _normal(model: bytes, at: int) -> tuple[int, int, int]:
    """
    Read a bind normal and pack it as the display list's lit vertices store one.

    The game swaps the second and third components and negates the new second
    (``(x, -z, y)``), then negates the whole normal as it writes the vertex, a sign its lighting
    expects. The last negation is not applied here. Without it, all but 14 of the first rider's
    337 vertex normals point away from the centre of their body part and agree with the triangles'
    counter-clockwise winding, the outward normals glTF expects.

    Parameters
    ----------
    model : bytes
        The rider.
    at : int
        Offset of the normal.

    Returns
    -------
    tuple[int, int, int]
        The unit normal scaled to 127, as three bytes in two's complement.
    """
    x, y, z = struct.unpack_from('3b', model, at)
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    return ((round(x / length * _NORMAL_UNIT) & 0xFF), (round(-z / length * _NORMAL_UNIT) & 0xFF),
            (round(y / length * _NORMAL_UNIT) & 0xFF))


def _fits(model: bytes, *regions: tuple[int, int]) -> bool:
    """
    Report whether every ``(offset, size)`` region lies inside the model.

    Parameters
    ----------
    model : bytes
        The rider.
    *regions : tuple[int, int]
        Each region's offset and size.

    Returns
    -------
    bool
        Whether all of them do.
    """
    return all(offset + size <= len(model) for offset, size in regions)


def parse_rider(model: bytes) -> Rider | None:
    """
    Read an N64 rider's mesh in its bind pose, and the joint weights of every vertex.

    Parameters
    ----------
    model : bytes
        A decompressed rider model from the N64 build.

    Returns
    -------
    Rider | None
        The rider, or :py:obj:`None` when *model* has no skeleton, no skin, or regions that do
        not fit.
    """
    if (skeleton := parse_skeleton(model)) is None:
        return None
    draw, counted, mapping, positions, coords, normals, _, skin = (
        pointer & _SEGMENT_MASK for pointer in struct.unpack_from(f'>{_POINTERS}I', model, 0))
    count = struct.unpack_from('>i', model, counted)[0] if _fits(model, (counted, 4)) else 0
    if count <= 0 or not _fits(model, (mapping, count * 2), (coords, count * 4)):
        log.warning('The rider draws %d vertices, beyond what the model stores.', count)
        return None
    indices = struct.unpack_from(f'>{count}H', model, mapping)
    total = max(indices) + 1
    if total > _MAX_POSITIONS or not _fits(model, (positions, total * 6), (normals, total * 3)):
        log.warning('The rider indexes %d bind positions, beyond what the model stores.', total)
        return None
    if (weights := _skin(model, skin, total, len(skeleton.bones))) is None:
        log.warning('The rider at 0x%X has no readable skin.', skin)
        return None
    bank = bytearray()
    for vertex, index in enumerate(indices):
        x, y, z = struct.unpack_from('>3h', model, positions + index * 6)
        # The coordinates are doubled into sixteen bits, wrapping as they do on the console.
        s, t = ((v * 2 + 0x8000) % 0x10000 - 0x8000
                for v in struct.unpack_from('>2h', model, coords + vertex * 4))
        bank += struct.pack('>3hH2h4B', x, y, z, 0, s, t, *_normal(model, normals + index * 3),
                            index)
    meshes = parse_display_lists(model, '>', bytes(bank), (draw,))
    reduced = [_influences(entry) for entry in weights]
    return Rider([
        mesh._replace(vertices=[v._replace(alpha=0xFF) for v in mesh.vertices]) for mesh in meshes
    ], [[reduced[v.alpha] for v in mesh.vertices] for mesh in meshes], skeleton)
