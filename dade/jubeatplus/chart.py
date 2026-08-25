"""
The note charts inside a tune package.

A chart is a 96-byte header followed by one eight-byte record per event. The header opens with a
four-byte magic - ``IJBQ``, ``IJSQ``, or ``JBSQ``, all three accepted by the engine and all three
present in shipped tunes - and carries the event count, the note count, the final sector, the
opening marker and where it falls, and a 60-byte music-bar bitmap at ``0x24``. One 16-bit field at
``0x10`` is never read by the engine and is reported here unnamed.

Each event record is a pair of little-endian 32-bit words. The first packs the event kind into its
low byte and the timing position, in sectors, into its upper twenty-four bits; the second is the
event's value. A tap's value is its playfield panel. A hold's value packs the panel into bits 0-3,
the arrow direction into bits 4-7, and the hold's length in sectors from bit 8 up. A tempo event's
value is microseconds per beat, the same unit MIDI uses. Time runs at exactly
:py:data:`SECTORS_PER_SECOND` sectors per second.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Final
import struct

if TYPE_CHECKING:
    from .typing import ChartDict, ChartEventDict, ChartHeaderDict, Difficulty

__all__ = ('EVENT_KINDS', 'HEADER_SIZE', 'MAGICS', 'MUSIC_BAR_SIZE', 'SECTORS_PER_SECOND',
           'parse_chart')

EVENT_KINDS: Final = {1: 'tap', 2: 'end', 3: 'measure', 4: 'beat', 5: 'tempo', 6: 'hold'}
"""Event-kind byte to name. Kind 2 is the sentinel that closes a chart.

:meta hide-value:
"""
HEADER_SIZE: Final = 0x60
"""Size of a chart header, in bytes.

:meta hide-value:
"""
MAGICS: Final = (b'IJBQ', b'IJSQ', b'JBSQ')
"""The three header magics the engine accepts.

:meta hide-value:
"""
MUSIC_BAR_SIZE: Final = 60
"""Size of the music-bar bitmap, in bytes.

:meta hide-value:
"""
SECTORS_PER_SECOND: Final = 300
"""Sectors the play position advances per second.

:meta hide-value:
"""

_EVENT_SIZE = 8
_MUSIC_BAR_OFFSET = 0x24
_RESERVED_OFFSET = 0x18
_KIND_TAP = 1
_KIND_TEMPO = 5
_KIND_HOLD = 6
_MICROSECONDS_PER_MINUTE = 60_000_000


def _parse_header(data: bytes) -> ChartHeaderDict:
    magic = data[:4]
    if magic not in MAGICS:
        expected = ', '.join(m.decode() for m in MAGICS)
        msg = f'Not a chart: magic {magic!r}, expected one of {expected}.'
        raise ValueError(msg)
    event_count, note_count, end_sector = struct.unpack_from('<III', data, 4)
    unknown, first_marker = struct.unpack_from('<HH', data, 0x10)
    first_marker_sector = struct.unpack_from('<I', data, 0x14)[0]
    return {
        'end_sector': end_sector,
        'end_time': end_sector / SECTORS_PER_SECOND,
        'event_count': event_count,
        'first_marker': first_marker,
        'first_marker_sector': first_marker_sector,
        'first_marker_time': first_marker_sector / SECTORS_PER_SECOND,
        'magic': magic.decode(),
        'music_bar': data[_MUSIC_BAR_OFFSET:_MUSIC_BAR_OFFSET + MUSIC_BAR_SIZE].hex(),
        'note_count': note_count,
        'reserved': data[_RESERVED_OFFSET:_MUSIC_BAR_OFFSET].hex(),
        'unknown_0x10': unknown
    }


def _parse_event(word: int, value: int) -> ChartEventDict:
    kind_id = word & 0xFF
    sector = word >> 8
    event: ChartEventDict = {
        'bpm': None,
        'hold_length_sectors': None,
        'kind': EVENT_KINDS.get(kind_id, f'unknown_{kind_id}'),
        'kind_id': kind_id,
        'microseconds_per_beat': None,
        'move': None,
        'panel': None,
        'sector': sector,
        'time': sector / SECTORS_PER_SECOND,
        'value': value
    }
    if kind_id == _KIND_TAP:
        event['panel'] = value & 0xF
    elif kind_id == _KIND_HOLD:
        event['panel'] = value & 0xF
        event['move'] = (value >> 4) & 0xF
        event['hold_length_sectors'] = value >> 8
    elif kind_id == _KIND_TEMPO and value:
        event['microseconds_per_beat'] = value
        event['bpm'] = _MICROSECONDS_PER_MINUTE / value
    return event


def parse_chart(data: bytes, difficulty: Difficulty | None = None) -> ChartDict:
    """
    Decode a chart from its deciphered bytes.

    Parameters
    ----------
    data : bytes
        The whole chart, header included, already deciphered.
    difficulty : Difficulty | None
        The difficulty the chart was read as, recorded in the result unchanged.

    Returns
    -------
    ChartDict
        The decoded header, every event, and the per-kind counts.

    Raises
    ------
    ValueError
        If the data is too short for a header, its magic is not one the engine accepts, or it is
        too short for the number of events the header claims.
    """
    if len(data) < HEADER_SIZE:
        msg = f'Too short for a {HEADER_SIZE}-byte chart header: {len(data)} bytes.'
        raise ValueError(msg)
    header = _parse_header(data)
    event_count = header['event_count']
    required = HEADER_SIZE + event_count * _EVENT_SIZE
    if len(data) < required:
        msg = (f'Too short for {event_count} events: {len(data)} bytes, {required} needed.')
        raise ValueError(msg)
    events = [
        _parse_event(*struct.unpack_from('<II', data, HEADER_SIZE + i * _EVENT_SIZE))
        for i in range(event_count)
    ]
    counts: dict[str, int] = {}
    for event in events:
        counts[event['kind']] = counts.get(event['kind'], 0) + 1
    # A hold scores twice, at its head and at its release, which is how the engine recounts the
    # header's note total whenever the two disagree.
    note_count = counts.get('tap', 0) + 2 * counts.get('hold', 0)
    return {
        'counts': dict(sorted(counts.items())),
        'difficulty': difficulty,
        'events': events,
        'header': header,
        'note_count': note_count,
        'sectors_per_second': SECTORS_PER_SECOND
    }
