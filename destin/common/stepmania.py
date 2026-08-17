"""
Writer for the StepMania ``.sm`` simfile.

A simfile is a run of ``#TAG:value;`` headers followed by one ``#NOTES`` block per chart. Each
block carries five colon-separated fields - the steps type, a description, the difficulty, the
meter, and the groove radar - and then the note data, in which every measure is a run of rows and
measures are separated by commas. A row holds one character per panel: ``0`` for nothing, ``1``
for a tap, ``2`` and ``3`` for the start and end of a hold, and ``M`` for a mine.

``#OFFSET`` is the one tag whose sign is easy to get backwards. StepMania stores the time of beat
0 negated: ``TimingData`` seeds its walk with ``start.last_time = -m_fBeat0OffsetInSeconds`` and
``NotesLoaderSM`` assigns the tag straight to that member, so a song whose beat 0 falls 5.339
seconds into the audio is written ``#OFFSET:-5.339``. :py:func:`write_sm` therefore takes the gap
as a positive number of seconds and negates it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = ('ROW_CANDIDATES', 'SimfileChart', 'quantize_measures', 'write_sm')

ROW_CANDIDATES = (4, 8, 12, 16, 24, 32, 48, 64, 96, 192)
"""Rows per measure to try, smallest first.

:meta hide-value:
"""

_ROW_TOLERANCE_FRACTION = 1 / 2048
"""How far from a row a note may sit before that row count is rejected, as a fraction of a measure.

Triplets cannot divide a power-of-two tick resolution evenly, so an exact test would reject charts
that legitimately contain them.

:meta hide-value:
"""


class SimfileChart(NamedTuple):
    """One chart's ``#NOTES`` block."""

    steps_type: str
    """The StepMania steps type, such as ``dance-single``."""
    difficulty: str
    """The StepMania difficulty name, such as ``Hard``."""
    meter: int
    """The foot rating. Zero reads as unrated."""
    notes: str
    """The note data, measures separated by commas."""
    description: str = ''
    """The description field, usually the chart's author."""
    radar: str = '0.000,0.000,0.000,0.000,0.000'
    """The groove radar field."""


def _rows_for(offsets: Iterable[int], ticks_per_measure: int) -> int:
    """
    Pick the smallest row count that can represent every offset in a measure.

    Parameters
    ----------
    offsets : collections.abc.Iterable[int]
        Tick offsets within the measure.
    ticks_per_measure : int
        Ticks one measure spans.

    Returns
    -------
    int
        A row count taken from :py:data:`ROW_CANDIDATES`.
    """
    kept = tuple(offsets)
    tolerance = ticks_per_measure * _ROW_TOLERANCE_FRACTION
    for rows in ROW_CANDIDATES:
        spacing = ticks_per_measure / rows
        if all(abs(offset - round(offset / spacing) * spacing) <= tolerance for offset in kept):
            return rows
    return ROW_CANDIDATES[-1]


def quantize_measures(events: Mapping[int, Mapping[int, str]], panels: int,
                      ticks_per_measure: int) -> str:
    """
    Lay tick-addressed note events out as StepMania measure blocks.

    Each measure is given the smallest row count from :py:data:`ROW_CANDIDATES` that can hold its
    notes, so a measure of quarter notes stays four rows rather than being padded out.

    Parameters
    ----------
    events : collections.abc.Mapping[int, collections.abc.Mapping[int, str]]
        ``{tick: {column: character}}``.
    panels : int
        How many columns a row holds.
    ticks_per_measure : int
        Ticks one measure spans.

    Returns
    -------
    str
        The note data, measures separated by commas.
    """
    if not events:
        return '0' * panels
    blocks = []
    for measure in range(max(events) // ticks_per_measure + 1):
        base = measure * ticks_per_measure
        here = {
            tick - base: columns
            for tick, columns in events.items() if base <= tick < base + ticks_per_measure
        }
        rows = _rows_for(here, ticks_per_measure) if here else ROW_CANDIDATES[0]
        spacing = ticks_per_measure / rows
        grid = [['0'] * panels for _ in range(rows)]
        for offset, columns in here.items():
            row = min(round(offset / spacing), rows - 1)
            for column, character in columns.items():
                if column < panels:
                    grid[row][column] = character
        blocks.append('\n'.join(''.join(row) for row in grid))
    return '\n,\n'.join(blocks)


def _pairs(values: Sequence[tuple[float, float]]) -> str:
    """
    Format beat-keyed pairs the way ``#BPMS`` and ``#STOPS`` are written.

    Parameters
    ----------
    values : collections.abc.Sequence[tuple[float, float]]
        ``(beat, value)`` pairs.

    Returns
    -------
    str
        The formatted list.
    """
    return ',\n'.join(f'{beat:.3f}={value:.3f}' for beat, value in values)


def write_sm(charts: Sequence[SimfileChart],
             bpms: Sequence[tuple[float, float]],
             *,
             artist: str = '',
             banner: str = '',
             credit: str = '',
             gap: float = 0.0,
             music: str = '',
             sample_length: float = 15.0,
             sample_start: float = 0.0,
             stops: Sequence[tuple[float, float]] = (),
             subtitle: str = '',
             title: str = '') -> str:
    """
    Render a complete ``.sm`` file.

    Parameters
    ----------
    charts : collections.abc.Sequence[SimfileChart]
        The charts, in the order they should appear.
    bpms : collections.abc.Sequence[tuple[float, float]]
        ``(beat, bpm)`` pairs. A file needs at least one.
    artist : str
        The artist.
    banner : str
        The banner image file name, relative to the simfile.
    credit : str
        The credit field.
    gap : float
        Seconds from the start of the audio to beat 0, written as ``#OFFSET:-gap``.
    music : str
        The audio file name, relative to the simfile.
    sample_length : float
        How long the music-wheel preview runs, in seconds.
    sample_start : float
        Where the music-wheel preview starts, in seconds.
    stops : collections.abc.Sequence[tuple[float, float]]
        ``(beat, seconds)`` pairs.
    subtitle : str
        The subtitle.
    title : str
        The song title.

    Returns
    -------
    str
        The simfile's contents.
    """
    lines = [
        f'#TITLE:{title};', f'#SUBTITLE:{subtitle};', f'#ARTIST:{artist};', '#TITLETRANSLIT:;',
        '#SUBTITLETRANSLIT:;', '#ARTISTTRANSLIT:;', f'#CREDIT:{credit};', f'#BANNER:{banner};',
        '#BACKGROUND:;', '#CDTITLE:;', f'#MUSIC:{music};', f'#OFFSET:{-gap:.3f};',
        f'#SAMPLESTART:{sample_start:.3f};', f'#SAMPLELENGTH:{sample_length:.3f};',
        '#SELECTABLE:YES;', f'#BPMS:{_pairs(bpms)};', f'#STOPS:{_pairs(stops)};', ''
    ]
    for chart in charts:
        lines += [
            f'//--------------- {chart.steps_type} - {chart.difficulty} ----------------',
            '#NOTES:', f'     {chart.steps_type}:', f'     {chart.description}:',
            f'     {chart.difficulty}:', f'     {chart.meter}:', f'     {chart.radar}:',
            chart.notes, ';', ''
        ]
    return '\n'.join(lines)
