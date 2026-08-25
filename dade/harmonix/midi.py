"""
Convert Standard MIDI Files (``.mid``) -- the games' note charts -- to JSON via :mod:`mido`.

Amplitude and FreQuency are fully keysounded: each song is a format-1 SMF whose tracks are the
instrument stems (e.g. ``T1 CATCH``, ``T2 B:Upright Bass``, ``WORLD``) and whose NoteOn events
trigger the matching sample banks. This module exposes that chart data as JSON.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import io
import logging

import mido  # type: ignore[import-untyped]

from dade.common.exceptions import InvalidFormatError
from dade.common.json import write_json

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from .typing import MIDIFile, MIDITrack

__all__ = ('EXTENSIONS', 'convert', 'smf_to_obj')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.mid'})
"""File extensions handled by :py:func:`convert`.

:meta hide-value:
"""


def smf_to_obj(data: bytes) -> MIDIFile:
    """
    Decode a Standard MIDI File into a JSON-ready object using :mod:`mido`.

    Each :class:`mido.Message` is serialised via :meth:`mido.Message.dict`, with the per-message
    delta ``time`` replaced by an absolute ``tick``; ``set_tempo`` events also gain a ``bpm`` field.

    Parameters
    ----------
    data : bytes
        The ``.mid`` file contents.

    Returns
    -------
    MIDIFile
        The decoded file.

    Raises
    ------
    InvalidFormatError
        If the bytes are not a readable Standard MIDI File.
    """
    try:
        midi_file = mido.MidiFile(file=io.BytesIO(data), clip=True)
    except (EOFError, OSError, ValueError) as e:
        msg = 'Not a readable Standard MIDI File.'
        raise InvalidFormatError(msg) from e
    tracks: list[MIDITrack] = []
    for track in midi_file.tracks:
        tick = 0
        name = ''
        events: list[dict[str, Any]] = []
        for message in track:
            tick += message.time
            event = message.dict()
            event.pop('time', None)  # Replace the per-message delta time with an absolute tick.
            event['tick'] = tick
            if message.type == 'track_name':
                name = message.name
            elif message.type == 'set_tempo':
                event['bpm'] = round(mido.tempo2bpm(message.tempo), 3)
            events.append(event)
        tracks.append({'name': name, 'event_count': len(events), 'events': events})
    log.debug('MIDI: format %d, %d tracks, division %d ticks/beat', midi_file.type, len(tracks),
              midi_file.ticks_per_beat)
    return {
        'format': midi_file.type,
        'division': midi_file.ticks_per_beat,
        'track_count': len(midi_file.tracks),
        'tracks': tracks
    }


def convert(path: Path) -> Path | None:
    """
    Write a ``<name>.mid.json`` chart sidecar; the standard ``.mid`` is kept.

    Parameters
    ----------
    path : pathlib.Path
        The ``.mid`` file.

    Returns
    -------
    pathlib.Path | None
        The written JSON path, or ``None`` if the file is not a readable SMF.
    """
    try:
        obj = smf_to_obj(path.read_bytes())
    except InvalidFormatError:
        return None
    out = path.with_name(f'{path.name}.json')
    write_json(out, obj, ensure_ascii=False, trailing_newline=False)
    log.debug('MIDI `%s`: %d tracks -> `%s`.', path.name, obj['track_count'], out.name)
    return out
