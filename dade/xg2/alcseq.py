"""
The libaudio ``ALCSeq`` compressed sequence format, shared by both Extreme-G games.

A sequence begins with sixteen track offsets, one per MIDI channel, and carries its division at
offset ``0x40``. Each track is a stream of delta times and MIDI-like events with two departures
from a standard MIDI file: note-on events carry an explicit duration rather than a matching
note-off, and the byte ``0xFE`` introduces a back-reference that replays a run of earlier bytes.

Loops are taken once. A loop-end event skips its body without jumping back, which linearises the
sequence for export; the game itself would repeat it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import operator
import struct

from .smf import write_vlq

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('DEFAULT_DIVISION', 'CSeqReader', 'decode_track', 'to_midi')

DEFAULT_DIVISION = 0x180
"""Division used when the sequence header does not hold a plausible one.

:meta hide-value:
"""
_BLOCK_CODE = 0xFE
_META = 0xFF
_META_TEMPO = 0x51
_META_END = 0x2F
_META_LOOP_START = 0x2E
_META_LOOP_END = 0x2D
_LOOP_END_BODY = 6
_TRACK_COUNT = 16
_GUARD = 500000
_NOTE_OFF = 0x80
_NOTE_ON = 0x90
_ONE_BYTE_MESSAGES = frozenset({0xC0, 0xD0})
_MAX_DIVISION = 0x8000


class CSeqReader:
    """
    Byte reader for one ``ALCSeq`` track, resolving back-reference blocks.

    Parameters
    ----------
    data : bytes
        The whole sequence blob.
    position : int
        Offset of the track within *data*.
    """
    def __init__(self, data: bytes, position: int) -> None:
        self.data = data
        self.position = position
        self.block_position = 0
        self.block_remaining = 0

    def byte(self) -> int:
        """
        Read one byte, transparently replaying a back-reference block.

        Returns
        -------
        int
            The next byte of the logical stream.
        """
        if self.block_remaining > 0:
            value = self.data[self.block_position]
            self.block_position += 1
            self.block_remaining -= 1
            return value
        value = self.data[self.position]
        self.position += 1
        if value == _BLOCK_CODE:
            following = self.data[self.position]
            self.position += 1
            if following != _BLOCK_CODE:  # A literal 0xFE is escaped by doubling it.
                low = self.data[self.position]
                self.position += 1
                length = self.data[self.position]
                self.position += 1
                self.block_position = self.position - (((following << 8) | low) + 4)
                self.block_remaining = length
                value = self.data[self.block_position]
                self.block_position += 1
                self.block_remaining -= 1
        return value

    def vlq(self) -> int:
        """
        Read a variable-length quantity.

        Returns
        -------
        int
            The decoded value.
        """
        value = self.byte()
        if value & 0x80:
            value &= 0x7F
            while True:
                byte = self.byte()
                value = (value << 7) + (byte & 0x7F)
                if not byte & 0x80:
                    break
        return value


def decode_track(data: bytes, start: int) -> list[tuple[int, str, tuple[int, ...]]]:
    """
    Decode one ``ALCSeq`` track to timed events.

    Parameters
    ----------
    data : bytes
        The whole sequence blob.
    start : int
        Offset of the track within *data*.

    Returns
    -------
    list[tuple[int, str, tuple[int, ...]]]
        Each event as its absolute tick, a kind of ``T`` for tempo, ``N`` for a note with a
        duration, or ``M`` for any other message, and its payload.
    """
    reader = CSeqReader(data, start)
    tick = 0
    running = 0
    events: list[tuple[int, str, tuple[int, ...]]] = []
    delta = reader.vlq()
    for _ in range(_GUARD):
        tick += delta
        status = reader.byte()
        if status == _META:
            kind = reader.byte()
            if kind == _META_TEMPO:
                events.append(
                    (tick, 'T', ((reader.byte() << 16) | (reader.byte() << 8) | reader.byte(),)))
                running = 0
            elif kind == _META_END:
                break
            elif kind == _META_LOOP_START:
                reader.byte()
                reader.byte()
                running = 0
            elif kind == _META_LOOP_END:
                reader.position += _LOOP_END_BODY
                reader.block_remaining = 0
                running = 0
            else:
                break
        else:
            if status & 0x80:
                first = reader.byte()
                running = status
            else:
                first = status
                status = running
            high = status & 0xF0
            if high in _ONE_BYTE_MESSAGES:
                events.append((tick, 'M', (status, first, 0)))
            else:
                second = reader.byte()
                if high == _NOTE_ON:
                    events.append((tick, 'N', (status, first, second, reader.vlq())))
                else:
                    events.append((tick, 'M', (status, first, second)))
        delta = reader.vlq()
    return events


def _flatten(events: list[tuple[int, str, tuple[int, ...]]]) -> list[tuple[int, int, bytes]]:
    """
    Turn decoded events into sortable triples.

    Returns
    -------
    list[tuple[int, int, bytes]]
        Each message as its absolute tick, a sort priority placing note ends first, and its bytes.
    """
    flat: list[tuple[int, int, bytes]] = []
    for tick, kind, payload in events:
        if kind == 'T':
            tempo = payload[0]
            flat.append((tick, 0,
                         bytes([
                             _META, _META_TEMPO, 3, (tempo >> 16) & 0xFF, (tempo >> 8) & 0xFF,
                             tempo & 0xFF
                         ])))
        elif kind == 'N':
            status, note, velocity, duration = payload
            flat.extend(((tick, 1, bytes(
                [status, note,
                 velocity])), (tick + duration, 0, bytes([_NOTE_OFF | (status & 0xF), note, 0]))))
        else:
            status, first, second = payload
            flat.append((tick, 1, bytes([status, first]) if
                         (status & 0xF0) in _ONE_BYTE_MESSAGES else bytes([status, first, second])))
    return flat


def _tracks(data: bytes) -> Iterator[bytes]:
    for channel in range(_TRACK_COUNT):
        offset = struct.unpack_from('>I', data, channel * 4)[0]
        if not 0 < offset < len(data):
            continue
        flat = _flatten(decode_track(data, offset))
        flat.sort(key=operator.itemgetter(0, 1))
        track = bytearray()
        previous = 0
        for tick, _, message in flat:
            track += write_vlq(tick - previous) + message
            previous = tick
        yield bytes(track + write_vlq(0) + bytes([_META, _META_END, 0]))


def to_midi(data: bytes) -> tuple[bytes, int]:
    """
    Convert an ``ALCSeq`` sequence to a format 1 standard MIDI file.

    Parameters
    ----------
    data : bytes
        The sequence blob.

    Returns
    -------
    tuple[bytes, int]
        The MIDI file and the number of tracks written.
    """
    division = struct.unpack_from('>I', data, 0x40)[0]
    if not 0 < division < _MAX_DIVISION:
        division = DEFAULT_DIVISION
    chunks = list(_tracks(data))
    out = b'MThd' + struct.pack('>IHHH', 6, 1, len(chunks), division)
    for chunk in chunks:
        out += b'MTrk' + struct.pack('>I', len(chunk)) + chunk
    return out, len(chunks)
