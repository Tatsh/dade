"""
Konami's ``SSQ`` step chart container, shared by the *Dance Dance Revolution* titles.

A file is a flat run of chunks, each ``int32 length | int16 type | int16 parameter |
int32 count | data``, where ``length`` counts the header. Four zero bytes end the file. Two chunk
types carry anything this module needs: type 1 is the tempo map and type 3 is a chart. Type 2 is a
trigger list whose meaning is unknown, and it is skipped along with anything else.

A chart chunk's parameter packs three fields. The low nibble is the panel count, so 0x14 is a
four-panel single chart and 0x18 an eight-panel double; the high byte is the difficulty; the
remaining nibble is a division that every observed chart sets to 1.

The note payload is ``int32 ticks[count]`` then ``uint8 steps[count]``, and after those, at the
next **even** offset, two bytes per freeze marker. Only the freeze block is two-byte aligned; the
chunk as a whole is padded to a four-byte boundary. A step byte is a panel bitmask whose bits 0-3
are player one's left, down, up, and right, and whose bits 4-7 are player two's. ``0x00`` marks the
**end** of a freeze and consumes one ``(panel mask, kind)`` pair; the note that begins it is the
most recent earlier one using the same panel. ``0xFF`` is a shock arrow, which becomes a row of
mines.

A measure is 4096 ticks, so a beat is 1024. The tempo chunk holds ``int32 beats[count]`` followed
by ``int32 times[count]``, the times counted in units of one ``parameter``-th of a second. Between
two entries the tempo is ``(delta_beats / 4096) * 240 * parameter / delta_times``, and two entries
sharing a beat are a stop lasting ``delta_times / parameter`` seconds instead.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct

from destin.common.exceptions import InvalidFormatError
from destin.common.stepmania import quantize_measures

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = (
    'BEATS_PER_MEASURE',
    'DIFFICULTY_NAMES',
    'FREEZE_MARKER',
    'SHOCK_MARKER',
    'SSQ',
    'STEPS_TYPES',
    'TICKS_PER_BEAT',
    'TICKS_PER_MEASURE',
    'Chart',
    'TempoMap',
    'chart_notes',
    'parse_ssq',
)

TICKS_PER_MEASURE = 4096
"""Ticks one measure spans.

:meta hide-value:
"""
TICKS_PER_BEAT = 1024
"""Ticks one beat spans.

:meta hide-value:
"""
BEATS_PER_MEASURE = TICKS_PER_MEASURE // TICKS_PER_BEAT
"""Beats one measure holds.

:meta hide-value:
"""
FREEZE_MARKER = 0x00
"""Step byte marking the end of a freeze arrow.

:meta hide-value:
"""
SHOCK_MARKER = 0xFF
"""Step byte marking a shock arrow, which becomes a row of mines.

:meta hide-value:
"""
DIFFICULTY_NAMES = {1: 'Easy', 2: 'Medium', 3: 'Hard', 4: 'Beginner', 6: 'Challenge'}
"""SSQ difficulty code to StepMania difficulty name.

Codes 1, 2, and 3 are Konami's Basic, Standard, and Heavy.

:meta hide-value:
"""
STEPS_TYPES = {4: 'dance-single', 8: 'dance-double'}
"""Panel count to StepMania steps type.

:meta hide-value:
"""

_CHUNK_HEADER = 8
_WORD = 4
_TYPE_TEMPO = 1
_TYPE_STEP = 3
_FREEZE_KIND = 0x01
_PANEL_BITS = 8
_QUARTERS_PER_MINUTE = 240
_TOLERANCE = 1e-6


def _columns(mask: int, panels: int) -> Iterator[int]:
    """
    Yield the column indices a panel bitmask selects.

    Parameters
    ----------
    mask : int
        The panel bitmask.
    panels : int
        How many panels the chart uses.

    Yields
    ------
    int
        Each selected column.
    """
    for column in range(min(panels, _PANEL_BITS)):
        if mask & 1 << column:
            yield column


class TempoMap(NamedTuple):
    """The tempo map from a type 1 chunk."""

    frames_per_second: int
    """The chunk parameter, the unit the times are counted in."""
    beats: tuple[int, ...]
    """Tick positions."""
    times: tuple[int, ...]
    """Elapsed time at each tick position."""
    def bpms(self) -> tuple[tuple[float, float], ...]:
        """
        Read the tempo changes off the map.

        Entries sharing a tick are stops rather than tempo changes and are left to
        :py:meth:`stops`. A tempo equal to the one before it is dropped, so a chart of constant
        tempo yields a single entry.

        Returns
        -------
        tuple[tuple[float, float], ...]
            ``(beat, bpm)`` pairs in beat order, never empty.
        """
        out: list[tuple[float, float]] = []
        for index in range(len(self.beats) - 1):
            delta_beats = self.beats[index + 1] - self.beats[index]
            delta_times = self.times[index + 1] - self.times[index]
            if delta_beats <= 0 or delta_times <= 0:
                continue
            bpm = ((delta_beats / TICKS_PER_MEASURE) * _QUARTERS_PER_MINUTE *
                   self.frames_per_second / delta_times)
            if out and abs(out[-1][1] - bpm) < _TOLERANCE:
                continue
            out.append((self.beats[index] / TICKS_PER_BEAT, bpm))
        return tuple(out) or ((0.0, 0.0),)

    def stops(self) -> tuple[tuple[float, float], ...]:
        """
        Read the stops off the map.

        Returns
        -------
        tuple[tuple[float, float], ...]
            ``(beat, seconds)`` pairs in beat order.
        """
        return tuple(
            (self.beats[index] / TICKS_PER_BEAT,
             (self.times[index + 1] - self.times[index]) / self.frames_per_second)
            for index in range(len(self.beats) - 1)
            if self.beats[index + 1] == self.beats[index] and self.times[index +
                                                                         1] > self.times[index])


class Chart(NamedTuple):
    """One chart, from a type 3 chunk."""

    parameter: int
    """The chunk parameter, packing the difficulty, panel count, and division."""
    ticks: tuple[int, ...]
    """Tick position of every entry, freeze markers included."""
    steps: bytes
    """Panel bitmask of every entry."""
    freezes: tuple[tuple[int, int], ...]
    """The ``(panel mask, kind)`` pairs, one per freeze marker, in order."""
    @property
    def difficulty(self) -> int:
        """
        The SSQ difficulty code.

        Returns
        -------
        int
            The code, 1 to 6.
        """
        return self.parameter >> 8

    @property
    def division(self) -> int:
        """
        The division nibble, which every observed chart sets to 1.

        Returns
        -------
        int
            The division.
        """
        return (self.parameter & 0xFF) >> 4

    @property
    def note_count(self) -> int:
        """
        How many entries are real notes rather than freeze markers.

        This is the max combo the game credits for the chart, which counts a jump once.

        Returns
        -------
        int
            The note count.
        """
        return sum(1 for step in self.steps if step != FREEZE_MARKER)

    @property
    def panels(self) -> int:
        """
        The panel count, 4 for single and 8 for double.

        Returns
        -------
        int
            The panel count.
        """
        return self.parameter & 0x0F

    def events(self) -> dict[int, dict[int, str]]:
        """
        Resolve the chart into StepMania note characters.

        Returns
        -------
        dict[int, dict[int, str]]
            ``{tick: {column: character}}`` using ``1`` for a tap, ``2`` and ``3`` for the start
            and end of a freeze, and ``M`` for a mine.
        """
        out: dict[int, dict[int, str]] = {}
        last_tap: dict[int, int] = {}
        freezes = iter(self.freezes)
        for index, step in enumerate(self.steps):
            tick = self.ticks[index]
            if step == FREEZE_MARKER:
                mask, kind = next(freezes, (0, 0))
                if kind != _FREEZE_KIND:
                    continue
                for column in _columns(mask, self.panels):
                    if (start := last_tap.pop(column, None)) is None:
                        continue
                    out.setdefault(start, {})[column] = '2'
                    out.setdefault(tick, {})[column] = '3'
            elif step == SHOCK_MARKER:
                for column in range(self.panels):
                    out.setdefault(tick, {})[column] = 'M'
            else:
                for column in _columns(step, self.panels):
                    out.setdefault(tick, {}).setdefault(column, '1')
                    last_tap[column] = tick
        return out


class SSQ(NamedTuple):
    """A parsed SSQ file."""

    tempo: TempoMap | None
    """The tempo map, if the file has one."""
    charts: tuple[Chart, ...]
    """Every chart, in file order."""


def _parse_step_chunk(parameter: int, body: bytes, count: int) -> Chart:
    """
    Parse one type 3 chunk body.

    Parameters
    ----------
    parameter : int
        The chunk parameter.
    body : bytes
        The chunk after its eight-byte header.
    count : int
        The entry count, the first word of the body.

    Returns
    -------
    Chart
        The parsed chart.
    """
    steps = body[_WORD + _WORD * count:_WORD + 5 * count]
    freeze_start = _WORD + 5 * count + count % 2
    return Chart(
        parameter, struct.unpack_from(f'<{count}I', body, _WORD), steps,
        tuple((body[freeze_start + pair * 2], body[freeze_start + pair * 2 + 1])
              for pair in range(sum(1 for step in steps if step == FREEZE_MARKER))))


def parse_ssq(data: bytes) -> SSQ:
    """
    Parse an SSQ file into its tempo map and charts.

    Chunk types other than the tempo map and the charts are skipped.

    Parameters
    ----------
    data : bytes
        The whole file, already deciphered if its container encrypted it.

    Returns
    -------
    SSQ
        The tempo map and every chart.

    Raises
    ------
    destin.common.exceptions.InvalidFormatError
        If a chunk is too short to hold a count, claims to run past the end of the file, or claims
        more entries than it holds.
    """
    tempo: TempoMap | None = None
    charts: list[Chart] = []
    offset = 0
    while offset + _CHUNK_HEADER <= len(data):
        length, kind, parameter = struct.unpack_from('<IHH', data, offset)
        if length == 0:
            break
        if length < _CHUNK_HEADER + _WORD or offset + length > len(data):
            msg = (f'Chunk at {offset} claims {length} bytes, which does not fit in the '
                   f'{len(data)}-byte file.')
            raise InvalidFormatError(msg)
        body = data[offset + _CHUNK_HEADER:offset + length]
        count = struct.unpack_from('<I', body, 0)[0]
        try:
            if kind == _TYPE_TEMPO:
                tempo = TempoMap(parameter, struct.unpack_from(f'<{count}i', body, _WORD),
                                 struct.unpack_from(f'<{count}i', body, _WORD + _WORD * count))
            elif kind == _TYPE_STEP:
                charts.append(_parse_step_chunk(parameter, body, count))
        except struct.error as e:
            msg = f'Chunk at {offset} of type {kind} claims {count} entries it does not hold.'
            raise InvalidFormatError(msg) from e
        offset += length
    return SSQ(tempo, tuple(charts))


def chart_notes(chart: Chart) -> str:
    """
    Render a chart as StepMania measure blocks.

    Parameters
    ----------
    chart : Chart
        The chart.

    Returns
    -------
    str
        The note data, measures separated by commas.
    """
    return quantize_measures(chart.events(), chart.panels, TICKS_PER_MEASURE)
