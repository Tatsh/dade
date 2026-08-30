"""
Reader for the object level (``.OLV``) file, which places a level's props and cast.

An ``.OLV`` is not a chunk stream but a memory image of the runtime object manager, so every array
sits at a fixed offset that the game hard-codes. The file header repeats those offsets and the
compiled size of each record, and the loader refuses a file whose numbers disagree with the
executable's own, which is what makes them safe to rely on here.

Two tables matter. The prototype table names each kind of object the level can place, and the
instance table places them: a world position, a turn about the vertical axis, and the index of the
prototype to draw. A prototype's name matches a section of the level's ``.SGP2`` library, which is
where the geometry lives.

Positions are three whole-unit ``s16`` followed by a ``-1`` filler. Height matters: a level with
more than one storey puts its furniture on the upper floor, and the kitchen's pots and pans stand on
the stove rather than the ground.
"""
from __future__ import annotations

from typing import NamedTuple
import logging
import math
import struct

from dade.common.exceptions import InvalidFormatError

__all__ = ('INSTANCE_SIZE', 'PROTOTYPE_SIZE', 'Placement', 'read_placements')

log = logging.getLogger(__name__)

PROTOTYPE_SIZE = 0x104
"""Bytes per prototype record.

:meta hide-value:
"""

INSTANCE_SIZE = 0x88
"""Bytes per instance record.

:meta hide-value:
"""

_PROTOTYPE_TABLE_AT = 0x667C
_INSTANCE_TABLE_AT = 0x16A80
_INSTANCE_TABLE_END = 0x38A80
_EXPECTED_HEADER = (_PROTOTYPE_TABLE_AT, _PROTOTYPE_TABLE_AT, _INSTANCE_TABLE_AT,
                    _INSTANCE_TABLE_END)
_STRING_TABLE_AT = 0x18
_INSTANCE_COUNT_AT = 0x4C
_POSITION_AT = 0x08
_NAME_AT = 0x14
_PROTOTYPE_AT = 0x16
_ROTATION_AT = 0x22
_NAME_LIMIT = 120
_FULL_TURN = 0x10000


class Placement(NamedTuple):
    """One object placed in a level."""

    name: str
    """The instance's own name, such as ``iSatrialesChair 1``."""
    prototype: str
    """Name of the object to draw, matching a ``.SGP2`` section."""
    x: float
    """World position along X."""
    y: float
    """World position along Y."""
    z: float
    """World position along Z, the height the object stands at."""
    rotation: float
    """Turn about the vertical axis, in radians, anticlockwise seen from above.

    The file measures its heading the other way round and from the opposite axis, so this is half a
    turn less the stored angle. Two independent checks agree: every one of Vesuvio's thirty-two
    dining chairs then faces the table it belongs to, with a mean cosine of 0.993, and the
    bathroom's urinals turn to stand three units off the wall behind them rather than nineteen
    units in front of it.
    """


def _name_at(data: bytes, strings: int, offset: int) -> str:
    """
    Read a NUL-terminated name from the string table.

    Parameters
    ----------
    data : bytes
        The whole ``.OLV`` file.
    strings : int
        Absolute offset of the string table.
    offset : int
        Offset of the name within the table.

    Returns
    -------
    str
        The name, empty when the offset does not point at one.
    """
    start = strings + offset
    if not 0 < start < len(data):
        return ''
    end = data.find(b'\0', start)
    if not 0 < end - start <= _NAME_LIMIT:
        return ''
    return data[start:end].decode('ascii', 'replace')


def read_placements(data: bytes) -> tuple[Placement, ...]:
    """
    Read every object a level places.

    Heights are reported exactly as recorded. A handful of instances put an object at zero where
    its fellows are on an upper floor -- Vesuvio's Bar Mitzvah cake ends up hovering over a table
    that sits a storey below it -- and giving those the median height of their prototype was tried
    and withdrawn: it fires on an eighth of all placements and lifts the Bing's ground-floor chairs
    into the air, where the floor beneath them is plainly at zero.

    Parameters
    ----------
    data : bytes
        The whole ``.OLV`` file.

    Returns
    -------
    tuple[Placement, ...]
        One entry per placed object, in file order. Entries whose prototype has no name are
        dropped, which covers the unused tail of the table.

    Raises
    ------
    InvalidFormatError
        If the file does not carry the expected table offsets.
    """
    if len(data) <= _INSTANCE_TABLE_END:
        msg = f'File is {len(data)} bytes, too short to be a .OLV.'
        raise InvalidFormatError(msg)
    if struct.unpack_from('<4I', data, 0) != _EXPECTED_HEADER:
        msg = 'File does not start with the expected .OLV table offsets.'
        raise InvalidFormatError(msg)
    strings = struct.unpack_from('<I', data, _STRING_TABLE_AT)[0]
    count = struct.unpack_from('<I', data, _INSTANCE_COUNT_AT)[0]
    placements = []
    for index in range(1, count + 1):
        at = _INSTANCE_TABLE_AT + index * INSTANCE_SIZE
        if at + INSTANCE_SIZE > _INSTANCE_TABLE_END:
            break
        x, y, z, _pad = struct.unpack_from('<4h', data, at + _POSITION_AT)
        name = _name_at(data, strings, struct.unpack_from('<H', data, at + _NAME_AT)[0])
        prototype = struct.unpack_from('<H', data, at + _PROTOTYPE_AT)[0]
        turn = struct.unpack_from('<h', data, at + _ROTATION_AT)[0]
        label = _name_at(
            data, strings,
            struct.unpack_from('<H', data,
                               _PROTOTYPE_TABLE_AT + prototype * PROTOTYPE_SIZE + _NAME_AT)[0])
        if not label:
            continue
        placements.append(
            Placement(name, label, float(x), float(y), float(z),
                      math.pi - turn / _FULL_TURN * math.tau))
    return tuple(placements)
