from __future__ import annotations

from typing import TYPE_CHECKING
import math
import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.sopranos.olv import INSTANCE_SIZE, PROTOTYPE_SIZE, read_placements

if TYPE_CHECKING:
    from collections.abc import Sequence

_PROTOTYPES_AT = 0x667C
_INSTANCES_AT = 0x16A80
_INSTANCES_END = 0x38A80
_STRINGS_AT = 0x38B00


def build_olv(placements: Sequence[tuple[str, int, int, int, int, int]],
              prototypes: Sequence[str]) -> bytes:
    """
    Build a ``.OLV`` object level.

    Parameters
    ----------
    placements : Sequence[tuple[str, int, int, int, int, int]]
        Each as ``(name, prototype index, x, y, z, turn)``.
    prototypes : Sequence[str]
        Prototype names, indexed by the placements.

    Returns
    -------
    bytes
        The whole file.
    """
    strings = bytearray(b'\0')
    offsets: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in offsets:
            offsets[text] = len(strings)
            strings.extend(text.encode() + b'\0')
        return offsets[text]

    raw = bytearray(_STRINGS_AT)
    struct.pack_into('<4I', raw, 0, _PROTOTYPES_AT, _PROTOTYPES_AT, _INSTANCES_AT, _INSTANCES_END)
    struct.pack_into('<I', raw, 0x18, _STRINGS_AT)
    struct.pack_into('<I', raw, 0x4C, len(placements))
    for index, name in enumerate(prototypes):
        struct.pack_into('<H', raw, _PROTOTYPES_AT + index * PROTOTYPE_SIZE + 0x14, intern(name))
    for slot, (name, prototype, x, y, z, turn) in enumerate(placements, start=1):
        at = _INSTANCES_AT + slot * INSTANCE_SIZE
        struct.pack_into('<4h', raw, at + 0x08, x, y, z, -1)
        struct.pack_into('<2H', raw, at + 0x14, intern(name), prototype)
        struct.pack_into('<h', raw, at + 0x22, turn)
    return bytes(raw) + bytes(strings)


def test_read_placements_reads_position_and_prototype() -> None:
    data = build_olv([('iSatrialesChair 1', 1, 1263, -61, 8, 0)], ['interact', 'SatrialesChair'])
    placement, = read_placements(data)
    assert placement.name == 'iSatrialesChair 1'
    assert placement.prototype == 'SatrialesChair'
    assert (placement.x, placement.y, placement.z) == (1263.0, -61.0, 8.0)


def test_read_placements_turns_the_heading_the_right_way() -> None:
    # The file measures its heading the other way round and from the opposite axis.
    data = build_olv([('a', 0, 0, 0, 0, 0), ('b', 0, 1, 0, 0, 0x4000)], ['thing'])
    first, second = read_placements(data)
    assert math.isclose(math.degrees(first.rotation), 180.0)
    assert math.isclose(math.degrees(second.rotation), 90.0)


def test_read_placements_reports_heights_as_recorded() -> None:
    data = build_olv([('pot', 0, 10, 20, 160, 0)], ['SimmeringPot'])
    assert read_placements(data)[0].z == pytest.approx(160.0)


def test_read_placements_drops_entries_with_a_nameless_prototype() -> None:
    data = build_olv([('kept', 0, 1, 2, 3, 0), ('dropped', 1, 4, 5, 6, 0)], ['thing', ''])
    assert [p.name for p in read_placements(data)] == ['kept']


def test_read_placements_ignores_an_out_of_range_name() -> None:
    raw = bytearray(build_olv([('thing', 0, 1, 2, 3, 0)], ['thing']))
    struct.pack_into('<H', raw, _INSTANCES_AT + INSTANCE_SIZE + 0x14, 0xFFFF)
    assert not read_placements(bytes(raw))[0].name


def test_read_placements_stops_at_the_end_of_the_table() -> None:
    raw = bytearray(build_olv([('thing', 0, 1, 2, 3, 0)], ['thing']))
    struct.pack_into('<I', raw, 0x4C, 0xFFFF)
    assert len(read_placements(bytes(raw))) < 0xFFFF


def test_read_placements_rejects_a_short_file() -> None:
    with pytest.raises(InvalidFormatError, match='too short'):
        read_placements(bytes(0x100))


def test_read_placements_rejects_a_foreign_header() -> None:
    raw = bytearray(build_olv([], []))
    struct.pack_into('<I', raw, 0, 0xDEAD)
    with pytest.raises(InvalidFormatError, match=r'expected \.OLV table offsets'):
        read_placements(bytes(raw))
