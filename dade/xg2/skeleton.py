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

The region is a header and one record per bone, both :py:data:`RECORD_SIZE` bytes, and the bones'
names follow immediately as NUL-terminated strings in the same order:

* header: the magic ``BSF\x80``, the bone count, and the root's degrees of freedom;
* bone: a signed parent index with ``-1`` for the root, a byte of degrees of freedom, a byte
  counting the axis codes that follow, then those codes, then a unit direction vector in 4.12 fixed
  point, then the rest of the record, not decoded yet.

The direction is the axis the bone extends along, exactly as an Acclaim skeleton stores it, and it
reads as a unit vector on every one of the 27 bones. Left and right mirror precisely, ``lhumerus``
being ``(-63, -4050, -603)`` against ``rhumerus``'s ``(-63, 4050, 604)``. That mirroring confirms
the field rather than its magnitude alone.

Multi-byte fields are big-endian even in the Windows build, though the eight header pointers that
lead here are little-endian.

**The decisive count.** The root's six degrees of freedom plus the bones' sixty-one make 67,
exactly how many curves every clip includes. Nothing was fitted to arrive at that, the per-bone
counts
being read from the file, and it is therefore the check that the layout is right. It also rules out
a hand-written table. The hip joints turn out to have no degrees of freedom at all, and
``lshoulderj`` and ``lacromial`` both hang off ``thorax`` rather than forming an arm chain.
"""
from __future__ import annotations

from typing import NamedTuple
import logging
import struct

from dade.common.exceptions import SelfCheckFailed

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
_MAX_AXES = 3
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
    direction: tuple[float, float, float]
    """Unit vector the bone extends along, from 4.12 fixed point."""
    axes: tuple[int, ...]
    """The skeleton's codes for which axes this joint turns about.

    Observed across every rider: ``0x0A`` on all seventeen three-degree joints, ``0x03`` and
    ``0x04`` on the one-degree ones, and ``lfingers`` with two codes, ``0x05`` and ``0x03``, for
    its two degrees. What each code means as an axis is **not** established. Acclaim skeletons
    usually order a three-degree joint ``rz ry rx``, but that is an assumption until it is checked
    against a clip.
    """


class Skeleton(NamedTuple):
    """A rider's whole skeleton."""

    root_dof: int
    """Degrees of freedom of the root, placed by the clips before any bone's."""
    bones: list[Bone]
    """The joints, in the order their curves appear."""
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
    # settles which is right, rather than the caller having to state it.
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
        axes = tuple(model[at + 4:at + 4 + min(model[at + 3], _MAX_AXES)])
        direction = tuple(v / _FIXED_ONE for v in struct.unpack_from('>3h', model, at + 8))
        bones.append(Bone(names[index], parent, dof, channel, direction, axes))
        channel += dof
    return Skeleton(root_dof, bones)


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
