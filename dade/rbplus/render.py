"""
Chart images.

A chart records no lane for a note, and the game has no fixed one to record.
``CMusicSheet2::AssignChartLanes`` allocates each ordinary note's lane at run time through
``NoteLaneTracker``, seeded from ``rand()`` when play starts, so one chart lays out differently on
every play. A picture that placed notes across the bar would be inventing the one thing neither the
file nor the game holds still.

What the file does hold is the chain. A note's chain block names the note before it and the note
after it by identifier, with -1 at each end, so walking the links recovers each run in the order it
is struck. A note carrying no chain block stands alone.

The engine's one fixed lane rule is that a chain member inherits the lane of the segment before it,
so a chain runs straight up a single lane. That is what is drawn here. Notes one side strikes
together cannot share a lane, so they take neighbouring ones.

*REFLEC BEAT* is a versus game, so a note also belongs to one of two sides. The two are separate
sets of notes rather than one set divided, so each is drawn on its own and counted on its own.

Each image is a strip. Time runs **upward**, the way the notes fall, so the start of the tune is at
the bottom of a column and the columns read left to right. One column holds
:py:data:`SECONDS_PER_COLUMN` seconds, ruled on every quarter note when the tune's tempo is known.

A note left to choose its own target is green, each note of a chain is joined to the next by a
line, and a speed change rules its column across. A hold extends as a bar to the moment it is
released, capped where it ends. A slide draws the track the finger takes, from the note across to
each of its waypoints. The image carries a drawn legend saying so.

A note's route selector decides whether the tracker ever sees it. One naming a lane, 0 to 6, comes
straight down into that lane and is not randomised: that is every slide and every vertical note. One
naming 7, 8, or 9 is aimed at an alternative target and drawn green. Only a note naming nothing is
laid out from the seed.

Which notes are green follows ``AssignGreenTargets``, whose availability bitmap starts with the
seven lanes set and three further slots clear. Those three are the alternative targets, and a note
is green when its route selector names one of them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import itertools
import math
import operator
import random

from PIL import Image, ImageDraw

from dade.common.fonts import load_font

from .chart import SLIDE_LANE_REMAP, SPEED_CHANGE_KIND

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from .typing import ChartDict, NoteDict, SlideDict, TempoEventDict

__all__ = (
    'ALTERNATE_TARGETS',
    'ALTERNATE_TARGET_COLOR',
    'ALTERNATE_TARGET_LANES',
    'DEFAULT_SCALE',
    'DEFAULT_SEED',
    'DEFAULT_SPEED',
    'FREE_NOTE_START_TIME',
    'HOLD_HEAD_KIND',
    'HOLD_NOTE_TYPE',
    'LANE_COUNT',
    'NOTE_COLOR',
    'NOTE_COLORS',
    'SCALE_RANGE',
    'SECONDS_PER_COLUMN',
    'SIDE_COUNT',
    'SIDE_LABELS',
    'SIDE_OBJECT_COLOR',
    'SIDE_OBJECT_FLAG',
    'SLIDE_COLOR',
    'SLIDE_NOTE_TYPE',
    'SPEED_RANGE',
    'SPEED_STEP',
    'render_chart_image',
)

ALTERNATE_TARGETS = (7, 8, 9)
"""
The route selectors naming a target beyond the seven lanes, which the game draws green.

``AssignGreenTargets`` starts a note's availability bitmap with slots 0 to 6 set and 7 to 9 clear,
so the seven are the lanes a note can be given and these three are the alternative targets a chart
has to name outright. A hold reaches them as its colour tone plus seven, matching the engine's
three-slot side scan.

:meta hide-value:
"""
HOLD_NOTE_TYPE = 1
"""The note type that is held, the engine's ``kNoteTypeHold``, whose first target coordinate is how
long for.

:meta hide-value:
"""
SLIDE_NOTE_TYPE = 2
"""
The note type that slides, which the engine remaps to its own ``kNoteTypeSlide`` on load.

None of the five tunes shipped with the game holds one; a downloaded library does.

:meta hide-value:
"""
HOLD_HEAD_KIND = 1
"""The hold kind marking a hold's head, the engine's ``kHoldKindHead``.

:meta hide-value:
"""
FREE_NOTE_START_TIME = -1
"""
The group value that marks a free note, which belongs to no chain.

The engine calls these free. They are struck like any other note and are drawn and counted as such;
they simply have no chain to inherit a lane from. The opening pair of a tune is usually two of
them.

:meta hide-value:
"""

DEFAULT_SEED = None
"""
The seed the lane layout uses when none is asked for, meaning a fresh one each run.

The game seeds the tracker with ``SetRandSeed(rand())``, so a chart lays out differently every
time it is played. Passing a seed pins the layout, which is what a replay does.

:meta hide-value:
"""
DEFAULT_SCALE = 1.0
"""The output scale used when none is asked for.

:meta hide-value:
"""
SCALE_RANGE = (1.0, 3.0)
"""
The smallest and largest output scale.

The image is laid out at three times its size and reduced once at the end, so a scale of three
keeps every pixel that was drawn and smooths nothing. Ask for a larger image when it is to be
looked at on a display that would otherwise have to enlarge it.

:meta hide-value:
"""
DEFAULT_SPEED = 1.0
"""The speed modifier used when none is asked for, which is the chart's own spacing.

:meta hide-value:
"""
SPEED_RANGE = (1.0, 2.0)
"""The lowest and highest speed modifier the game offers.

:meta hide-value:
"""
SPEED_STEP = 0.1
"""How coarsely the speed modifier may be set between the ends of :py:data:`SPEED_RANGE`.

:meta hide-value:
"""
SECONDS_PER_COLUMN = 30
"""How many seconds of chart one column holds by default.

:meta hide-value:
"""
SIDE_COUNT = 2
"""How many play sides a chart has.

:meta hide-value:
"""
SIDE_LABELS = ('side 0 (pink)', 'side 1 (blue)')
"""
What the game shows each side as.

Established from the opening of *威風堂々*, whose first notes are a pair on side 0 at 2308 ms
answered by a pair on side 1 at 2885 ms. That gap is 577 ms, one quarter note at the tune's 104
beats per minute, and the pink player is the one who opens.

:meta hide-value:
"""
LANE_COUNT = 7
"""
How many lanes the field has, which is the engine's own ``NoteLaneTracker::kLaneCount``.

The lane table places them symmetrically about a centre lane, at fractions of the half-width in
sevenths of a third: -0.777778, -0.518519, -0.259259, 0, and the three mirrors of those.

:meta hide-value:
"""
NOTE_COLORS = ((255, 120, 180), (80, 220, 255))
"""The colour of an ordinary note on each side, matching the two the game gives the players.

:meta hide-value:
"""
NOTE_COLOR = NOTE_COLORS[1]
"""The colour of an ordinary note on side 1, which the hold and chain glyphs draw in.

:meta hide-value:
"""
ALTERNATE_TARGET_COLOR = (110, 235, 130)
"""The colour of a note aimed at one of the alternative targets, which the game draws green.

:meta hide-value:
"""
SIDE_OBJECT_FLAG = 0x20
"""
The note flag marking a note that travels to the other side, to be swiped back.

The engine calls this ``kSideObjectFlag`` and counts the notes carrying it per side. It is the same
bit as ``kNoteFlagHasPath``, so such a note is exactly one carrying path points, and those points
name the notes on the far side it links to.

:meta hide-value:
"""
SIDE_OBJECT_COLOR = (255, 200, 70)
"""The colour of a note that travels to the other side, which the game draws gold.

:meta hide-value:
"""
SLIDE_COLOR = (200, 150, 255)
"""
The colour a slide's track is drawn in.

A slide is neither side's colour, being a path rather than a note, so it takes one of its own.

:meta hide-value:
"""

_REMAPPED_ROUTE_VERSION = 12
_UNSET_ROUTE = -2
_SIGN_BIT = 0x8000
_NO_ROUTE_SELECTOR = 0xFFFE
ALTERNATE_TARGET_LANES = (5, 3, 1)
"""
Which lane each of the three alternative targets is drawn in, in route-selector order.

The targets sit above the lanes rather than among them, so any placement is a choice. These three
are spaced evenly and symmetrically about the middle lane of the seven. The selectors run right to
left, matching where the game puts the three objects on the pink side.

:meta hide-value:
"""

_BACKGROUND = (24, 24, 32)
_TRACK_COLOR = (40, 40, 52)
_TRACK_EDGE = (58, 58, 72)
_LANE_LINE = (50, 50, 64)
_GRID_COLOR = (58, 58, 72)
_SECOND_TEXT = (150, 150, 165)
_TITLE_COLOR = (235, 235, 245)
_SUBTITLE_COLOR = (170, 170, 185)
_TEMPO_COLOR = (255, 90, 210)
_BEAT_LINE = (46, 46, 60)
_BAR_LINE = (72, 72, 90)
_HALF_TURN = 180
_FULL_TURN = 360

_SUPERSAMPLE = 3
_SLIDE_WIDTH = 4 * _SUPERSAMPLE
_VEE_STROKE = 2 * _SUPERSAMPLE
_VEE_WIDTH = 0.55
_VEE_RISE = 0.4
_SLIDE_DOT = 3 * _SUPERSAMPLE
_TEXT_GAP = 6 * _SUPERSAMPLE
_MARGIN = 24 * _SUPERSAMPLE
_HEADER = 112 * _SUPERSAMPLE
_FOOTER = 34 * _SUPERSAMPLE
_LANE_PX = 15 * _SUPERSAMPLE
_PANEL_GAP = 60 * _SUPERSAMPLE
_COLUMN_GAP = 40 * _SUPERSAMPLE
_GUTTER = 52 * _SUPERSAMPLE
_PIXELS_PER_SECOND = 46 * _SUPERSAMPLE
_NOTE_RADIUS = 5 * _SUPERSAMPLE
_BAR_WIDTH = 3 * _SUPERSAMPLE
_HOLD_WIDTH = 9 * _SUPERSAMPLE
_MILLISECONDS = 1000.0
_SECONDS_PER_MINUTE = 60.0
_BEATS_PER_BAR = 4
_CHAIN_MINIMUM = 2
_LEGEND_ITEM = 168 * _SUPERSAMPLE
_LEGEND_GLYPH = 34 * _SUPERSAMPLE
_LEGEND_ROW = 22 * _SUPERSAMPLE
_LEGEND_HOLD = 12 * _SUPERSAMPLE
_LEGEND_CHAIN = 9 * _SUPERSAMPLE
_LEGEND_RULE = 12 * _SUPERSAMPLE
_TITLE_SIZE = 20 * _SUPERSAMPLE
_LABEL_SIZE = 13 * _SUPERSAMPLE
_SMALL_SIZE = 11 * _SUPERSAMPLE


def _timing_selector(note: NoteDict, version: int) -> int:
    # The engine's route selector, as InstallParsedNotes derives it from the second target
    # coordinate. A value inside 0..9 names a target outright; anything else leaves the note to
    # choose one.
    unsigned = note['target'][1] & 0xFFFF
    route = unsigned - 0x10000 if unsigned >= _SIGN_BIT else unsigned
    if note['hold_kind'] == HOLD_HEAD_KIND:
        return route + LANE_COUNT
    if version <= _REMAPPED_ROUTE_VERSION or unsigned >= _NO_ROUTE_SELECTOR:
        return _UNSET_ROUTE
    match route:
        case -3:
            return -4
        case -4:
            return -3
        case _ if 0 <= route < len(SLIDE_LANE_REMAP):
            return SLIDE_LANE_REMAP[route]
        case _:
            return _UNSET_ROUTE


def _vertical(note: NoteDict, version: int) -> bool:
    # Whether a note comes straight down into a lane the chart names, rather than taking a path the
    # tracker lays out. A slide names its lane the same way, so the caller rules those out.
    return 0 <= _timing_selector(note, version) < LANE_COUNT


def _alternate_target(note: NoteDict, version: int) -> bool:
    # Whether a note is drawn green, meaning it is aimed at one of the three targets beyond the
    # seven lanes rather than at a lane.
    return _timing_selector(note, version) in ALTERNATE_TARGETS


def _note_color(note: NoteDict, version: int) -> tuple[int, int, int]:
    # A note aimed at an alternative target is green whichever side it is on; every other note takes
    # its side's colour.
    if _alternate_target(note, version):
        return ALTERNATE_TARGET_COLOR
    side = note['side'] if 0 <= note['side'] < SIDE_COUNT else 0
    return NOTE_COLORS[side]


def _claimed_until(note: NoteDict) -> int:
    # The last moment a note holds its lane against another. A hold keeps its lane for as long as it
    # is held, so nothing may land in that lane until it is released.
    return note['hit_time'] + _hold_length(note)


def _draw_note_head(draw: ImageDraw.ImageDraw,
                    center: int,
                    y: int,
                    color: tuple[int, int, int],
                    *,
                    side_object: bool = False,
                    vertical: bool = False) -> None:
    # One note's disc. A note that travels to the other side keeps its own colour on the half
    # nearest the player and takes gold on the half it leaves by, so it says both whose it is and
    # that it has to be swiped back. A note that comes straight down carries a V cut into it.
    box = (center - _NOTE_RADIUS, y - _NOTE_RADIUS, center + _NOTE_RADIUS, y + _NOTE_RADIUS)
    draw.ellipse(box, fill=color)
    if side_object:
        draw.pieslice(box, _HALF_TURN, _FULL_TURN, fill=SIDE_OBJECT_COLOR)
    if vertical:
        arm = round(_NOTE_RADIUS * _VEE_WIDTH)
        rise = round(_NOTE_RADIUS * _VEE_RISE)
        draw.line((center - arm, y - rise, center, y + rise, center + arm, y - rise),
                  fill=_BACKGROUND,
                  width=_VEE_STROKE,
                  joint='curve')


def _hold_length(note: NoteDict) -> int:
    # How long a hold note is held, in milliseconds, or zero when it is not one. A hold carries its
    # length in the first target coordinate, which is zero on every other note. The engine scales
    # that coordinate exactly as it scales the note's times, and the lengths it yields are whole
    # quarter notes at the tune's own tempo.
    return note['target'][0] if note['type'] == HOLD_NOTE_TYPE else 0


def _playable(notes: Sequence[NoteDict], side: int) -> int:
    # How many notes one side holds. The two sides are separate sets, so each is counted alone.
    return sum(1 for note in notes if note['side'] == side)


def _column_span(notes: Sequence[NoteDict], end_time: int) -> tuple[int, int]:
    # The first and last millisecond the image has to cover.
    if not notes:
        return 0, max(end_time, 1)
    first = min(*(note['hit_time'] for note in notes), 0)
    last = max(*(note['hit_time'] for note in notes), end_time)
    return first, max(last, first + 1)


def _fixed_lane(note: NoteDict, version: int) -> int | None:
    # The slot a note is pinned to, or None when the game is free to choose one. A note aimed at an
    # alternative target names it outright, so it is drawn in that target's own slot and no
    # randomness touches it.
    selector = _timing_selector(note, version)
    if selector in ALTERNATE_TARGETS:
        return ALTERNATE_TARGET_LANES[ALTERNATE_TARGETS.index(selector)]
    # A selector naming one of the seven lanes is a note that comes straight down into it, which is
    # every slide and every vertical note. The tracker never sees these, so no seed moves them.
    return selector if 0 <= selector < LANE_COUNT else None


def _lanes(notes: Sequence[NoteDict],
           version: int,
           seed: int | None = DEFAULT_SEED) -> Mapping[int, int]:
    """
    Work out which lane each note is drawn in.

    Three rules, in the order ``CMusicSheet2::AssignChartLanes`` applies them. A note aimed at one
    of the three alternative targets is pinned to that target's slot, and no randomness touches it.
    A chain member takes the slot of the segment before it, so a chain runs straight up rather than
    stepping sideways. Everything else the engine allocates at run time through ``NoteLaneTracker``,
    which shuffles its candidates with ``rand()`` and so lays one chart out differently on every
    play.

    Only that last rule is approximated: the shuffle here is driven by *seed*, so passing one pins
    a layout the way a replay does.

    Parameters
    ----------
    notes : collections.abc.Sequence[NoteDict]
        The chart's notes.
    version : int
        The chart version, which decides how a note's route selector is read.
    seed : int | None
        Chooses between the layouts the game would pick between. ``None`` takes a fresh one, as the
        game itself does.

    Returns
    -------
    collections.abc.Mapping[int, int]
        Each note's index against its lane.
    """
    rng = random.Random(seed)  # noqa: S311
    # A chain claims its lane from its first note to its last, so the spans can be compared.
    spans: list[tuple[int, int, int, list[int]]] = []
    singles: dict[tuple[int, int], list[int]] = {}
    for members in _groups(notes):
        side = notes[members[0]]['side']
        side = side if 0 <= side < SIDE_COUNT else 0
        if len(members) < _CHAIN_MINIMUM:
            # A note in no chain still cannot share a lane with one struck beside it, so the ones a
            # side strikes together are laid out as a group.
            singles.setdefault((side, notes[members[0]]['hit_time']), []).append(members[0])
            continue
        times = [_claimed_until(notes[index]) for index in members]
        spans.append(
            (min(notes[index]['hit_time'] for index in members), max(times), side, members))
    for (side, hit_time), members in singles.items():
        spans.append(
            (hit_time, max(_claimed_until(notes[index]) for index in members), side, members))
    spans.sort(key=operator.itemgetter(0, 1))
    lanes: dict[int, int] = {}
    # taken[side] holds, per lane, the time the lane is claimed until.
    taken = [[-math.inf] * LANE_COUNT for _ in range(SIDE_COUNT)]
    for start, end, side, members in spans:
        # A note aimed at an alternative target sits in that target's own slot, so it neither needs
        # a lane nor takes one from the notes struck beside it.
        aimed = {
            index: slot
            for index in members if (slot := _fixed_lane(notes[index], version)) is not None
        }
        lanes.update(aimed)
        if not (rest := [index for index in members if index not in aimed]):
            continue
        by_time: dict[int, list[int]] = {}
        for index in rest:
            by_time.setdefault(notes[index]['hit_time'], []).append(index)
        width = max(len(at_once) for at_once in by_time.values())
        free = [
            lane for lane in range(max(LANE_COUNT - width + 1, 1)) if all(
                taken[side][min(lane + offset, LANE_COUNT - 1)] < start for offset in range(width))
        ]
        # The engine shuffles its candidates and takes the first; so does this, from the seed.
        base = rng.choice(free) if free else 0
        for at_once in by_time.values():
            for offset, index in enumerate(sorted(at_once)):
                lanes[index] = min(base + offset, LANE_COUNT - 1)
        for offset in range(width):
            taken[side][min(base + offset, LANE_COUNT - 1)] = end
    return lanes


def _groups(notes: Sequence[NoteDict]) -> list[list[int]]:
    # Every chain, as the indices of its notes in the order they are struck.
    #
    # A chain is a doubly linked run: a note's chain block names the note before it and the note
    # after it by identifier, with -1 at each end. Walking forward from every head recovers the
    # runs. A note carrying no chain block is a run of one.
    by_id = {note['id']: index for index, note in enumerate(notes)}
    runs: list[list[int]] = []
    seen: set[int] = set()
    for index, note in enumerate(notes):
        if index in seen:
            continue
        chain = note['chain']
        # Start only from a head, so a run is walked once and in order.
        if chain is not None and chain[0] in by_id:
            continue
        run: list[int] = []
        step: int | None = index
        while step is not None and step not in seen:
            seen.add(step)
            run.append(step)
            following = notes[step]['chain']
            after = following[1] if following is not None else -1
            step = by_id.get(after) if after != -1 else None
        runs.append(run)
    # A run whose links form a ring has no head, so it is picked up from wherever it is met.
    runs.extend([index] for index in range(len(notes)) if index not in seen)
    return runs


class _Layout(NamedTuple):
    """Where a chart's columns, lanes, and times land on the canvas."""

    bottom: int
    columns: int
    column_height: int
    column_width: int
    height: int
    lanes: int
    legend_rows: int
    panel_width: int
    pixels_per_second: int
    seconds_per_column: int
    span_ms: int
    start_ms: int
    top: int
    width: int

    @classmethod
    def for_chart(cls, chart: ChartDict, seconds_per_column: int, speed: float) -> _Layout:
        start_ms, end_ms = _column_span(chart['notes'], chart['header']['end_time'])
        span_ms = seconds_per_column * int(_MILLISECONDS)
        columns = max(1, math.ceil((end_ms - start_ms) / span_ms))
        # The speed modifier spreads the notes further apart without changing how much time a
        # column holds, exactly as it does in play.
        pixels_per_second = round(_PIXELS_PER_SECOND * speed)
        column_height = seconds_per_column * pixels_per_second
        # Every lane is drawn whether the chart uses it or not, since an empty lane is part of the
        # field rather than wasted width.
        lanes = LANE_COUNT
        column_width = _GUTTER + lanes * _LANE_PX
        # Each side gets a panel of its own holding the whole of that side's chart, and the two sit
        # beside each other rather than interleaving column by column.
        panel_width = columns * column_width + (columns - 1) * _COLUMN_GAP
        top = _MARGIN + _HEADER
        width = _MARGIN * 2 + SIDE_COUNT * panel_width + (SIDE_COUNT - 1) * _PANEL_GAP
        legend_rows = _legend_rows(width)
        return cls(
            bottom=top + column_height,
            columns=columns,
            column_height=column_height,
            column_width=column_width,
            height=(_MARGIN * 2 + _HEADER + column_height + _FOOTER + legend_rows * _LEGEND_ROW),
            lanes=lanes,
            legend_rows=legend_rows,
            panel_width=panel_width,
            pixels_per_second=pixels_per_second,
            seconds_per_column=seconds_per_column,
            span_ms=span_ms,
            start_ms=start_ms,
            top=top,
            width=width)

    def panel_origin(self, side: int) -> int:
        # The left edge of one side's panel. Side 0 is on the left, side 1 on the right.
        return _MARGIN + side * (self.panel_width + _PANEL_GAP)

    def column_origin(self, side: int, column: int) -> int:
        # The left edge of one column within a side's panel.
        return self.panel_origin(side) + column * (self.column_width + _COLUMN_GAP)

    def lane_center(self, side: int, column: int, lane: int) -> int:
        # The middle of one lane.
        return self.column_origin(side, column) + _GUTTER + lane * _LANE_PX + _LANE_PX // 2

    def place(self, time_ms: int) -> tuple[int, int] | None:
        # The column and pixel row a time lands on, or None when it falls outside the image. Time
        # runs upward, so the earliest moment in a column sits at its bottom edge.
        offset = time_ms - self.start_ms
        column = offset // self.span_ms
        if not 0 <= column < self.columns:
            return None
        within = (offset % self.span_ms) / _MILLISECONDS * self.pixels_per_second
        return int(column), self.bottom - int(within)


def _draw_beats(draw: ImageDraw.ImageDraw, layout: _Layout, bpm: float) -> None:
    # A line on every quarter note, with a brighter one every fourth, in both panels. The grid is
    # anchored at time zero, which is where the tune's own clock starts; a chart may begin before
    # it.
    beat_ms = _SECONDS_PER_MINUTE * _MILLISECONDS / bpm
    last_beat = math.ceil((layout.start_ms + layout.columns * layout.span_ms) / beat_ms)
    for beat in range(math.floor(layout.start_ms / beat_ms), last_beat + 1):
        if (spot := layout.place(int(beat * beat_ms))) is None:
            continue
        column, y = spot
        color = _BAR_LINE if beat % _BEATS_PER_BAR == 0 else _BEAT_LINE
        for side in range(SIDE_COUNT):
            origin = layout.column_origin(side, column)
            draw.line((origin + _GUTTER, y, origin + layout.column_width, y),
                      fill=color,
                      width=_SUPERSAMPLE)


def _draw_grid(draw: ImageDraw.ImageDraw, layout: _Layout, bpm: float | None) -> None:
    # Each side's panel of columns, their lane divisions, the beat grid, and the seconds.
    small = load_font(_SMALL_SIZE)
    label = load_font(_LABEL_SIZE)
    for side in range(SIDE_COUNT):
        draw.text((layout.panel_origin(side), layout.top - _LABEL_SIZE - _TEXT_GAP),
                  SIDE_LABELS[side],
                  fill=NOTE_COLORS[side],
                  font=label)
        for column in range(layout.columns):
            left = layout.column_origin(side, column) + _GUTTER
            draw.rectangle((left, layout.top, left + layout.lanes * _LANE_PX, layout.bottom),
                           fill=_TRACK_COLOR,
                           outline=_TRACK_EDGE,
                           width=_SUPERSAMPLE)
            for lane in range(1, layout.lanes):
                x = left + lane * _LANE_PX
                draw.line((x, layout.top, x, layout.bottom), fill=_LANE_LINE, width=_SUPERSAMPLE)
    if bpm is not None and bpm > 0:
        _draw_beats(draw, layout, bpm)
    for side in range(SIDE_COUNT):
        for column in range(layout.columns):
            origin = layout.column_origin(side, column)
            for second in range(layout.seconds_per_column + 1):
                y = layout.bottom - second * layout.pixels_per_second
                draw.line((origin + _GUTTER, y, origin + layout.column_width, y),
                          fill=_GRID_COLOR,
                          width=_SUPERSAMPLE)
                absolute = (layout.start_ms + column * layout.span_ms) / _MILLISECONDS + second
                draw.text((origin, y - _SMALL_SIZE // 2),
                          f'{absolute:.0f}s',
                          fill=_SECOND_TEXT,
                          font=small)


def _draw_tempo_events(draw: ImageDraw.ImageDraw, layout: _Layout,
                       events: Sequence[TempoEventDict]) -> None:
    # A speed change rules its column across in both panels, labelled with the speed it installs.
    for event in events:
        if event['kind'] != SPEED_CHANGE_KIND or (spot := layout.place(event['time'])) is None:
            continue
        column, y = spot
        for side in range(SIDE_COUNT):
            origin = layout.column_origin(side, column)
            draw.line((origin + _GUTTER, y, origin + layout.column_width, y),
                      fill=_TEMPO_COLOR,
                      width=2 * _SUPERSAMPLE)


def _spot(layout: _Layout, notes: Sequence[NoteDict], lanes: Mapping[int, int],
          index: int) -> tuple[int, int, int] | None:
    # The column and the pixel position a note is drawn at, or None when it is not drawn at all. A
    # free note asks nothing of the player, so it is left out rather than shown.
    note = notes[index]
    if (placed := layout.place(note['hit_time'])) is None:
        return None
    column, y = placed
    side = note['side'] if 0 <= note['side'] < SIDE_COUNT else 0
    return column, layout.lane_center(side, column, lanes.get(index, 0)), y


def _draw_chains(draw: ImageDraw.ImageDraw, layout: _Layout, notes: Sequence[NoteDict],
                 lanes: Mapping[int, int], version: int) -> None:
    # A line joins each note of a chain to the next, drawn under the notes themselves. Nothing is
    # drawn before the first note or after the last, and a pair split across two columns is left
    # without a line, there being nowhere to run one.
    for members in _groups(notes):
        if len(members) < _CHAIN_MINIMUM:
            continue
        placed = [(index, _spot(layout, notes, lanes, index)) for index in members]
        for (_, before), (index, after) in itertools.pairwise(placed):
            if before is None or after is None or before[0] != after[0]:
                continue
            draw.line((before[1], before[2], after[1], after[2]),
                      fill=_note_color(notes[index], version),
                      width=_BAR_WIDTH)


def _slide_paths(notes: Sequence[NoteDict],
                 slides: Sequence[SlideDict]) -> dict[int, list[tuple[int, int]]]:
    """
    Work out the lane a slide is in at each moment it is drawn through.

    A slide's records are its waypoints. Each carries the lane the finger is to be in and, in the
    same shape a note's own timing takes, a spawn time and a travel time whose sum is the moment it
    is to be there. The note itself is the first point, since that is where the finger goes down.

    Parameters
    ----------
    notes : collections.abc.Sequence[NoteDict]
        The chart's notes.
    slides : collections.abc.Sequence[SlideDict]
        The chart's slide records.

    Returns
    -------
    dict[int, list[tuple[int, int]]]
        Each sliding note's index against its path, as a time and a lane at each point.
    """
    grouped: dict[int, list[SlideDict]] = {}
    for slide in slides:
        if 0 <= slide['note_index'] < len(notes):
            grouped.setdefault(slide['note_index'], []).append(slide)
    return {
        index: [(notes[index]['hit_time'], -1)] +
               [(record['value_a'] + record['value_b'], record['lane'])
                for record in sorted(records, key=operator.itemgetter('field2'))
                if 0 <= record['lane'] < LANE_COUNT]
        for index, records in grouped.items()
    }


def _draw_slides(draw: ImageDraw.ImageDraw, layout: _Layout, notes: Sequence[NoteDict],
                 lanes: Mapping[int, int], slides: Sequence[SlideDict]) -> None:
    # The track a finger takes: down on the note, then across to each waypoint in turn. It is drawn
    # under the notes, and a leg whose two ends fall in different columns is left out, there being
    # nowhere to run it.
    for index, path in _slide_paths(notes, slides).items():
        side = notes[index]['side'] if 0 <= notes[index]['side'] < SIDE_COUNT else 0
        points = []
        for time_ms, lane in path:
            if (placed := layout.place(time_ms)) is None:
                continue
            column, y = placed
            at = lanes.get(index, 0) if lane < 0 else lane
            points.append((column, layout.lane_center(side, column, at), y))
        for before, after in itertools.pairwise(points):
            if before[0] != after[0]:
                continue
            draw.line((before[1], before[2], after[1], after[2]),
                      fill=SLIDE_COLOR,
                      width=_SLIDE_WIDTH)
            draw.ellipse((after[1] - _SLIDE_DOT, after[2] - _SLIDE_DOT, after[1] + _SLIDE_DOT,
                          after[2] + _SLIDE_DOT),
                         fill=SLIDE_COLOR)


def _draw_notes(draw: ImageDraw.ImageDraw,
                layout: _Layout,
                notes: Sequence[NoteDict],
                lanes: Mapping[int, int],
                version: int,
                slides: Sequence[SlideDict] = ()) -> None:
    sliding = {slide['note_index'] for slide in slides}
    for index, note in enumerate(notes):
        if (placed := _spot(layout, notes, lanes, index)) is None:
            continue
        _, center, y = placed
        color = _note_color(note, version)
        if (held := _hold_length(note)) > 0:
            # A hold runs from the note up to the moment it is released, clipped to the column. It
            # is drawn wide, with a cap at the release, so that a hold sitting at the end of a chain
            # cannot be taken for the narrower line joining the chain.
            top = max(y - int(held / _MILLISECONDS * layout.pixels_per_second), layout.top)
            draw.rectangle((center - _HOLD_WIDTH // 2, top, center + _HOLD_WIDTH // 2, y),
                           fill=color)
            draw.line((center - _HOLD_WIDTH, top, center + _HOLD_WIDTH, top),
                      fill=color,
                      width=2 * _SUPERSAMPLE)
        _draw_note_head(draw,
                        center,
                        y,
                        color,
                        side_object=bool(note['flags'] & SIDE_OBJECT_FLAG),
                        vertical=index not in sliding and _vertical(note, version))


def _draw_header(draw: ImageDraw.ImageDraw, layout: _Layout, chart: ChartDict, *,
                 artist: str | None, difficulty: str | None, level: int | None,
                 title: str | None) -> None:
    label_font = load_font(_LABEL_SIZE)
    y = _MARGIN
    if title:
        draw.text((_MARGIN, y), title, fill=_TITLE_COLOR, font=load_font(_TITLE_SIZE))
        y += _TITLE_SIZE + 8
    if artist:
        draw.text((_MARGIN, y), artist, fill=_SUBTITLE_COLOR, font=label_font)
        y += _LABEL_SIZE + _TEXT_GAP
    parts = [difficulty or 'chart']
    if level is not None:
        parts.append(f'level {level}')
    # Each side is counted on its own: the two are separate sets of notes, not one total split
    # between them.
    parts.extend(f'{SIDE_LABELS[side]}: {_playable(chart["notes"], side)} notes'
                 for side in range(SIDE_COUNT))
    parts.append(f'v{chart["header"]["version"]}')
    draw.text((_MARGIN, y), '  ·  '.join(parts), fill=_SUBTITLE_COLOR, font=label_font)
    draw.text(
        (_MARGIN,
         layout.height - _MARGIN - layout.legend_rows * _LEGEND_ROW - _SMALL_SIZE - _TEXT_GAP),
        'Time runs upward. Across is where a note falls in its chain.',
        fill=_SECOND_TEXT,
        font=load_font(_SMALL_SIZE))


def _draw_legend(draw: ImageDraw.ImageDraw, layout: _Layout) -> None:
    # One drawn example of every mark, so the picture explains itself.
    small = load_font(_SMALL_SIZE)
    per_row = _legend_columns(layout.width)
    base = layout.height - _MARGIN - layout.legend_rows * _LEGEND_ROW
    for index, (label, glyph) in enumerate(_LEGEND):
        x = _MARGIN + (index % per_row) * _LEGEND_ITEM
        y = base + (index // per_row) * _LEGEND_ROW + _LEGEND_ROW // 2
        glyph(draw, x + _LEGEND_GLYPH // 2, y)
        draw.text((x + _LEGEND_GLYPH + _TEXT_GAP, y - _SMALL_SIZE // 2),
                  label,
                  fill=_SUBTITLE_COLOR,
                  font=small)


def _glyph_side_note(draw: ImageDraw.ImageDraw, x: int, y: int, side: int) -> None:
    draw.ellipse((x - _NOTE_RADIUS, y - _NOTE_RADIUS, x + _NOTE_RADIUS, y + _NOTE_RADIUS),
                 fill=NOTE_COLORS[side])


def _glyph_note(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    _glyph_side_note(draw, x, y, 1)


def _glyph_side_0_note(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    _glyph_side_note(draw, x, y, 0)


def _glyph_side_1_note(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    _glyph_side_note(draw, x, y, 1)


def _glyph_alternate(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.ellipse((x - _NOTE_RADIUS, y - _NOTE_RADIUS, x + _NOTE_RADIUS, y + _NOTE_RADIUS),
                 fill=ALTERNATE_TARGET_COLOR)


def _glyph_side_object(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    _draw_note_head(draw, x, y, NOTE_COLOR, side_object=True)


def _glyph_hold(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.rectangle((x - _HOLD_WIDTH // 2, y - _LEGEND_HOLD, x + _HOLD_WIDTH // 2, y),
                   fill=NOTE_COLOR)
    draw.line((x - _HOLD_WIDTH, y - _LEGEND_HOLD, x + _HOLD_WIDTH, y - _LEGEND_HOLD),
              fill=NOTE_COLOR,
              width=2 * _SUPERSAMPLE)
    _glyph_note(draw, x, y)


def _glyph_chain(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # Three notes, since a chain runs to as many as five and two would read as a special case.
    spots = [(x + (step - 1) * _LEGEND_CHAIN, y) for step in range(3)]
    draw.line(spots[0] + spots[-1], fill=NOTE_COLOR, width=_BAR_WIDTH)
    for spot_x, spot_y in spots:
        _glyph_note(draw, spot_x, spot_y)


def _glyph_slide(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # A finger going down and stepping sideways twice, which is what a slide asks for.
    spots = ((x - _LEGEND_CHAIN, y + _LEGEND_CHAIN), (x, y), (x + _LEGEND_CHAIN, y - _LEGEND_CHAIN))
    for before, after in itertools.pairwise(spots):
        draw.line(before + after, fill=SLIDE_COLOR, width=_SLIDE_WIDTH)
    for spot_x, spot_y in spots[1:]:
        draw.ellipse(
            (spot_x - _SLIDE_DOT, spot_y - _SLIDE_DOT, spot_x + _SLIDE_DOT, spot_y + _SLIDE_DOT),
            fill=SLIDE_COLOR)
    _glyph_note(draw, spots[0][0], spots[0][1])


def _glyph_vertical(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    _draw_note_head(draw, x, y, NOTE_COLOR, vertical=True)


def _glyph_speed(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.line((x - _LEGEND_RULE, y, x + _LEGEND_RULE, y), fill=_TEMPO_COLOR, width=2 * _SUPERSAMPLE)


_LEGEND: tuple[tuple[str, Callable[[ImageDraw.ImageDraw, int, int], None]], ...] = (
    ('side 0 note', _glyph_side_0_note),
    ('side 1 note', _glyph_side_1_note),
    ('alternative target', _glyph_alternate),
    ('swipe back', _glyph_side_object),
    ('hold', _glyph_hold),
    ('slide', _glyph_slide),
    ('vertical', _glyph_vertical),
    ('chain', _glyph_chain),
    ('speed change', _glyph_speed),
)


def _legend_columns(width: int) -> int:
    # How many legend entries fit on one row of an image this wide.
    return max(1, (width - _MARGIN * 2) // _LEGEND_ITEM)


def _legend_rows(width: int) -> int:
    return math.ceil(len(_LEGEND) / _legend_columns(width))


def render_chart_image(chart: ChartDict,
                       path: Path,
                       *,
                       title: str | None = None,
                       artist: str | None = None,
                       bpm: float | None = None,
                       difficulty: str | None = None,
                       level: int | None = None,
                       seconds_per_column: int = SECONDS_PER_COLUMN,
                       scale: float = DEFAULT_SCALE,
                       seed: int | None = DEFAULT_SEED,
                       speed: float = DEFAULT_SPEED) -> tuple[int, int]:
    """
    Render a chart as a strip of eight-slot lanes, read bottom to top.

    Parameters
    ----------
    chart : ChartDict
        The parsed chart.
    path : pathlib.Path
        Where to write the image.
    title : str | None
        The tune's title, drawn in the header.
    artist : str | None
        The tune's artist, drawn in the header.
    bpm : float | None
        The tune's tempo. Given one, a line is drawn on every quarter note and a brighter one on
        every bar. A tempo that is absent or not positive leaves the beat grid off.
    difficulty : str | None
        The difficulty name, drawn in the header.
    level : int | None
        The chart's level, drawn in the header.
    seconds_per_column : int
        How many seconds each column holds before wrapping.
    scale : float
        How large to write the image, as a multiple of its usual size, from 1.0 to 3.0. The layout
        is unchanged; only the number of pixels it is written at differs.
    seed : int | None
        Chooses between the lane layouts the game would pick between. The game shuffles with
        ``rand()`` and so lays a chart out differently on every play, which ``None`` matches by
        taking a fresh seed; passing one pins the layout the way a replay does.
    speed : float
        The speed modifier, from 1.0 to 2.0 in steps of 0.1 as the game offers it. A higher one
        spreads the notes further apart without changing how much time a column holds, so the image
        grows taller.

    Returns
    -------
    tuple[int, int]
        The image's width and height in pixels.

    Raises
    ------
    ValueError
        If *seconds_per_column* is not positive.
    """
    if seconds_per_column <= 0:
        msg = f'seconds_per_column must be positive, got {seconds_per_column}.'
        raise ValueError(msg)
    layout = _Layout.for_chart(chart, seconds_per_column, speed)
    image = Image.new('RGB', (layout.width, layout.height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    lanes = _lanes(chart['notes'], chart['header']['version'], seed)
    _draw_grid(draw, layout, bpm)
    _draw_tempo_events(draw, layout, chart['tempo_events'])
    _draw_slides(draw, layout, chart['notes'], lanes, chart['slides'])
    _draw_chains(draw, layout, chart['notes'], lanes, chart['header']['version'])
    _draw_notes(draw, layout, chart['notes'], lanes, chart['header']['version'], chart['slides'])
    _draw_header(draw,
                 layout,
                 chart,
                 artist=artist,
                 difficulty=difficulty,
                 level=level,
                 title=title)
    _draw_legend(draw, layout)
    # Pillow draws no anti-aliasing of its own, so everything is laid out at a multiple of the
    # final size and reduced once at the end, which smooths every edge in one pass. Asking for a
    # larger image reduces it by less, so it keeps more pixels and is smoothed by that much less.
    width = round(layout.width * scale / _SUPERSAMPLE)
    height = round(layout.height * scale / _SUPERSAMPLE)
    image.resize((width, height), Image.Resampling.LANCZOS).save(path)
    return width, height
