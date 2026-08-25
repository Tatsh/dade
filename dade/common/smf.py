"""
Standard MIDI file reading and rewriting.

These helpers operate on raw SMF bytes rather than a parsed representation, so timing and running
status survive a rewrite untouched. That matters when the sequences are converted from a game's own
format and any re-quantising would change what is heard.

Two rewrites are offered. :py:func:`to_xg` prepends a setup track that sends XG System On and arms
channel 10 as a drum channel, optionally remapping the drum notes onto General MIDI percussion so
the result plays recognisably on any device. :py:func:`remap_channel` moves one channel's voice
messages to another, which is needed when a game uses channel 10 as an ordinary part that a General
MIDI player would otherwise force to percussion.
"""
from __future__ import annotations

import struct

__all__ = ('DRUM_CHANNEL', 'read_vlq', 'remap_channel', 'split_tracks', 'to_xg', 'used_channels',
           'write_vlq')

DRUM_CHANNEL = 9
"""Zero-indexed General MIDI percussion channel, spoken of as channel 10.

:meta hide-value:
"""

_VOICE_TWO_BYTE = (0x80, 0x90, 0xA0, 0xB0, 0xE0)
_VOICE_ONE_BYTE = (0xC0, 0xD0)
_SYSEX = (0xF0, 0xF7)
_META = 0xFF


def write_vlq(value: int) -> bytes:
    """
    Encode an integer as a MIDI variable-length quantity.

    Parameters
    ----------
    value : int
        A non-negative integer.

    Returns
    -------
    bytes
        The encoded value, most significant group first.
    """
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def read_vlq(buffer: bytes, position: int) -> tuple[int, int]:
    """
    Decode a MIDI variable-length quantity.

    Parameters
    ----------
    buffer : bytes
        Buffer to read from.
    position : int
        Offset of the first byte.

    Returns
    -------
    tuple[int, int]
        The decoded value and the offset just past it.
    """
    value = 0
    while True:
        byte = buffer[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, position


def split_tracks(data: bytes) -> tuple[int, list[bytes]]:
    """
    Split a standard MIDI file into its division and track bodies.

    Parameters
    ----------
    data : bytes
        A standard MIDI file.

    Returns
    -------
    tuple[int, list[bytes]]
        The division and one body per track, without their ``MTrk`` headers.

    Raises
    ------
    ValueError
        If *data* is not a standard MIDI file.
    """
    if data[:4] != b'MThd':
        msg = 'Not a standard MIDI file.'
        raise ValueError(msg)
    _, track_count, division = struct.unpack_from('>HHH', data, 8)
    position = 14
    out = []
    for _ in range(track_count):
        length = struct.unpack_from('>I', data, position + 4)[0]
        out.append(data[position + 8:position + 8 + length])
        position += 8 + length
    return division, out


def _rebuild(division: int, tracks: list[bytes]) -> bytes:
    out = b'MThd' + struct.pack('>IHHH', 6, 1, len(tracks), division)
    for track in tracks:
        out += b'MTrk' + struct.pack('>I', len(track)) + track
    return out


def _xg_setup_track(drum_program: int = 0) -> bytes:
    """
    Build a leading track that sends XG System On and arms the drum channel.

    Returns
    -------
    bytes
        The track body.
    """
    out = bytearray()
    out += write_vlq(0) + bytes([0xF0, 8, 0x43, 0x10, 0x4C, 0x00, 0x00, 0x7E, 0x00, 0xF7])
    out += write_vlq(0) + bytes([0xB0 | DRUM_CHANNEL, 0x00, 127])  # Bank select MSB: drums.
    out += write_vlq(0) + bytes([0xB0 | DRUM_CHANNEL, 0x20, 0])  # Bank select LSB.
    out += write_vlq(0) + bytes([0xC0 | DRUM_CHANNEL, drum_program & 0x7F])
    return bytes(out + write_vlq(0) + bytes([_META, 0x2F, 0]))


def used_channels(data: bytes) -> set[int]:
    """
    Collect the channels carrying any voice message.

    Parameters
    ----------
    data : bytes
        A standard MIDI file.

    Returns
    -------
    set[int]
        Zero-indexed channel numbers. A :py:class:`ValueError` propagates if *data* is not a
        standard MIDI file.
    """
    used: set[int] = set()
    for body in split_tracks(data)[1]:
        position, length, running = 0, len(body), 0
        while position < length:
            _, position = read_vlq(body, position)
            byte = body[position]
            if byte & 0x80:
                status = byte
                position += 1
            else:
                status = running
            high = status & 0xF0
            if high in _VOICE_TWO_BYTE:
                used.add(status & 0x0F)
                position += 2
                running = status
            elif high in _VOICE_ONE_BYTE:
                used.add(status & 0x0F)
                position += 1
                running = status
            elif status in _SYSEX:
                size, position = read_vlq(body, position)
                position += size
                running = 0
            elif status == _META:
                position += 1
                size, position = read_vlq(body, position)
                position += size
                running = 0
            else:
                break
    return used


def _rewrite_track(body: bytes,
                   drum_map: dict[int, int] | None = None,
                   channels: tuple[int, int] | None = None) -> bytes:
    """
    Rewrite one track body, optionally remapping drum notes or moving a channel.

    Timing, running status, meta events, and system exclusive events are all preserved. Only note
    numbers on the drum channel and the channel nibble of voice messages are touched.

    Returns
    -------
    bytes
        The rewritten track body.

    Raises
    ------
    ValueError
        If the track holds an unhandled status byte.
    """
    out = bytearray()
    position, length, running = 0, len(body), 0
    while position < length:
        delta, position = read_vlq(body, position)
        out += write_vlq(delta)
        byte = body[position]
        explicit = bool(byte & 0x80)
        if explicit:
            status = byte
            position += 1
        else:
            status = running
        high = status & 0xF0
        emitted = status
        if (channels is not None and high in {*_VOICE_TWO_BYTE, *_VOICE_ONE_BYTE}
                and (status & 0x0F) == channels[0]):
            emitted = (status & 0xF0) | channels[1]
        if explicit:
            out.append(emitted)
        if high in _VOICE_TWO_BYTE:
            first, second = body[position], body[position + 1]
            if (drum_map is not None and high in {0x80, 0x90} and (status & 0x0F) == DRUM_CHANNEL):
                first = drum_map.get(first, first)
            out.append(first)
            out.append(second)
            position += 2
            running = status
        elif high in _VOICE_ONE_BYTE:
            out.append(body[position])
            position += 1
            running = status
        elif status in _SYSEX:
            size, position = read_vlq(body, position)
            out += write_vlq(size) + body[position:position + size]
            position += size
            running = 0
        elif status == _META:
            out.append(body[position])
            position += 1
            size, position = read_vlq(body, position)
            out += write_vlq(size) + body[position:position + size]
            position += size
            running = 0
        else:
            msg = f'Unhandled MIDI status 0x{status:02X}.'
            raise ValueError(msg)
    return bytes(out)


def remap_channel(data: bytes, source: int, destination: int) -> bytes:
    """
    Move every voice message on one channel to another.

    Only the channel nibble changes, so running-status runs stay self-consistent.

    Parameters
    ----------
    data : bytes
        A standard MIDI file.
    source : int
        Zero-indexed channel to move from.
    destination : int
        Zero-indexed channel to move to.

    Returns
    -------
    bytes
        The rewritten file. A :py:class:`ValueError` propagates if *data* is not a standard MIDI
        file or holds an unhandled status byte.
    """
    division, tracks = split_tracks(data)
    return _rebuild(division, [_rewrite_track(t, channels=(source, destination)) for t in tracks])


def to_xg(data: bytes, drum_map: dict[int, int] | None = None, drum_program: int = 0) -> bytes:
    """
    Prepend an XG initialisation track, optionally remapping the drums.

    Parameters
    ----------
    data : bytes
        A standard MIDI file.
    drum_map : dict[int, int] | None
        Game drum key to General MIDI percussion note. When ``None`` the notes are left as they
        are, which is faithful to the game but needs its SoundFont to sound right.
    drum_program : int
        Drum kit selected on the percussion channel.

    Returns
    -------
    bytes
        The rewritten file. A :py:class:`ValueError` propagates if *data* is not a standard MIDI
        file or holds an unhandled status byte.
    """
    division, tracks = split_tracks(data)
    rewritten = [_rewrite_track(t, drum_map=drum_map) for t in tracks] if drum_map else tracks
    return _rebuild(division, [_xg_setup_track(drum_program), *rewritten])
