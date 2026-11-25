"""
Rewriting of the In The Groove PS2 simfiles for StepMania.

The PS2 simfiles play their music from an ``.av`` stream and their background from the special
``_movie`` entry, the video of the same stream. :py:func:`rewrite_simfile` points ``#MUSIC`` at the
WAV and the ``_movie`` entry at the MPEG written from the stream. The PS2 entry is placed at beat
-10000, and the engine plays the video in step with the music. StepMania starts a movie when its
entry is reached, and the entry is therefore moved to the beat at which the music starts.

The In The Groove songs on the In The Groove 2 beta disc identify an OGG that the disc does not
store. The engine plays the ``.av`` stream of the same name instead, and ``#MUSIC`` is pointed at
its WAV. Their backgrounds are the arcade's shared movie clips, which the disc does not store
either, and they are replaced with the video of the stream.

Several In The Groove 2 simfiles were shipped with unresolved CVS merge conflicts. The first side of
each conflict is the PS2 revision, and it is the side retained.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import re

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ('beat_at_music_start', 'resolve_conflicts', 'rewrite_simfile')

_MUSIC = re.compile(r'(#MUSIC:)([^;]*?)(\.[^.;]*);')
_MOVIE = re.compile(r'(?<=[:,\s])-?[\d.]+=_movie=')
_FIRST_SIDE = 1
_SECOND_SIDE = 2
_BACKGROUNDS = re.compile(r'#BGCHANGES:[^;]*;', re.IGNORECASE)
_TAG = re.compile(r'#(OFFSET|BPMS|STOPS):([^;]*);', re.IGNORECASE)


def resolve_conflicts(text: str) -> str:
    """
    Retain the first side of every merge conflict in a simfile.

    Parameters
    ----------
    text : str
        The simfile.

    Returns
    -------
    str
        The simfile without conflict markers or the second side of any conflict.
    """
    lines = []
    side = 0
    for line in text.splitlines(keepends=True):
        if line.startswith('<<<<<<<'):
            side = _FIRST_SIDE
        elif side == _FIRST_SIDE and line.startswith('======='):
            side = _SECOND_SIDE
        elif side and line.startswith('>>>>>>>'):
            side = 0
        elif side != _SECOND_SIDE:
            lines.append(line)
    return ''.join(lines)


def _pairs(value: str) -> list[tuple[float, float]]:
    return sorted((float(beat), float(amount)) for beat, _, amount in (pair.strip().partition('=')
                                                                       for pair in value.split(',')
                                                                       if '=' in pair))


def beat_at_music_start(offset: float, bpms: Sequence[tuple[float, float]],
                        stops: Sequence[tuple[float, float]]) -> float:
    """
    Find the beat at which the music starts.

    Parameters
    ----------
    offset : float
        The ``#OFFSET`` of the simfile. Beat 0 falls this many seconds before the music starts.
    bpms : Sequence[tuple[float, float]]
        The ``#BPMS`` pairs of beat and tempo, sorted by beat. At least one is required.
    stops : Sequence[tuple[float, float]]
        The ``#STOPS`` pairs of beat and seconds, sorted by beat.

    Returns
    -------
    float
        The beat at which the music starts.
    """
    bpm = next((tempo for beat, tempo in reversed(bpms) if beat <= 0), bpms[0][1])
    if offset <= 0:
        return offset * bpm / 60
    changes = {beat: tempo for beat, tempo in bpms if beat > 0}
    pauses = {beat: seconds for beat, seconds in stops if beat >= 0}
    elapsed = offset
    beat = 0.0
    for event in sorted(changes.keys() | pauses.keys()):
        if elapsed <= (span := (event - beat) * 60 / bpm):
            break
        elapsed -= span
        beat = event
        bpm = changes.get(event, bpm)
        if elapsed <= (pause := pauses.get(event, 0)):
            return beat
        elapsed -= pause
    return beat + elapsed * bpm / 60


def rewrite_simfile(text: str, streams: Mapping[str, bool] | None = None) -> str:
    """
    Rewrite a PS2 simfile to play from the files written from its ``.av`` stream.

    Parameters
    ----------
    text : str
        The simfile.
    streams : Mapping[str, bool] | None
        The stems of the ``.av`` streams beside the simfile, in lower case, and whether each has
        video. Music with one of these stems is played from its stream whatever extension
        ``#MUSIC`` gives. When the stream has video and the simfile has no ``_movie`` entry, its
        ``#BGCHANGES`` play the stream's MPEG.

    Returns
    -------
    str
        The simfile with its conflicts resolved, ``#MUSIC`` pointing at the WAV, and the ``_movie``
        background pointing at the MPEG at the beat the music starts on. A simfile whose music is
        not an ``.av`` stream only has its conflicts resolved.
    """
    text = resolve_conflicts(text)
    streams = streams or {}
    if (music := _MUSIC.search(text)) is None or (music[3].lower() != '.av'
                                                  and music[2].strip().lower() not in streams):
        return text
    stem = music[2]
    text = _MUSIC.sub(lambda match: f'{match[1]}{match[2]}.wav;', text, count=1)
    tags = {match[1].upper(): match[2] for match in _TAG.finditer(text)}
    beat = 0.0
    if bpms := _pairs(tags.get('BPMS', '')):
        beat = beat_at_music_start(float(tags.get('OFFSET', '0').strip() or 0), bpms,
                                   _pairs(tags.get('STOPS', '')))
    if _MOVIE.search(text) is None and streams.get(stem.strip().lower()):
        return _BACKGROUNDS.sub(lambda _: f'#BGCHANGES:{beat:.3f}={stem}.mpg=1.000=0=0=1,\n'
                                '99999=-nosongbg-=1.000=0=0=0;',
                                text,
                                count=1)
    return _MOVIE.sub(lambda _: f'{beat:.3f}={stem}.mpg=', text)
