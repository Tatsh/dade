"""
Character skeletons and motion banks of Monopoly 2008.

Both are big-endian blobs written straight from the engine's in-memory structures, shared byte
for byte by the Xbox 360, PS3, and Wii builds. A 16-byte resource header precedes the blob, and
every pointer inside it is an offset from the start of the blob.

A skeleton (resource type ``0x7892``) lists each bone's parent and inverse bind matrix in
breadth-first order. A motion bank (resource type ``0x694b``) is an EA CCT character bank: a list
of named states, each driving one motion, and the motions themselves in the SKA codec. A bank
records the identifier of the skeleton it animates, and its bones are that skeleton's bones in the
same order.

SKA stores each bone with a 16-bit descriptor selecting how its rotation and translation are
packed. A rotation is constant or per frame, as a quaternion or as Euler angles, either stored
whole or as a base value plus a per-frame correction. Corrections are fixed-point numbers or
variable-length codes from one bit stream per frame. A translation is constant, a float per
frame, or a float base plus an 8-bit or 16-bit correction. The decoding follows
``SKA_ExpandNextBone`` of the Wii build, the only build shipped with symbols.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple
import math
import struct

from dade.common.utils import align_up

__all__ = ('MOTION_TICK_RATE', 'Bank', 'BoneKey', 'Clip', 'Skeleton', 'bank_character',
           'parse_bank', 'parse_skeleton')

MOTION_TICK_RATE = 59.94
"""Ticks per second at which the engine advances an animation tree.

:meta hide-value:
"""

_HEADER = 0x10
_ALIGN = 0x10
_SKA_CODEC = 0
_STATE_NODE = 0x02010000
_MOTION_NODE = 0x16000001
_DEFAULT_TICKS_PER_FRAME = 2.0
_SKA_HEADER_SIZE = 0xD0
_QUATERNION_SCALE = 4096.0
_VLC_QUATERNION_SCALE = 512.0
_TRANSLATION_SCALE = 1024.0
_ANGLE_SCALE = 2 * math.pi / 65536
_VLC_PAYLOAD_BITS = (12, 8, 4, 0)
"""Payload width of a variable-length code, indexed by its 2-bit tag.

:meta hide-value:
"""

_ROT_STATIC_QUATERNION = 0x80
_ROT_STATIC_EULER = 0x01
_ROT_DELTA_QUATERNION = 0x100
_ROT_VLC_EULER = 0x02
_ROT_FRAME_QUATERNION = 0x40
_ROT_VLC_QUATERNION = 0x400
_TRANS_ANIMATED = 0x1C
_TRANS_8BIT = 0x10
_TRANS_16BIT = 0x08
_TRANS_NONE = 0x20
_EULER_AXIS_OF_MODE = {1: 0, 2: 2, 3: 1}
"""Euler angle a single-axis rotation mode corrects.

:meta hide-value:
"""
_TRANSLATION_AXIS_OF_MODE = {1: 0, 2: 1, 3: 2}
"""Translation axis a single-axis translation mode corrects.

:meta hide-value:
"""


class Skeleton(NamedTuple):
    """A character skeleton."""

    character: int
    """Identifier a motion bank records for the skeleton it animates."""
    inverse_binds: tuple[tuple[float, ...], ...]
    """Each bone's inverse bind matrix, 16 floats for row vectors with the translation last."""
    parents: tuple[int, ...]
    """Each bone's parent index, or ``-1`` for a root."""


class BoneKey(NamedTuple):
    """One bone's local transform in one frame."""

    rotation: tuple[float, float, float, float]
    """Rotation quaternion as ``(x, y, z, w)``."""
    translation: tuple[float, float, float] | None
    """Translation, or :py:obj:`None` when the bone retains its bind translation."""


class Clip(NamedTuple):
    """One decoded motion."""

    frame_time: float
    """Seconds between consecutive frames."""
    frames: tuple[tuple[BoneKey, ...], ...]
    """Each frame's transform of every bone."""
    name: str
    """Name of the state playing the motion."""


class Bank(NamedTuple):
    """A decoded motion bank."""

    character: int
    """Identifier of the skeleton the bank animates."""
    clips: tuple[Clip, ...]
    """The bank's motions."""


def _u16(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('>H', data, offset)[0])


def _s16(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('>h', data, offset)[0])


def _u32(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('>I', data, offset)[0])


def parse_skeleton(data: bytes) -> Skeleton:
    """
    Parse a skeleton resource.

    Parameters
    ----------
    data : bytes
        The resource, including its 16-byte header.

    Returns
    -------
    Skeleton
        The skeleton.

    Raises
    ------
    ValueError
        If the bone table does not fit the resource.
    """
    blob = data[_HEADER:]
    record = _u32(blob, 0x1C)
    count = _u32(blob, record + 4)
    links, matrices = _u32(blob, record + 8), _u32(blob, record + 12)
    if count == 0 or matrices + 64 * count > len(blob) or links + 20 * count > len(blob):
        msg = f'Bone table of {count} bones does not fit a {len(data)}-byte skeleton.'
        raise ValueError(msg)
    parents = struct.unpack_from(f'>{count * 5}i', blob, links)[::5]
    inverse = struct.unpack_from(f'>{count * 16}f', blob, matrices)
    return Skeleton(_u32(blob, 8), tuple(inverse[16 * i:16 * i + 16] for i in range(count)),
                    tuple(parents))


class _Layout(NamedTuple):
    """Where each stream of one SKA motion begins."""

    base: int
    frame_floats: int
    frame_rotations: int
    frame_table: int
    masks: int
    masks8: int
    masks16: int
    static_rotations: int
    static_translations: int
    trans8_base: int
    trans8_data: int
    trans16_base: int
    trans16_data: int
    vlc: int


def _layout(blob: bytes, header: int) -> _Layout:
    def groups(count: int, per_word: int) -> int:
        return ((count - 1) // per_word + 1) * 8 if count > 0 else 0

    cursor = align_up(header + _SKA_HEADER_SIZE + _u16(blob, header + 0x1E), _ALIGN)
    masks = cursor
    cursor += groups(_s16(blob, header + 0x2E), 8)
    masks16 = cursor
    cursor += groups(_s16(blob, header + 0x36), 16)
    masks8 = cursor
    cursor += groups(_s16(blob, header + 0x38), 16)
    cursor += groups(_s16(blob, header + 0x40), 16) + _s16(blob, header + 0x54)
    starts = []
    for size in (_u32(blob, header + 4), _u32(blob, header + 0x18), _u32(blob, header + 8),
                 _u16(blob, header + 0x24), _u16(blob, header + 0x26), _u32(
                     blob, header + 0xC), _u16(blob, header + 0x20), _u16(blob, header + 0x22)):
        starts.append(cursor)
        cursor += size
    (static_rotations, base, frame_floats, trans16_data, trans8_data, static_translations,
     trans16_base, trans8_base) = starts
    frame_table = vlc = 0
    if table_size := _u16(blob, header + 0x2A):
        frame_table, vlc = cursor, cursor + table_size
        cursor = vlc + 4 * _u16(blob, header + 0x2C)
    return _Layout(base, frame_floats, cursor, frame_table, masks, masks8, masks16,
                   static_rotations, static_translations, trans8_base, trans8_data, trans16_base,
                   trans16_data, vlc)


class _BitReader:
    """Most significant bit first reader of the variable-length codes of one frame."""
    def __init__(self, data: bytes, offset: int) -> None:
        self._data = data
        self._bit = offset * 8

    def _bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            byte = self._data[self._bit >> 3]
            value = value << 1 | (byte >> (7 - (self._bit & 7))) & 1
            self._bit += 1
        return value

    def code(self) -> int:
        return self._bits(_VLC_PAYLOAD_BITS[self._bits(2)])


def _euler_quaternion(pitch: float, yaw: float, roll: float) -> tuple[float, float, float, float]:
    sa, ca = math.sin(pitch / 2), math.cos(pitch / 2)
    sb, cb = math.sin(yaw / 2), math.cos(yaw / 2)
    sc, cc = math.sin(roll / 2), math.cos(roll / 2)
    return (ca * sb * cc - sa * cb * sc, ca * sb * sc + sa * cb * cc, ca * cb * sc - sa * sb * cc,
            ca * cb * cc + sa * sb * sc)


def _angles_quaternion(angles: tuple[int, ...] | list[int]) -> tuple[float, float, float, float]:
    # The engine passes the second, the third, and the first stored angle, each negated.
    return _euler_quaternion(-_ANGLE_SCALE * angles[1], -_ANGLE_SCALE * angles[2],
                             -_ANGLE_SCALE * angles[0])


def _quaternion(blob: bytes, offset: int) -> list[float]:
    return [v / _QUATERNION_SCALE for v in struct.unpack_from('>4h', blob, offset)]


@dataclass
class _Cursor:
    """Read position in every stream of one frame, advanced bone by bone."""

    base: int
    """Rotation bases a per-frame correction applies to."""
    codes: _BitReader
    """Variable-length codes of the frame."""
    floats: int
    """Per-frame float translations."""
    rotations: int
    """Per-frame quaternions and quaternion corrections."""
    static_rotations: int
    """Constant rotations."""
    static_translations: int
    """Constant translations."""
    corrections: list[int]
    """Per-frame 8-bit and 16-bit translation corrections."""
    translation_bases: list[int]
    """Float bases of 8-bit and 16-bit translations."""
    mask: int = 0
    """Index of the next rotation mode."""
    translation_masks: list[int] = field(default_factory=lambda: [0, 0])
    """Index of the next 8-bit and 16-bit translation mode."""


def _rotation(blob: bytes, layout: _Layout, cursor: _Cursor,
              flags: int) -> tuple[float, ...] | list[float]:
    def nibble() -> int:
        index = cursor.mask
        cursor.mask += 1
        return _u32(blob, layout.masks + 4 * (index >> 3)) >> 4 * (index & 7) & 0xF

    rotation: tuple[float, ...] | list[float] = (0.0, 0.0, 0.0, 1.0)
    if flags & _ROT_STATIC_QUATERNION:
        rotation = _quaternion(blob, cursor.static_rotations)
        cursor.static_rotations += 8
    elif flags & _ROT_STATIC_EULER:
        rotation = _angles_quaternion(struct.unpack_from('>3H', blob, cursor.static_rotations))
        cursor.static_rotations += 6
    elif flags & _ROT_DELTA_QUATERNION:
        rotation = _quaternion(blob, cursor.base)
        bits = nibble()
        for axis in (axis for axis in range(4) if bits >> axis & 1):
            rotation[axis] += _u16(blob, cursor.rotations) / _QUATERNION_SCALE
            cursor.rotations += 2
        cursor.base += 8
    elif flags & _ROT_VLC_EULER:
        angles = list(struct.unpack_from('>3H', blob, cursor.base))
        mode = nibble()
        for axis in (_EULER_AXIS_OF_MODE[mode],) if mode in _EULER_AXIS_OF_MODE else (0, 1, 2):
            angles[axis] -= cursor.codes.code() << 4
        rotation = _angles_quaternion(angles)
        cursor.base += 6
    elif flags & _ROT_FRAME_QUATERNION:
        rotation = _quaternion(blob, cursor.rotations)
        cursor.rotations += 8
        cursor.mask += 1
    elif flags & _ROT_VLC_QUATERNION:
        rotation = _quaternion(blob, cursor.base)
        bits = nibble() or 0xF
        for axis in (axis for axis in range(4) if bits >> axis & 1):
            rotation[axis] += cursor.codes.code() / _VLC_QUATERNION_SCALE
        cursor.base += 8
    return rotation


def _translation(blob: bytes, layout: _Layout, cursor: _Cursor,
                 flags: int) -> tuple[float, ...] | list[float] | None:
    if flags & (_TRANS_8BIT | _TRANS_16BIT):
        wide = int(not flags & _TRANS_8BIT)
        translation = list(struct.unpack_from('>3f', blob, cursor.translation_bases[wide]))
        index = cursor.translation_masks[wide]
        masks = layout.masks16 if wide else layout.masks8
        mode = _u32(blob, masks + 4 * (index >> 4)) >> 2 * (index & 15) & 3
        for axis in ((_TRANSLATION_AXIS_OF_MODE[mode],) if mode in _TRANSLATION_AXIS_OF_MODE else
                     (0, 1, 2)):
            at = cursor.corrections[wide]
            translation[axis] += (_u16(blob, at) if wide else blob[at]) / _TRANSLATION_SCALE
            cursor.corrections[wide] += 1 + wide
        cursor.translation_bases[wide] += 12
        cursor.translation_masks[wide] += 1
        return translation
    if flags & _TRANS_ANIMATED:
        cursor.floats += 12
        return struct.unpack_from('>3f', blob, cursor.floats - 12)
    if flags & _TRANS_NONE:
        return None
    cursor.static_translations += 12
    return struct.unpack_from('>3f', blob, cursor.static_translations - 12)


def _decode_frame(blob: bytes, header: int, layout: _Layout, frame: int) -> tuple[BoneKey, ...]:
    vlc_offset = 0
    if layout.frame_table and frame:
        stride = _u16(blob, layout.frame_table)
        vlc_offset = (_s16(blob, layout.frame_table + 2 * frame) +
                      stride * frame if stride else _u16(blob, layout.frame_table + 2 * frame))
    cursor = _Cursor(layout.base, _BitReader(blob, layout.vlc + vlc_offset),
                     layout.frame_floats + 12 * _s16(blob, header + 0x34) * frame,
                     layout.frame_rotations + _s16(blob, header + 0x14) * frame,
                     layout.static_rotations, layout.static_translations, [
                         layout.trans8_data + _s16(blob, header + 0x3C) * frame,
                         layout.trans16_data + 2 * _s16(blob, header + 0x3A) * frame
                     ], [layout.trans8_base, layout.trans16_base])
    keys = []
    for bone in range(_u16(blob, header + 0x1C)):
        flags = int(struct.unpack_from('<H', blob, header + _SKA_HEADER_SIZE + 2 * bone)[0])
        rotation = _rotation(blob, layout, cursor, flags)
        translation = _translation(blob, layout, cursor, flags)
        keys.append(
            BoneKey((rotation[0], rotation[1], rotation[2], rotation[3]),
                    None if translation is None else
                    (translation[0], translation[1], translation[2])))
    return tuple(keys)


def _state_names(blob: bytes) -> dict[int, tuple[str, float]]:
    names: dict[int, tuple[str, float]] = {}
    states = _u32(blob, 0x28)
    for index in range(_u32(blob, 0x24)):
        state = _u32(blob, states + 4 * index)
        node = _u32(blob, state + 4)
        if _u32(blob, node) != _STATE_NODE:
            continue
        motion_node = _u32(blob, node + 0xC)
        if _u32(blob, motion_node) != _MOTION_NODE:
            continue
        name_at = _u32(blob, state)
        name = blob[name_at:blob.index(b'\0', name_at)].decode('latin-1')
        ticks = struct.unpack_from('>f', blob, motion_node + 0x18)[0]
        names.setdefault(_u32(blob, motion_node + 0xC), (name, ticks))
    return names


def bank_character(data: bytes) -> int:
    """
    Read the skeleton identifier of a motion bank without decoding its motions.

    Parameters
    ----------
    data : bytes
        The resource, including its 16-byte header.

    Returns
    -------
    int
        Identifier of the skeleton the bank animates.
    """
    return _u32(data, _HEADER + 0xC)


def parse_bank(data: bytes) -> Bank:
    """
    Parse and decode every motion of a motion bank.

    A motion takes the name of the state playing it. The motion node of that state records how many
    engine ticks each frame lasts. A motion no state plays is called ``motion_<index>`` and given
    two ticks a frame, the rate of most of the game's states.

    Parameters
    ----------
    data : bytes
        The resource, including its 16-byte header.

    Returns
    -------
    Bank
        The decoded bank.

    Raises
    ------
    ValueError
        If a motion uses a codec other than SKA, or the older SKA layout.
    """
    blob = data[_HEADER:]
    names = _state_names(blob)
    motions = _u32(blob, 0x30)
    clips = []
    for index in range(_u32(blob, 0x2C)):
        motion = _u32(blob, motions + 4 * index)
        if (codec := _u32(blob, motion + 0x24) & 0xFFFF) != _SKA_CODEC:
            msg = f'Motion {index} uses codec {codec}, not SKA.'
            raise ValueError(msg)
        header = align_up(motion + 0x34, _ALIGN)
        if not _u32(blob, header):
            msg = f'Motion {index} uses the older SKA layout.'
            raise ValueError(msg)
        layout = _layout(blob, header)
        name, ticks = names.get(motion, (f'motion_{index:02d}', _DEFAULT_TICKS_PER_FRAME))
        frames = tuple(
            _decode_frame(blob, header, layout, frame)
            for frame in range(_u32(blob, motion + 0x1C)))
        clips.append(Clip(ticks / MOTION_TICK_RATE, frames, name))
    return Bank(bank_character(data), tuple(clips))
