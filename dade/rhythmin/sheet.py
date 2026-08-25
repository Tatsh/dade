"""
Reading of the ``sheet_*`` note charts inside ``.orb`` and ``.acv`` song packages.

Both package kinds are ZIPs whose entries are :mod:`BFCodec <dade.rhythmin.bfcodec>` payloads.
The chart entries are ``sheet_es``, ``sheet_n``, ``sheet_h``, and ``sheet_ex``, and the two package
kinds carry completely different chart formats:

* **Standard** (``%09d.orb``, read by ``NoteMng::InitPlayData``): a four-byte header that is a
  little-endian ``float32`` holding the chart's base hi-speed multiplier, followed by 20-byte
  records of ``uint32`` tick, ``uint32`` end tick (greater than the tick for a hold), ``uint8``
  type at +0x8, ``uint16`` value at +0xc whose low byte is the note kind, and six position bytes at
  +0xe that ``MakeNote`` scales into on-screen percentages. The types are 0 note, 1 mark (the BGM
  start), 2 tempo (the value is the BPM), 3 end, and 4 bar line.
* **Arcade** (``ac%09d.acv``, read by ``AcNoteMng::InitPlayData``): a stream of eight-byte units of
  ``uint32`` tick, a pad byte holding the ASCII magic ``E`` in the first unit, ``uint8`` type, and
  ``uint16`` value. The engine parses every unit including the first, whose type and value are a
  real initial-tempo event, and re-stamps the final unit as the type-6 terminator. The types it
  handles are 1 tap (the lane is the value's low nibble), 3 BGM start, 4 tempo, 6 end of chart, 10
  measure boundary, and 11 beat boundary; other types appear in the shipped charts with no handler.

The format is detected from the decrypted payload, with the file extension as the tiebreaker.

:func:`render_strip_image` draws a chart as a DDR-style strip: fixed-height measures wrapped into
columns left to right, one button per tap in its lane, with measure numbers, beat lines, BPM
markers, and BGM-start markers. Arcade charts have nine real lanes. Standard charts are
position-based rather than lane-based, so, as osu!mania does when it converts osu! beatmaps, each
note's judge-target x percentage is bucketed into a chosen number of columns, the button colour
cycles with the note kind, holds become long notes, and the measure grid is synthesised from the
tempo map when the chart carries no bar records.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, NamedTuple
import bisect
import collections
import itertools
import math
import plistlib
import struct
import zipfile

from PIL import Image, ImageDraw, ImageFont

from .bfcodec import decipher
from .render import load_font

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = ('ARCADE_TYPES', 'KIND_SPRITES', 'LANE_SPRITES', 'SPRITE_COLORS', 'STANDARD_TYPES',
           'SUFFIXES', 'SUFFIX_LEVEL_KEYS', 'ArcadeUnit', 'ChartStrip', 'Note', 'Sheet',
           'StandardChart', 'StandardRecord', 'arcade_strip', 'arcade_to_json', 'detect_format',
           'parse_arcade', 'parse_standard', 'read_sheet', 'render_strip_image', 'standard_strip',
           'standard_to_json')

SUFFIXES = ('es', 'ex', 'h', 'n')
"""The chart difficulty suffixes, which name the ``sheet_<suffix>`` entries.

:meta hide-value:
"""
SUFFIX_LEVEL_KEYS: Mapping[str, str] = {
    'es': 'Easy',
    'ex': 'Ex',
    'h': 'Hyper',
    'n': 'Normal',
}
"""Chart suffix to the difficulty-level key it maps to in the package's ``info`` plist.

The arcade info carries all four; a standard ``.orb`` info has no Easy.

:meta hide-value:
"""
STANDARD_TYPES: Mapping[int, str] = {
    0: 'note',
    1: 'mark',
    2: 'tempo',
    3: 'end',
    4: 'bar',
}
"""Standard-chart record type to its readable name.

:meta hide-value:
"""
ARCADE_TYPES: Mapping[int, str] = {
    1: 'tap',
    3: 'bgm-start',
    4: 'tempo',
    6: 'end',
    10: 'measure',
    11: 'beat',
}
"""Arcade-chart unit type to its readable name. Types absent here have no handler in the game.

:meta hide-value:
"""
LANE_SPRITES = (3, 4, 5, 1, 2, 1, 5, 4, 3)
"""Arcade lane to its ``login_popn`` sprite number.

The nine pop'n buttons run white, yellow, green, blue, red, blue, green, yellow, white from left to
right.

:meta hide-value:
"""
KIND_SPRITES = (3, 4, 5, 1, 2)
"""Standard-chart note kind to its sprite number, cycling white, yellow, green, blue, red.

:meta hide-value:
"""
SPRITE_COLORS: Mapping[int, tuple[int, int, int]] = {
    1: (70, 130, 250),
    2: (240, 60, 60),
    3: (235, 235, 235),
    4: (250, 200, 30),
    5: (90, 200, 90),
}
"""Sprite number to the flat colour drawn when the real button sprites are unavailable.

:meta hide-value:
"""

_STANDARD_RECORD_SIZE = 20
_STANDARD_HEADER_SIZE = 4
_STANDARD_TYPE_OFFSET = 8
_STANDARD_VALUE_OFFSET = 0xC
_STANDARD_POSITION = slice(0xE, 0x14)
_STANDARD_TARGET_X = 4
_ARCADE_UNIT_SIZE = 8
_ARCADE_MAGIC = ord('E')
_ARCADE_MAGIC_OFFSET = 4
_ARCADE_LANES = 9
_ARCADE_MIN_SIZE = 16
_STANDARD_MIN_SIZE = 24
_TICKS_PER_MEASURE_AT_ONE_BPM = 240000.0
_MAX_SYNTHESISED_MEASURES = 100000
_DEFAULT_MEASURE_TICKS = 2000
_TYPE_NOTE, _TYPE_MARK, _TYPE_TEMPO, _TYPE_END, _TYPE_BAR = 0, 1, 2, 3, 4
_UNIT_TAP, _UNIT_BGM, _UNIT_TEMPO, _UNIT_END, _UNIT_MEASURE, _UNIT_BEAT = 1, 3, 4, 6, 10, 11
_LANE_PX = 26
_NOTE_SIZE = (24, 22)
_GUTTER = 46
_GAP = 26
_MARGIN = 24
_HEADER = 84
_MEASURE_NUMBER_INSET = 8
_TITLE_STEP = 30
_ARTIST_STEP = 24
_BACKGROUND = (24, 24, 32)
_LINE_COLOR = (150, 150, 165)
_DIM_COLOR = (58, 58, 72)
_LANE_COLOR = (40, 40, 52)
_MEASURE_TEXT = (170, 170, 185)
_TEMPO_COLOR = (255, 90, 210)
_BGM_COLOR = (80, 220, 255)
_TITLE_COLOR = (235, 235, 245)
_ARTIST_COLOR = (190, 190, 205)
_STATS_COLOR = (220, 220, 230)
_SOURCE_COLOR = (140, 140, 155)


class Sheet(NamedTuple):
    """One chart read out of a song package."""

    entry: str
    """Name of the ZIP entry the chart came from."""
    payload: bytes
    """The decrypted chart."""
    encrypted_size: int
    """Size of the entry before deciphering."""
    info: dict[str, Any] | None
    """The package's decrypted ``info`` plist, when it has one that could be read."""


class StandardRecord(NamedTuple):
    """One 20-byte record of a standard chart."""

    tick: int
    """Milliseconds from the start of the chart."""
    end_tick: int
    """End of a hold, equal to :attr:`tick` for an ordinary note."""
    record_type: int
    """The record's :data:`STANDARD_TYPES` value."""
    value: int
    """Type-specific value: the note kind for a note, the BPM for a tempo event."""
    positions: tuple[int, ...]
    """The six position bytes, which ``MakeNote`` scales into on-screen percentages."""
    @property
    def is_hold(self) -> bool:
        """
        Whether this note is held rather than tapped.

        Returns
        -------
        bool
            ``True`` when the record ends later than it starts.
        """
        return self.end_tick > self.tick

    @property
    def kind(self) -> int:
        """
        The note kind, which is the value's low byte.

        Returns
        -------
        int
            The kind.
        """
        return self.value & 0xFF

    @property
    def type_name(self) -> str:
        """
        Readable name of the record's type.

        Returns
        -------
        str
            The :data:`STANDARD_TYPES` name, or a description of the raw value.
        """
        return STANDARD_TYPES.get(self.record_type, f'unknown({self.record_type})')


class StandardChart(NamedTuple):
    """A parsed standard chart."""

    hi_speed: float
    """The base hi-speed multiplier from the four-byte header."""
    records: tuple[StandardRecord, ...]
    """Every record, in file order."""


class ArcadeUnit(NamedTuple):
    """One eight-byte unit of an arcade chart."""

    tick: int
    """Milliseconds from the start of the chart."""
    pad: int
    """The pad byte, which holds the ASCII magic ``E`` in the first unit."""
    unit_type: int
    """The unit's :data:`ARCADE_TYPES` value."""
    value: int
    """Type-specific value: the lane in the low nibble for a tap, the BPM for a tempo event."""
    @property
    def lane(self) -> int:
        """
        The tap's lane, which is the value's low nibble.

        Returns
        -------
        int
            The lane.
        """
        return self.value & 0xF

    @property
    def type_name(self) -> str:
        """
        Readable name of the unit's type.

        Returns
        -------
        str
            The :data:`ARCADE_TYPES` name, or a description of the raw value, which the game has no
            handler for.
        """
        return ARCADE_TYPES.get(self.unit_type, f'unhandled({self.unit_type})')


class Note(NamedTuple):
    """One drawable note in a strip chart."""

    tick: int
    """Where the note starts."""
    end_tick: int
    """Where the note ends, equal to :attr:`tick` for a tap."""
    lane: int
    """The column the note is drawn in."""
    sprite: int
    """The :data:`SPRITE_COLORS` sprite number the note is drawn with."""


class ChartStrip(NamedTuple):
    """A chart reduced to what the strip renderer needs, whichever format it came from."""

    notes: tuple[Note, ...]
    """Every drawable note."""
    lane_count: int
    """How many columns the strip has."""
    measure_ticks: tuple[int, ...]
    """Tick of each measure line, ascending."""
    beat_ticks: tuple[int, ...]
    """Tick of each beat line, ascending."""
    tempos: tuple[tuple[int, int], ...]
    """Tick and BPM of each tempo change."""
    bgm_ticks: tuple[int, ...]
    """Tick of each BGM-start marker."""
    end_ticks: tuple[int, ...]
    """Tick of each end-of-chart marker."""


def read_sheet(package: Path, suffix: str, key: bytes | None = None) -> Sheet:
    """
    Read and decrypt one chart, and the package's song metadata, from a ``.orb`` or ``.acv``.

    Parameters
    ----------
    package : pathlib.Path
        The song package.
    suffix : str
        The difficulty suffix, one of :data:`SUFFIXES`.
    key : bytes | None
        The cipher key, defaulting to :py:func:`dade.rhythmin.bfcodec.default_key`.

    Returns
    -------
    Sheet
        The decrypted chart and the package's ``info`` plist, where one could be read.

    Raises
    ------
    KeyError
        If the package holds no chart of that difficulty. A chart whose length trailer does not
        check out raises the :py:class:`ValueError` :py:func:`dade.rhythmin.bfcodec.decipher`
        raises.
    """
    entry = f'sheet_{suffix}'
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if entry not in names:
            present = ', '.join(name for name in names if name.startswith('sheet_')) or 'none'
            msg = f'No {entry!r} in {package}; the sheets present are {present}.'
            raise KeyError(msg)
        data = archive.read(entry)
        info: dict[str, Any] | None = None
        if 'info' in names:
            try:
                loaded = plistlib.loads(decipher(archive.read('info'), key))
            except (ValueError, plistlib.InvalidFileException):
                loaded = None
            info = loaded if isinstance(loaded, dict) else None
    return Sheet(entry, decipher(data, key), len(data), info)


def detect_format(payload: bytes, extension: str = '') -> Literal['arcade', 'standard']:
    """
    Classify a decrypted chart as arcade or standard.

    Parameters
    ----------
    payload : bytes
        The decrypted chart.
    extension : str
        The package's file extension, used only to break a tie when the payload could be either.

    Returns
    -------
    Literal['arcade', 'standard']
        The format.

    Raises
    ------
    ValueError
        If the payload is neither, which usually means it was decrypted with the wrong key.
    """
    arcade = (len(payload) >= _ARCADE_MIN_SIZE and len(payload) % _ARCADE_UNIT_SIZE == 0
              and payload[4] == _ARCADE_MAGIC)
    standard = (len(payload) >= _STANDARD_MIN_SIZE
                and (len(payload) - _STANDARD_HEADER_SIZE) % _STANDARD_RECORD_SIZE == 0)
    if arcade and standard:
        return 'arcade' if extension.lower() == '.acv' else 'standard'
    if arcade:
        return 'arcade'
    if standard:
        return 'standard'
    magic = (f', byte {_ARCADE_MAGIC_OFFSET} is {payload[_ARCADE_MAGIC_OFFSET]:#04x}'
             if len(payload) > _ARCADE_MAGIC_OFFSET else '')
    msg = f'Unrecognised chart payload of {len(payload)} bytes{magic}.'
    raise ValueError(msg)


def parse_standard(payload: bytes) -> StandardChart:
    """
    Parse a standard chart.

    Parameters
    ----------
    payload : bytes
        The decrypted chart.

    Returns
    -------
    StandardChart
        The header's hi-speed multiplier and every record.
    """
    count = (len(payload) - _STANDARD_HEADER_SIZE) // _STANDARD_RECORD_SIZE
    records: list[StandardRecord] = []
    for index in range(count):
        offset = _STANDARD_HEADER_SIZE + index * _STANDARD_RECORD_SIZE
        tick, end_tick = struct.unpack_from('<II', payload, offset)
        records.append(
            StandardRecord(
                tick, end_tick, payload[offset + _STANDARD_TYPE_OFFSET],
                struct.unpack_from('<H', payload, offset + _STANDARD_VALUE_OFFSET)[0],
                tuple(payload[offset + _STANDARD_POSITION.start:offset + _STANDARD_POSITION.stop])))
    return StandardChart(struct.unpack_from('<f', payload, 0)[0], tuple(records))


def parse_arcade(payload: bytes) -> tuple[ArcadeUnit, ...]:
    """
    Parse an arcade chart.

    Parameters
    ----------
    payload : bytes
        The decrypted chart.

    Returns
    -------
    tuple[ArcadeUnit, ...]
        Every unit, the magic-bearing first one included.
    """
    return tuple(
        ArcadeUnit(
            struct.unpack_from('<I', payload, offset)[0], payload[offset + 4], payload[offset + 5],
            struct.unpack_from('<H', payload, offset + 6)[0])
        for offset in range(0,
                            len(payload) - (_ARCADE_UNIT_SIZE - 1), _ARCADE_UNIT_SIZE))


def _bpm_range(tempos: Sequence[tuple[int, int]]) -> list[int] | None:
    """
    Summarise a tempo map's range.

    Parameters
    ----------
    tempos : Sequence[tuple[int, int]]
        Tick and BPM of each tempo change.

    Returns
    -------
    list[int] | None
        The lowest and highest BPM, or ``None`` when the chart has no tempo events.
    """
    if not tempos:
        return None
    values = [bpm for _, bpm in tempos]
    return [min(values), max(values)]


def standard_to_json(chart: StandardChart, *, summary_only: bool = False) -> dict[str, Any]:
    """
    Render a parsed standard chart as JSON-ready values.

    Parameters
    ----------
    chart : StandardChart
        The chart to render.
    summary_only : bool
        Leave out the per-record list.

    Returns
    -------
    dict[str, Any]
        The rendered chart.
    """
    tempos = [(r.tick, r.value) for r in chart.records if r.record_type == _TYPE_TEMPO]
    notes = [r for r in chart.records if r.record_type == _TYPE_NOTE]
    marks = [r.tick for r in chart.records if r.record_type == _TYPE_MARK]
    ends = [r.tick for r in chart.records if r.record_type == _TYPE_END]
    rendered: dict[str, Any] = {
        'format': 'standard',
        'hiSpeed': chart.hi_speed,
        'recordCount': len(chart.records),
        'summary': {
            'notes':
                len(notes),
            'holds':
                sum(1 for r in notes if r.is_hold),
            'bars':
                sum(1 for r in chart.records if r.record_type == _TYPE_BAR),
            'tempoEvents':
                len(tempos),
            'markTick':
                marks[-1] if marks else None,
            'endTick':
                ends[-1] if ends else None,
            'bpmRange':
                _bpm_range(tempos),
            'tempoMap': [{
                'tick': tick,
                'bpm': bpm
            } for tick, bpm in tempos],
            'typeHistogram':
                dict(sorted(collections.Counter(r.record_type for r in chart.records).items())),
        },
    }
    if summary_only:
        return rendered
    rendered['records'] = [{
        'index':
            index,
        'tick':
            record.tick,
        'type':
            record.record_type,
        'typeName':
            record.type_name,
        **({
            'endTick': record.end_tick,
            'hold': record.is_hold,
            'kind': record.kind,
            'kindHigh': record.value >> 8,
            'positions': list(record.positions),
        } if record.record_type == _TYPE_NOTE else {}),
        **({
            'bpm': record.value
        } if record.record_type == _TYPE_TEMPO else {}),
    } for index, record in enumerate(chart.records)]
    return rendered


def arcade_to_json(units: Sequence[ArcadeUnit], *, summary_only: bool = False) -> dict[str, Any]:
    """
    Render a parsed arcade chart as JSON-ready values.

    Parameters
    ----------
    units : Sequence[ArcadeUnit]
        The chart's units.
    summary_only : bool
        Leave out the per-unit list.

    Returns
    -------
    dict[str, Any]
        The rendered chart.
    """
    taps = [unit for unit in units if unit.unit_type == _UNIT_TAP]
    tempos = [(unit.tick, unit.value) for unit in units if unit.unit_type == _UNIT_TEMPO]
    bgm = [unit.tick for unit in units if unit.unit_type == _UNIT_BGM]
    ends = [unit.tick for unit in units if unit.unit_type == _UNIT_END]
    lanes = collections.Counter(unit.lane for unit in taps)
    rendered: dict[str, Any] = {
        'format': 'arcade',
        'unitCount': len(units),
        'summary': {
            'taps': len(taps),
            'measures': sum(1 for unit in units if unit.unit_type == _UNIT_MEASURE),
            'beats': sum(1 for unit in units if unit.unit_type == _UNIT_BEAT),
            'tempoEvents': len(tempos),
            'bgmStartTick': bgm[-1] if bgm else None,
            'endTick': ends[-1] if ends else None,
            'bpmRange': _bpm_range(tempos),
            'tempoMap': [{
                'tick': tick,
                'bpm': bpm
            } for tick, bpm in tempos],
            'tapsPerLane': dict(sorted(lanes.items())),
            'typeHistogram': dict(sorted(collections.Counter(u.unit_type for u in units).items())),
        },
    }
    if summary_only:
        return rendered
    rendered['units'] = [{
        'index': index,
        'tick': unit.tick,
        'type': unit.unit_type,
        'typeName': unit.type_name,
        'value': unit.value,
        **({
            'lane': unit.lane
        } if unit.unit_type == _UNIT_TAP else {}),
        **({
            'bpm': unit.value
        } if unit.unit_type == _UNIT_TEMPO else {}),
        **({
            'pad': unit.pad
        } if unit.pad else {}),
    } for index, unit in enumerate(units)]
    return rendered


def arcade_strip(units: Sequence[ArcadeUnit]) -> ChartStrip:
    """
    Reduce an arcade chart to what the strip renderer needs.

    Parameters
    ----------
    units : Sequence[ArcadeUnit]
        The chart's units.

    Returns
    -------
    ChartStrip
        The reduced chart.

    Raises
    ------
    ValueError
        If the chart carries no measure events, so there is no grid to lay it out against.
    """
    measures = sorted({unit.tick for unit in units if unit.unit_type == _UNIT_MEASURE})
    if not measures:
        msg = 'The chart has no measure events to lay out against.'
        raise ValueError(msg)
    return ChartStrip(
        tuple(
            Note(unit.tick, unit.tick, unit.lane, LANE_SPRITES[unit.lane]) for unit in units
            if unit.unit_type == _UNIT_TAP and unit.lane < _ARCADE_LANES), _ARCADE_LANES,
        tuple(measures), tuple(sorted({u.tick
                                       for u in units if u.unit_type == _UNIT_BEAT})),
        tuple((u.tick, u.value) for u in units if u.unit_type == _UNIT_TEMPO),
        tuple(u.tick for u in units if u.unit_type == _UNIT_BGM),
        tuple(u.tick for u in units if u.unit_type == _UNIT_END))


def _synthesise_measures(tempos: Sequence[tuple[int, int]], last_tick: int) -> list[int]:
    """
    Build a measure grid from a tempo map, for a chart with no bar records.

    Ticks are milliseconds, so a 4/4 measure lasts ``240000 / BPM`` of them.

    Parameters
    ----------
    tempos : Sequence[tuple[int, int]]
        Tick and BPM of each tempo change.
    last_tick : int
        The chart's final tick, which closes the last segment.

    Returns
    -------
    list[int]
        The measure ticks.
    """
    measures: list[int] = []
    events = [*sorted(tempos), (last_tick, 0)]
    for (start, bpm), (end, _) in itertools.pairwise(events):
        if bpm <= 0:
            continue
        length = _TICKS_PER_MEASURE_AT_ONE_BPM / bpm
        index = 0
        while start + index * length < end and len(measures) < _MAX_SYNTHESISED_MEASURES:
            measures.append(round(start + index * length))
            index += 1
    return measures


def standard_strip(chart: StandardChart, lanes: int = 7) -> ChartStrip:
    """
    Reduce a standard chart to what the strip renderer needs, osu!mania style.

    The standard game is position-based rather than lane-based, so each note's judge-target x
    percentage is bucketed into ``lanes`` columns, the button colour cycles with the note kind, and
    a hold becomes a long note. The measure grid comes from the chart's bar records when it has
    any, and is otherwise synthesised from the tempo map.

    Parameters
    ----------
    chart : StandardChart
        The chart to reduce.
    lanes : int
        How many columns to bucket the notes into.

    Returns
    -------
    ChartStrip
        The reduced chart.

    Raises
    ------
    ValueError
        If ``lanes`` is not positive, or the chart has neither bar records nor a usable tempo map.
    """
    if lanes <= 0:
        msg = f'The column count must be positive, not {lanes}.'
        raise ValueError(msg)
    notes: list[Note] = []
    tempos: list[tuple[int, int]] = []
    bars: list[int] = []
    bgm_ticks: list[int] = []
    end_ticks: list[int] = []
    for record in chart.records:
        match record.record_type:
            case 0:
                lane = min(lanes - 1, record.positions[_STANDARD_TARGET_X] * lanes // 100)
                notes.append(
                    Note(record.tick, max(record.end_tick, record.tick), lane,
                         KIND_SPRITES[record.kind % len(KIND_SPRITES)]))
            case 1:
                bgm_ticks.append(record.tick)
            case 2:
                tempos.append((record.tick, record.value))
            case 3:
                end_ticks.append(record.tick)
            case 4:
                bars.append(record.tick)
            case _:
                pass
    if bars:
        measures = sorted(set(bars))
    else:
        measures = _synthesise_measures(tempos, max([*end_ticks, *(n.end_tick for n in notes), 0]))
    if not measures:
        msg = 'The chart has no bar records and no usable tempo map.'
        raise ValueError(msg)
    beats = [
        round(first + (second - first) * quarter / 4)
        for first, second in itertools.pairwise(measures) for quarter in (1, 2, 3)
    ]
    return ChartStrip(tuple(notes), lanes, tuple(measures), tuple(beats), tuple(tempos),
                      tuple(bgm_ticks), tuple(end_ticks))


def _load_button_sprites(directory: Path, size: tuple[int, int]) -> dict[int, Image.Image]:
    """
    Load the game's five pop'n button sprites, scaled to the note size.

    Parameters
    ----------
    directory : pathlib.Path
        A directory holding ``login_popn01@2x.png`` through ``login_popn05@2x.png``.
    size : tuple[int, int]
        The width and height to scale each sprite to.

    Returns
    -------
    dict[int, PIL.Image.Image]
        Sprite number to the scaled image.

    Raises
    ------
    ValueError
        If any of the five sprites cannot be read.
    """
    sprites: dict[int, Image.Image] = {}
    for number in sorted(SPRITE_COLORS):
        path = directory / f'login_popn{number:02d}@2x.png'
        try:
            with Image.open(path) as sprite:
                sprites[number] = sprite.convert('RGBA').resize(size, Image.Resampling.LANCZOS)
        except OSError as e:
            msg = f'Cannot load the button sprite `{path}`: {e}'
            raise ValueError(msg) from e
    return sprites


class _Layout(NamedTuple):
    """
    Geometry of one rendered strip chart.

    Every measure is one layout unit whatever its tick span, which is the DDR-chart convention, so
    a tempo change does not distort the grid.
    """

    strip: ChartStrip
    """The chart being drawn."""
    total_measures: int
    """How many measures the chart occupies, the final partial one included."""
    measures_per_column: int
    """How many measures each column holds before wrapping."""
    measure_px: int
    """Height of one measure in pixels."""
    last_length: int
    """Median measure length in ticks, used to extrapolate past the final measure line."""
    top_down: bool
    """Read each column top to bottom instead of bottom to top."""
    @property
    def column_height(self) -> int:
        """
        Height of a full column in pixels.

        Returns
        -------
        int
            The height.
        """
        return self.measures_per_column * self.measure_px

    def column_measures(self, column: int) -> int:
        """
        How many measures one column holds, which is fewer for the last one.

        Parameters
        ----------
        column : int
            The column's index.

        Returns
        -------
        int
            The measure count.
        """
        return min(self.measures_per_column,
                   self.total_measures - column * self.measures_per_column)

    def column_x(self, column: int) -> int:
        """
        Left edge of one column's strip.

        Parameters
        ----------
        column : int
            The column's index.

        Returns
        -------
        int
            The x coordinate.
        """
        return _MARGIN + column * (_GUTTER + self.strip_width + _GAP) + _GUTTER

    @property
    def columns(self) -> int:
        """
        How many columns the chart wraps into.

        Returns
        -------
        int
            The column count.
        """
        return math.ceil(self.total_measures / self.measures_per_column)

    def frame(self, column: int) -> tuple[int, int]:
        """
        Top and bottom of one column's frame.

        A partial final column is bottom-aligned when reading bottom-up, so bar 1 of every column
        shares a bottom line.

        Parameters
        ----------
        column : int
            The column's index.

        Returns
        -------
        tuple[int, int]
            The top and bottom y coordinates.
        """
        measures = self.column_measures(column)
        if self.top_down:
            return self.top, self.top + measures * self.measure_px
        return (self.top + self.column_height - measures * self.measure_px,
                self.top + self.column_height)

    @property
    def height(self) -> int:
        """
        Height of the whole image in pixels.

        Returns
        -------
        int
            The height.
        """
        return _MARGIN * 2 + _HEADER + self.column_height

    def measure_position(self, tick: int) -> float:
        """
        Locate a tick in measures, fractionally.

        Parameters
        ----------
        tick : int
            The tick to locate.

        Returns
        -------
        float
            The measure ordinal plus the fraction of the way through it.
        """
        index = bisect.bisect_right(self.strip.measure_ticks, tick) - 1
        if index < 0:
            return 0.0
        start = self.strip.measure_ticks[index]
        length = (self.strip.measure_ticks[index + 1] - start if index +
                  1 < len(self.strip.measure_ticks) else self.last_length)
        return index + ((tick - start) / length if length > 0 else 0.0)

    def place(self, tick: int) -> tuple[int, int]:
        """
        Locate a tick on the image.

        Parameters
        ----------
        tick : int
            The tick to place.

        Returns
        -------
        tuple[int, int]
            The left edge of its column's strip and its y coordinate.
        """
        position = min(self.measure_position(tick), float(self.total_measures))
        column = min(int(position // self.measures_per_column), self.columns - 1)
        relative = min(position - column * self.measures_per_column,
                       float(self.column_measures(column)))
        y = (self.top + relative * self.measure_px if self.top_down else self.top +
             self.column_height - relative * self.measure_px)
        return self.column_x(column), round(y)

    @property
    def strip_width(self) -> int:
        """
        Width of one column's lanes in pixels.

        Returns
        -------
        int
            The width.
        """
        return _LANE_PX * self.strip.lane_count

    @property
    def top(self) -> int:
        """
        Top of the first column's frame.

        The title block is a header when reading top-down and a footer otherwise.

        Returns
        -------
        int
            The y coordinate.
        """
        return _MARGIN + (_HEADER if self.top_down else 0)

    @property
    def width(self) -> int:
        """
        Width of the whole image in pixels.

        Returns
        -------
        int
            The width.
        """
        return (_MARGIN * 2 + self.columns * (_GUTTER + self.strip_width) +
                (self.columns - 1) * _GAP)


def _draw_frames(draw: ImageDraw.ImageDraw, layout: _Layout,
                 font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> None:
    """
    Draw each column's lane separators, measure lines, and measure numbers.

    Parameters
    ----------
    draw : PIL.ImageDraw.ImageDraw
        The drawing context.
    layout : _Layout
        The chart's geometry.
    font : PIL.ImageFont.FreeTypeFont
        The font measure numbers are drawn with.
    """
    for column in range(layout.columns):
        x = layout.column_x(column)
        measures = layout.column_measures(column)
        frame_top, frame_bottom = layout.frame(column)
        for lane in range(1, layout.strip.lane_count):
            draw.line([(x + lane * _LANE_PX, frame_top), (x + lane * _LANE_PX, frame_bottom)],
                      fill=_LANE_COLOR)
        for measure in range(measures + 1):
            y = frame_top + measure * layout.measure_px
            draw.line([(x, y), (x + layout.strip_width, y)], fill=_LINE_COLOR)
        for measure in range(measures):
            text = str(column * layout.measures_per_column + measure + 1)
            y = (frame_top + measure * layout.measure_px + 3 if layout.top_down else frame_bottom -
                 measure * layout.measure_px - 20)
            draw.text((x - _MEASURE_NUMBER_INSET - draw.textlength(text, font=font), y),
                      text,
                      fill=_MEASURE_TEXT,
                      font=font)
        draw.rectangle([x, frame_top, x + layout.strip_width, frame_bottom], outline=_LINE_COLOR)


def _draw_markers(draw: ImageDraw.ImageDraw, layout: _Layout,
                  font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> None:
    """
    Draw the beat lines, tempo changes, and BGM-start markers.

    Parameters
    ----------
    draw : PIL.ImageDraw.ImageDraw
        The drawing context.
    layout : _Layout
        The chart's geometry.
    font : PIL.ImageFont.FreeTypeFont
        The font BPM labels are drawn with.
    """
    measures = set(layout.strip.measure_ticks)
    for tick in layout.strip.beat_ticks:
        if tick in measures:
            continue
        x, y = layout.place(tick)
        draw.line([(x + 1, y), (x + layout.strip_width - 1, y)], fill=_DIM_COLOR)
    for tick, bpm in layout.strip.tempos:
        x, y = layout.place(tick)
        draw.line([(x, y), (x + layout.strip_width, y)], fill=_TEMPO_COLOR, width=2)
        draw.text((x + layout.strip_width + 4, y - 8), str(bpm), fill=_TEMPO_COLOR, font=font)
    for tick in layout.strip.bgm_ticks:
        x, y = layout.place(tick)
        draw.line([(x, y), (x + layout.strip_width, y)], fill=_BGM_COLOR, width=2)


def _draw_notes(image: Image.Image, draw: ImageDraw.ImageDraw, layout: _Layout,
                sprites: dict[int, Image.Image] | None) -> int:
    """
    Draw every note, with a body bar between the ends of a long note.

    Parameters
    ----------
    image : PIL.Image.Image
        The image, which button sprites are pasted into.
    draw : PIL.ImageDraw.ImageDraw
        The drawing context.
    layout : _Layout
        The chart's geometry.
    sprites : dict[int, PIL.Image.Image] | None
        The button sprites, or ``None`` to draw flat coloured discs.

    Returns
    -------
    int
        How many long notes were drawn.
    """
    def button(centre_x: int, y: int, sprite: int) -> None:
        if sprites is not None:
            image.paste(sprites[sprite], (centre_x - _NOTE_SIZE[0] // 2, y - _NOTE_SIZE[1] // 2),
                        sprites[sprite])
        else:
            draw.ellipse([centre_x - 10, y - 9, centre_x + 10, y + 9],
                         fill=SPRITE_COLORS[sprite],
                         outline=(0, 0, 0))

    holds = 0
    for note in layout.strip.notes:
        if note.lane >= layout.strip.lane_count:
            continue
        x, y = layout.place(note.tick)
        centre_x = x + note.lane * _LANE_PX + _LANE_PX // 2
        if note.end_tick > note.tick:
            # A long note: a dimmed body bar from head to tail with a button on each end, which is
            # the osu!mania hold-note look.
            holds += 1
            _, tail_y = layout.place(note.end_tick)
            body = tuple(channel // 2 for channel in SPRITE_COLORS[note.sprite])
            draw.rectangle([centre_x - 6, min(y, tail_y), centre_x + 6, max(y, tail_y)], fill=body)
            button(centre_x, tail_y, note.sprite)
        button(centre_x, y, note.sprite)
    return holds


def _bpm_text(tempos: Sequence[tuple[int, int]]) -> str:
    """
    Summarise a tempo map for the stats line.

    Parameters
    ----------
    tempos : Sequence[tuple[int, int]]
        Tick and BPM of each tempo change.

    Returns
    -------
    str
        One BPM, a range, or a question mark when the chart has no tempo events.
    """
    values = [bpm for _, bpm in tempos]
    if not values:
        return '?'
    if min(values) == max(values):
        return str(values[0])
    return f'{min(values)}-{max(values)}'


def _draw_titles(draw: ImageDraw.ImageDraw, layout: _Layout, holds: int, *, source: str,
                 title: str | None, artist: str | None, level: int | None) -> None:
    """
    Draw the title block and the provenance line.

    Parameters
    ----------
    draw : PIL.ImageDraw.ImageDraw
        The drawing context.
    layout : _Layout
        The chart's geometry.
    holds : int
        How many long notes were drawn, which the stats line reports.
    source : str
        A provenance line drawn in the bottom corner.
    title : str | None
        The song's title.
    artist : str | None
        The song's artist or genre.
    level : int | None
        The chart's difficulty level.
    """
    font, sub_font, header_font = load_font(14), load_font(15), load_font(21)
    text_y = _MARGIN if layout.top_down else layout.top + layout.column_height + 10
    if title:
        draw.text((_MARGIN, text_y), title, fill=_TITLE_COLOR, font=header_font)
        text_y += _TITLE_STEP
    if artist:
        draw.text((_MARGIN, text_y), artist, fill=_ARTIST_COLOR, font=sub_font)
        text_y += _ARTIST_STEP
    stats = [f'BPM: {_bpm_text(layout.strip.tempos)}']
    if level:
        stats.append(f'Level: {level}')
    stats.append(f'Taps: {len(layout.strip.notes)}')
    if holds:
        stats.append(f'Holds: {holds}')
    stats.append(f'Measures: {layout.total_measures}')
    draw.text((_MARGIN, text_y), '    '.join(stats), fill=_STATS_COLOR, font=sub_font)
    draw.text(
        (layout.width - _MARGIN - draw.textlength(source, font=font), layout.height - _MARGIN + 3),
        source,
        fill=_SOURCE_COLOR,
        font=font)


def render_strip_image(strip: ChartStrip,
                       path: Path,
                       *,
                       source: str,
                       title: str | None = None,
                       artist: str | None = None,
                       level: int | None = None,
                       buttons_dir: Path | None = None,
                       beat_px: int = 48,
                       measures_per_column: int = 16,
                       top_down: bool = False) -> tuple[int, int]:
    """
    Render a chart as a DDR-style strip image.

    Measures are fixed-height boxes wrapped into columns left to right, and each note is drawn as a
    pop'n button in its lane with a long-note body when it is held. Reading bottom to top, the
    default, mirrors the game's downward note fall, so bar 1 sits at the bottom left and the title
    block becomes a footer.

    Parameters
    ----------
    strip : ChartStrip
        The reduced chart to draw.
    path : pathlib.Path
        Where to write the image.
    source : str
        A provenance line drawn in the bottom corner.
    title : str | None
        The song's title.
    artist : str | None
        The song's artist or genre.
    level : int | None
        The chart's difficulty level.
    buttons_dir : pathlib.Path | None
        A directory holding the game's ``login_popn01..05@2x.png`` sprites, to draw taps as real
        pop'n buttons instead of flat coloured discs.
    beat_px : int
        Height of one beat in pixels, so a measure is four times this.
    measures_per_column : int
        How many measures each column holds before wrapping.
    top_down : bool
        Read each column top to bottom instead of bottom to top.

    Returns
    -------
    tuple[int, int]
        The image's width and height in pixels.

    Raises
    ------
    ValueError
        If the chart has no measure grid. Button sprites that cannot be read raise the
        :py:class:`ValueError` the sprite loader raises.
    """
    if not strip.measure_ticks:
        msg = 'The chart has no measure grid to lay out against.'
        raise ValueError(msg)
    # Ticks past the final measure line extrapolate with the median measure length.
    gaps = sorted(second - first for first, second in itertools.pairwise(strip.measure_ticks)
                  if second > first)
    layout = _Layout(strip, 1, measures_per_column, beat_px * 4,
                     gaps[len(gaps) // 2] if gaps else _DEFAULT_MEASURE_TICKS, top_down)
    last_tick = max(
        [*(note.end_tick for note in strip.notes), *strip.end_ticks, strip.measure_ticks[-1]])
    layout = layout._replace(total_measures=int(layout.measure_position(last_tick)) + 1)
    image = Image.new('RGB', (layout.width, layout.height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = load_font(14)
    _draw_frames(draw, layout, font)
    _draw_markers(draw, layout, font)
    holds = _draw_notes(
        image, draw, layout,
        None if buttons_dir is None else _load_button_sprites(buttons_dir, _NOTE_SIZE))
    _draw_titles(draw, layout, holds, source=source, title=title, artist=artist, level=level)
    image.save(path)
    return layout.width, layout.height
