r"""
The ``BSF`` skeleton stored inside Extreme-G XG2's rider models.

The ``BMC`` motion clips in :py:mod:`dade.xg2.bmc` are 67 bare curves that identify the skeleton
they drive (``man2sk.asf``, ``ivask.bsf``, ``albeanosk.bs``), and that skeleton has no separate
file. It is a region *inside* each rider model. Searching the archives for a ``.asf`` therefore
finds nothing. ``bulk/data/iva.cmp`` and its siblings are single-entry ``XG2Arch`` containers whose
decompressed payload stores it.

A rider's header is eight segment-five pointers, relocated at load time by masking each with
``0xFFFFFF`` and adding the buffer base; the Windows build's loader does this at ``0x004A3142`` and
finishes with a ``gsSPSegment(5, buffer)``. The seventh of them, at ``+0x18``, is the skeleton.

The region is a header and one record per bone, both :py:data:`BONE_RECORD_SIZE` bytes, and the
bones' names follow immediately as NUL-terminated strings in the same order:

* header: the magic ``BSF\x80``, the bone count, the root's degrees of freedom, a byte counting
  the root's channel codes, those codes, the root's basis at ``+0x10``, and its pivot at ``+0x24``;
* bone: a signed parent index with ``-1`` for the root, a byte of degrees of freedom, a byte
  counting the channel codes that follow, then those codes, then a basis at ``+0x08``, then a pivot
  at ``+0x1C``, then the rest of the record, not decoded yet.

A basis is a rotation in 4.12 fixed point whose columns are the axes the bone turns about. A pivot
is the point it turns about, three 28.4 fixed-point values in the model's bind space, the space the
rider's vertices are stored in. Both readings are those of the game's pose builder
(``BuildAnimationPoseTransforms``, ``0x800B08A0`` in the N64 build), and the data bears them out.
Left and right mirror precisely, ``lhumerus``'s basis opening ``(-63, -4050, -603)`` against
``rhumerus``'s ``(-63, 4050, 604)``, and the pivots step down the leg from the hip at the origin to
the knee at a height of -4905 and the ankle at -9624.

Multi-byte fields are big-endian even in the Windows build, though the eight header pointers that
lead here are little-endian.

**The decisive count.** The root's six degrees of freedom plus the bones' sixty-one make 67,
exactly how many curves every clip includes. The per-bone counts are read from the file rather
than fitted, and the total is therefore the check that the layout is right. It also rules out
a hand-written table. The hip joints turn out to have no degrees of freedom at all, and
``lshoulderj`` and ``lacromial`` both hang off ``thorax`` rather than forming an arm chain.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import logging
import struct

from dade.common.exceptions import SelfCheckFailed

if TYPE_CHECKING:
    from .typing import Basis, Vector

__all__ = ('BONE_RECORD_SIZE', 'SKELETON_MAGIC', 'SKELETON_POINTER', 'Bone', 'Skeleton',
           'parse_skeleton')

log = logging.getLogger(__name__)

SKELETON_MAGIC = b'BSF\x80'
"""Magic introducing the skeleton region.

:meta hide-value:
"""
BONE_RECORD_SIZE = 80
"""Bytes per bone, and per the header that precedes them.

:meta hide-value:
"""
SKELETON_POINTER = 0x18
"""Header offset of the segment pointer naming the skeleton region.

:meta hide-value:
"""
_HEADER_POINTERS = 8
_SEGMENT_MASK = 0xFFFFFF
_MAX_BONES = 256
_NAME_END = 0
_FIXED_ONE = 4096.0
_PIVOT_ONE = 16.0
_MAX_BONE_CODES = 4
_MAX_ROOT_CODES = 7
_BONE_BASIS = 0x08
_BONE_PIVOT = 0x1C
_ROOT_BASIS = 0x10
_ROOT_PIVOT = 0x24
_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_DEMO_BONES = 27
_DEMO_CHANNELS = 67


class Bone(NamedTuple):
    """One joint of a rider's skeleton."""

    name: str
    """Name as stored after the records, such as ``lfemur``."""
    parent: int
    """Index of the parent bone, or ``-1`` for a child of the root."""
    dof: int
    """Degrees of freedom the motion clips drive, zero for a joint that only offsets its child."""
    channel: int
    """Index of this bone's first curve within a clip's 67."""
    axes: tuple[int, ...]
    """The channel codes, identifying what each of the bone's curves drives, in curve order.

    The game's pose decoder (``DecodePackedAnimationPose``, ``0x800AF62C`` in the N64 build) reads
    ``0`` to ``2`` as a translation along X, Y, or Z, ``3`` to ``5`` as a turn about the first,
    second, or third column of :py:attr:`basis`, ``7`` and ``8`` as three translations ordered X Y Z
    and Z Y X, and ``9`` and ``10`` as three turns ordered first, second, third and third, second,
    first. Every rider has ``10`` on all seventeen three-degree joints, ``3`` on the knees and
    elbows, ``4`` on the wrists, and ``5`` then ``3`` on the fingers. The knee's first column is
    the lateral axis, the one a knee bends about.
    """
    basis: Basis
    """The rotation whose columns are the axes the bone turns about, as rows."""
    pivot: Vector
    """The point the bone turns about, in the model's bind space and in vertex units."""


class Skeleton(NamedTuple):
    """A rider's whole skeleton."""

    root_dof: int
    """Degrees of freedom of the root, placed by the clips before any bone's."""
    bones: list[Bone]
    """The joints, in the order their curves appear."""
    root_axes: tuple[int, ...] = ()
    """The root's channel codes, read as :py:attr:`Bone.axes` is."""
    root_basis: Basis = _IDENTITY
    """The root's basis, read as :py:attr:`Bone.basis` is."""
    root_pivot: Vector = (0.0, 0.0, 0.0)
    """The root's pivot, read as :py:attr:`Bone.pivot` is."""
    @property
    def channels(self) -> int:
        """
        Total curves a clip needs to drive this skeleton.

        Returns
        -------
        int
            The root's degrees of freedom plus every bone's.
        """
        return self.root_dof + sum(bone.dof for bone in self.bones)


def _names(data: bytes, at: int, count: int) -> list[str]:
    """
    Read *count* NUL-terminated names.

    Parameters
    ----------
    data : bytes
        The decompressed rider.
    at : int
        Offset of the first name.
    count : int
        How many to read.

    Returns
    -------
    list[str]
        The names, empty when the block runs out early.
    """
    out = []
    for _ in range(count):
        end = data.find(bytes([_NAME_END]), at)
        if end < 0:
            return []
        out.append(data[at:end].decode('ascii', 'replace'))
        at = end + 1
    return out


def parse_skeleton(model: bytes) -> Skeleton | None:
    """
    Read the skeleton out of a decompressed rider model.

    Parameters
    ----------
    model : bytes
        The rider's decompressed payload, as
        :py:func:`dade.xg2.archive.decode_entries` yields it.

    Returns
    -------
    Skeleton | None
        The skeleton, or :py:obj:`None` when the model includes none.
    """
    if len(model) < _HEADER_POINTERS * 4:
        return None
    # The header's pointers store the segment number in the top byte, and their byte order follows
    # the build, little-endian on Windows and big-endian on the N64. Both are tried and the magic
    # settles which is right, rather than the caller having to specify it.
    start = 0
    for endian in ('<', '>'):
        candidate = struct.unpack_from(f'{endian}I', model, SKELETON_POINTER)[0] & _SEGMENT_MASK
        if (candidate + BONE_RECORD_SIZE <= len(model)
                and model[candidate:candidate + 4] == SKELETON_MAGIC):
            start = candidate
            break
    else:
        return None

    count, root_dof = struct.unpack_from('>2H', model, start + 4)
    if not 0 < count < _MAX_BONES:
        return None
    records = start + BONE_RECORD_SIZE
    if records + count * BONE_RECORD_SIZE > len(model):
        return None

    names = _names(model, records + count * BONE_RECORD_SIZE, count)
    if len(names) != count:
        log.warning('The skeleton at 0x%X names %d bones but only some are readable.', start, count)
        return None

    bones, channel = [], root_dof
    for index in range(count):
        at = records + index * BONE_RECORD_SIZE
        parent = struct.unpack_from('>h', model, at)[0]
        dof = model[at + 2]
        axes = tuple(model[at + 4:at + 4 + min(model[at + 3], _MAX_BONE_CODES)])
        bones.append(
            Bone(names[index], parent, dof, channel, axes, _basis(model, at + _BONE_BASIS),
                 _pivot(model, at + _BONE_PIVOT)))
        channel += dof
    root_axes = tuple(model[start + 9:start + 9 + min(model[start + 8], _MAX_ROOT_CODES)])
    return Skeleton(root_dof, bones, root_axes, _basis(model, start + _ROOT_BASIS),
                    _pivot(model, start + _ROOT_PIVOT))


def _basis(model: bytes, at: int) -> Basis:
    """
    Read a 4.12 fixed-point rotation, stored row by row.

    Parameters
    ----------
    model : bytes
        The decompressed rider.
    at : int
        Offset of the rotation.

    Returns
    -------
    dade.xg2.typing.Basis
        The rows.
    """
    v = [value / _FIXED_ONE for value in struct.unpack_from('>9h', model, at)]
    return (v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])


def _pivot(model: bytes, at: int) -> Vector:
    """
    Read a 28.4 fixed-point point.

    Parameters
    ----------
    model : bytes
        The decompressed rider.
    at : int
        Offset of the point.

    Returns
    -------
    dade.xg2.typing.Vector
        The point in vertex units.
    """
    x, y, z = (value / _PIVOT_ONE for value in struct.unpack_from('>3i', model, at))
    return x, y, z


def demo() -> None:
    """
    Check the reader against a rider from the Windows port, if one is to hand.

    Raises
    ------
    SelfCheckFailed
        If the rider's skeleton does not match what every rider is known to have.
    """
    from pathlib import Path  # ruff: ignore[import-outside-top-level]

    from .archive import decode_entries, parse_archive  # ruff: ignore[import-outside-top-level]

    path = Path('/home/tatsh/dev/extreme-g-noclip/xg2-pc/data1/BULK/DATA/Iva.cmp')
    if not path.is_file():
        print(f'{path} is not here; nothing to check against.')  # ruff: ignore[print]
        return
    data = path.read_bytes()
    model = next(iter(decode_entries(data, parse_archive(data, 0, '<'))))[1]
    skeleton = parse_skeleton(model)
    if skeleton is None:
        msg = 'The rider model includes no skeleton.'
        raise SelfCheckFailed(msg)
    if len(skeleton.bones) != _DEMO_BONES:
        msg = f'Skeleton has {len(skeleton.bones)} bones, expected {_DEMO_BONES}.'
        raise SelfCheckFailed(msg)
    # The clips have 67 curves each, and that is what makes this the right reading.
    if skeleton.channels != _DEMO_CHANNELS:
        msg = f'Skeleton has {skeleton.channels} channels, expected {_DEMO_CHANNELS}.'
        raise SelfCheckFailed(msg)
    if skeleton.bones[0].name != 'lhipjoint':
        msg = f'First bone is {skeleton.bones[0].name!r}, expected lhipjoint.'
        raise SelfCheckFailed(msg)
    if skeleton.bones[0].dof != 0:
        msg = f'Hip joint has {skeleton.bones[0].dof} degrees of freedom, expected none.'
        raise SelfCheckFailed(msg)
    print(f'{len(skeleton.bones)} bones, {skeleton.channels} channels.')  # ruff: ignore[print]


if __name__ == '__main__':
    demo()
