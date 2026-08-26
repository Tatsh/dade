"""
The RBFF note chart.

A chart opens with a sixteen-byte file header: the ``RBFF`` magic, a format version, and eight
bytes the parser does not read. Versions 10 to 14 take the layout below; 6 and 7 take an older one
the shipped packages do not use, and anything else is rejected.

The chart header follows at offset sixteen, then the notes, then the tempo events, then the slide
records. A note is variable length: it carries an inline array of path points whose count it
declares, and a twelve-byte chain block that is present only when flag bit 3 is set. Because of
that, a mis-sized field desynchronises the cursor rather than merely yielding wrong values, so a
chart that parses to exactly the end of its buffer is strong evidence the layout is right.

Times are milliseconds. A note's ``time`` may be negative: a chart begins before its audio does.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from .typing import ChartDict, ChartHeaderDict, NoteDict, SlideDict, TempoEventDict

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ('LEGACY_VERSIONS', 'MAGIC', 'MODERN_VERSIONS', 'NOTE_FLAGS', 'SLIDE_LANE_REMAP',
           'SPEED_CHANGE_KIND', 'TEMPO_EVENT_SIZE', 'ChartError', 'flag_names', 'parse_chart')

MAGIC = b'RBFF'
"""The four bytes a chart opens with.

:meta hide-value:
"""
MODERN_VERSIONS = frozenset(range(10, 15))
"""The format versions this parser reads.

:meta hide-value:
"""
LEGACY_VERSIONS = frozenset((6, 7))
"""The format versions the game reads with an older parser, which no shipped chart uses.

:meta hide-value:
"""
NOTE_FLAGS: Mapping[int, str] = {
    0x01: 'same_lane',
    0x04: 'different_lane',
    0x08: 'long_head',
    0x10: 'free',
    0x20: 'has_path',
    0x40: 'side_object',
}
"""The note flag bits and the names the engine gives them.

:meta hide-value:
"""
SLIDE_LANE_REMAP = (6, 5, 4, 3, 2, 1, 0, 9, 8, 7)
"""Maps an on-disk slide lane to the engine's internal lane.

:meta hide-value:
"""
SPEED_CHANGE_KIND = 3
"""The tempo-event kind that installs a new scroll speed.

:meta hide-value:
"""
TEMPO_EVENT_SIZE = 36
"""Bytes in one tempo event, most of which the engine never unpacks.

:meta hide-value:
"""

_FILE_HEADER_SIZE = 16
_VERSION_OFFSET = 4
_NOTES_OFFSET = 0x1C
_LONG_HEAD_FLAG = 0x08
_CHAIN_BLOCK_SIZE = 12
_SLIDE_RECORD_SIZE = 16
_SLIDE_LANE_SENTINELS: Mapping[int, int] = {0xFFFF: -2, 0xFFFE: -2, 0xFFFD: -4, 0xFFFC: -3}

_HEADER = struct.Struct('<iii')
_COUNTS = struct.Struct('<hhh')
_SLIDE_COUNT = struct.Struct('<i')
_NOTE_LEAD = struct.Struct('<iihhh')
_NOTE_BYTES = struct.Struct('<4b')
_TARGETS = struct.Struct('<4h')
_FLAGS = struct.Struct('<I')
_CHAIN = struct.Struct('<hhii')
_TRAILER = struct.Struct('<bbhi')
_SLIDE = struct.Struct('<HHH2xii')
_SHORT = struct.Struct('<h')
_INT = struct.Struct('<i')


class ChartError(Exception):
    """Raised when a buffer is not a chart this parser reads."""


def _read_note(data: bytes, offset: int) -> tuple[NoteDict, int]:
    spawn_time, travel_time, note_id, start_time, point_count = _NOTE_LEAD.unpack_from(data, offset)
    offset += _NOTE_LEAD.size
    path_points: tuple[int, ...] = ()
    if point_count > 0:
        path_points = struct.unpack_from(f'<{point_count}h', data, offset)
        offset += 2 * point_count
    kind, side, hold_kind, note_type = _NOTE_BYTES.unpack_from(data, offset)
    offset += _NOTE_BYTES.size
    target = _TARGETS.unpack_from(data, offset)
    offset += _TARGETS.size
    flags = _FLAGS.unpack_from(data, offset)[0]
    offset += _FLAGS.size
    # The engine reads these four fields into its staging record and never unpacks them again.
    # They are read here too rather than stepped over, so that a chart ending inside them is caught
    # rather than silently accepted.
    _TRAILER.unpack_from(data, offset)
    offset += _TRAILER.size
    chain: tuple[int, int, int, int] | None = None
    if flags & _LONG_HEAD_FLAG:
        chain = _CHAIN.unpack_from(data, offset)
        offset += _CHAIN_BLOCK_SIZE
    return NoteDict(spawn_time=spawn_time,
                    travel_time=travel_time,
                    hit_time=spawn_time + travel_time,
                    id=note_id,
                    start_time=start_time,
                    kind=kind,
                    side=side,
                    hold_kind=hold_kind,
                    type=note_type,
                    target=target,
                    flags=flags,
                    path_points=path_points,
                    chain=chain), offset


def _read_tempo_event(data: bytes, offset: int) -> TempoEventDict:
    block = data[offset:offset + TEMPO_EVENT_SIZE]
    if len(block) < TEMPO_EVENT_SIZE:
        msg = f'Truncated tempo event at offset {offset}.'
        raise ChartError(msg)
    return TempoEventDict(kind=_SHORT.unpack_from(block)[0],
                          time=_INT.unpack_from(block, 0x04)[0],
                          speed=_INT.unpack_from(block, 0x10)[0],
                          raw=block.hex())


def _read_notes(data: bytes, offset: int, count: int) -> tuple[list[NoteDict], int]:
    # Every note and the offset just past the last one. A note is variable length, so the notes
    # cannot be addressed individually the way the fixed-size records after them can.
    notes = []
    for _ in range(count):
        note, offset = _read_note(data, offset)
        notes.append(note)
    return notes, offset


def _read_slide(data: bytes, offset: int) -> SlideDict:
    note_index, field2, raw_lane, value_a, value_b = _SLIDE.unpack_from(data, offset)
    return SlideDict(note_index=note_index,
                     field2=field2,
                     lane=_slide_lane(raw_lane),
                     value_a=value_a,
                     value_b=value_b)


def _slide_lane(raw: int) -> int:
    if (sentinel := _SLIDE_LANE_SENTINELS.get(raw)) is not None:
        return sentinel
    if 0 <= raw < len(SLIDE_LANE_REMAP):
        return SLIDE_LANE_REMAP[raw]
    # The engine indexes its remap table unguarded; reporting the raw lane is safer than reading
    # past the table as it would.
    return raw


def _read_records(
        data: bytes, *, note_count: int, slide_record_count: int,
        tempo_event_count: int) -> tuple[list[NoteDict], list[TempoEventDict], list[SlideDict]]:
    # The notes, tempo events, and slide records that follow the chart header, in stream order. A
    # mis-sized field desynchronises the cursor, so running off the end is reported as a chart
    # error rather than left as a struct error.
    offset = _FILE_HEADER_SIZE + _NOTES_OFFSET
    try:
        notes, offset = _read_notes(data, offset, note_count)
        tempo_events = [
            _read_tempo_event(data, offset + index * TEMPO_EVENT_SIZE)
            for index in range(tempo_event_count)
        ]
        offset += tempo_event_count * TEMPO_EVENT_SIZE
        slides = [
            _read_slide(data, offset + index * _SLIDE_RECORD_SIZE)
            for index in range(max(slide_record_count, 0))
        ]
    except struct.error as e:
        msg = f'Chart ends inside a record at offset {offset}.'
        raise ChartError(msg) from e
    return notes, tempo_events, slides


def flag_names(flags: int) -> tuple[str, ...]:
    """
    Name the bits set in a note's flags.

    Parameters
    ----------
    flags : int
        The note's flag word.

    Returns
    -------
    tuple[str, ...]
        The names of the set bits, lowest first. Bits with no name are omitted.
    """
    return tuple(name for bit, name in sorted(NOTE_FLAGS.items()) if flags & bit)


def parse_chart(data: bytes) -> ChartDict:
    """
    Parse an RBFF chart.

    Parameters
    ----------
    data : bytes
        The deciphered chart.

    Returns
    -------
    ChartDict
        The header, the notes, the tempo events, and the slide records.

    Raises
    ------
    ChartError
        If the magic is wrong, the version is one this parser does not read, or the stream ends
        inside a record.
    """
    if not data.startswith(MAGIC):
        msg = f'Not a chart: expected {MAGIC!r}, got {data[:len(MAGIC)]!r}.'
        raise ChartError(msg)
    version = _FLAGS.unpack_from(data, _VERSION_OFFSET)[0]
    if version not in MODERN_VERSIONS:
        known = 'the legacy layout, which is not read here' if version in LEGACY_VERSIONS else (
            'no known layout')
        msg = f'Chart format version {version} uses {known}.'
        raise ChartError(msg)

    initial_speed, end_time, seed = _HEADER.unpack_from(data, _FILE_HEADER_SIZE)
    note_count, tempo_event_count, free_note_count = _COUNTS.unpack_from(
        data, _FILE_HEADER_SIZE + 0x0C)
    slide_record_count = _SLIDE_COUNT.unpack_from(data, _FILE_HEADER_SIZE + 0x14)[0]

    notes, tempo_events, slides = _read_records(data,
                                                note_count=note_count,
                                                slide_record_count=slide_record_count,
                                                tempo_event_count=tempo_event_count)
    return ChartDict(header=ChartHeaderDict(version=version,
                                            initial_speed=initial_speed,
                                            end_time=end_time,
                                            seed=seed,
                                            note_count=note_count,
                                            tempo_event_count=tempo_event_count,
                                            free_note_count=free_note_count,
                                            slide_record_count=slide_record_count),
                     notes=notes,
                     tempo_events=tempo_events,
                     slides=slides)
