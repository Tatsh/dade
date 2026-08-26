"""Tests for :py:mod:`dade.rbplus.render`."""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, cast

from PIL import Image
import pytest

from dade.rbplus.chart import parse_chart
from dade.rbplus.render import (
    ALTERNATE_TARGET_COLOR,
    DEFAULT_SPEED,
    HOLD_HEAD_KIND,
    HOLD_NOTE_TYPE,
    LANE_COUNT,
    NOTE_COLORS,
    SIDE_COUNT,
    SIDE_OBJECT_COLOR,
    SIDE_OBJECT_FLAG,
    SLIDE_COLOR,
    SLIDE_NOTE_TYPE,
    render_chart_image,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _histogram(path: Path) -> list[tuple[int, tuple[int, int, int]]]:
    # Pillow types getcolors() loosely, since it answers differently by mode; converting to RGB
    # first makes every entry a count against an RGB triple.
    with Image.open(path) as image:
        return cast('list[tuple[int, tuple[int, int, int]]]',
                    image.convert('RGB').getcolors(maxcolors=1 << 20) or [])


def _count(path: Path, wanted: tuple[int, int, int]) -> int:
    """
    Count the pixels of one colour an image holds.

    Every image carries the legend, which draws one of each mark, so a colour is never absent
    outright. Counting instead of looking tells a mark in the chart from the same mark in the
    legend.
    """
    return sum(count for count, color in _histogram(path) if color == wanted)


def _near(path: Path, wanted: tuple[int, int, int], within: int = 24) -> int:
    """
    Count the pixels close to one colour.

    A mark drawn over only part of a note is small enough that the reduction to the final size
    leaves no pixel holding the colour exactly, so nearness is counted instead.
    """
    return sum(count for count, color in _histogram(path) if all(
        abs(a - b) <= within for a, b in zip(color, wanted, strict=True)))


def test_a_chart_renders(tmp_path: Path, chart_bytes: bytes) -> None:
    out = tmp_path / 'chart.png'
    width, height = render_chart_image(parse_chart(chart_bytes), out)
    assert out.is_file()
    with Image.open(out) as image:
        assert image.size == (width, height)


def _baseline(tmp_path: Path, make_chart: Callable[..., bytes], wanted: tuple[int, int,
                                                                              int]) -> int:
    """Count the pixels of one colour an empty chart carries, which is the legend's own."""
    out = tmp_path / 'baseline.png'
    render_chart_image(parse_chart(make_chart()), out)
    return _count(out, wanted)


def test_an_ordinary_note_takes_its_side_colour(tmp_path: Path, make_chart: Callable[..., bytes],
                                                make_note: Callable[..., bytes]) -> None:
    out = tmp_path / 'chart.png'
    render_chart_image(parse_chart(make_chart(notes=(make_note(start_time=3, kind=2),))), out)
    assert _count(out, NOTE_COLORS[0]) > _baseline(tmp_path, make_chart, NOTE_COLORS[0])
    assert _count(out, ALTERNATE_TARGET_COLOR) == _baseline(tmp_path, make_chart,
                                                            ALTERNATE_TARGET_COLOR)


@pytest.mark.parametrize('tone', [0, 1, 2])
def test_an_alternative_target_is_green(tmp_path: Path, make_chart: Callable[..., bytes],
                                        make_note: Callable[..., bytes], tone: int) -> None:
    # A note aiming at a named target reaches it as its colour tone plus the seven lanes, so tones
    # zero to two are the three alternative targets.
    out = tmp_path / 'chart.png'
    note = make_note(hold_kind=1, target=(0, tone, 0, 0))
    render_chart_image(parse_chart(make_chart(notes=(note,))), out, seed=0)
    assert _count(out, ALTERNATE_TARGET_COLOR) > _baseline(tmp_path, make_chart,
                                                           ALTERNATE_TARGET_COLOR)


def _green_columns(path: Path) -> set[int]:
    """Which columns of an image carry a green pixel."""
    with Image.open(path) as image:
        pixels = image.convert('RGB').load()
        assert pixels is not None
        return {
            x
            for x in range(image.width)
            for y in range(image.height)
            if cast('tuple[int, int, int]', pixels[x, y]) == ALTERNATE_TARGET_COLOR
        }


def test_the_alternative_targets_run_right_to_left(tmp_path: Path, make_chart: Callable[..., bytes],
                                                   make_note: Callable[..., bytes]) -> None:
    # The game puts the pink side's three objects left, middle, and right, and the route selectors
    # name them in the opposite order, so a higher tone is drawn further left. The legend draws a
    # green mark of its own at a fixed place, so it is measured once and taken back out.
    empty = tmp_path / 'empty.png'
    render_chart_image(parse_chart(make_chart()), empty, seed=0)
    legend = _green_columns(empty)

    def note_column(tone: int) -> float:
        out = tmp_path / f'tone{tone}.png'
        render_chart_image(parse_chart(
            make_chart(notes=(make_note(hold_kind=1, target=(0, tone, 0, 0)),))),
                           out,
                           seed=0)
        found = _green_columns(out) - legend
        assert found
        return sum(found) / len(found)

    assert note_column(0) > note_column(1) > note_column(2)


def test_a_hold_note_extends_to_its_end(tmp_path: Path, make_chart: Callable[..., bytes],
                                        make_note: Callable[..., bytes]) -> None:
    short = make_note(note_type=HOLD_NOTE_TYPE, target=(300, 0, 0, 0))
    long = make_note(note_type=HOLD_NOTE_TYPE, target=(4000, 0, 0, 0))

    def held_pixels(note: bytes, name: str) -> int:
        out = tmp_path / name
        render_chart_image(parse_chart(make_chart(notes=(note,))), out, seed=0)
        return _count(out, NOTE_COLORS[0])

    assert held_pixels(long, 'long.png') > held_pixels(short, 'short.png')


def test_a_note_that_is_not_a_hold_draws_no_bar(tmp_path: Path, make_chart: Callable[..., bytes],
                                                make_note: Callable[..., bytes]) -> None:
    # A non-hold note carries a zero first target coordinate, so nothing extends from it.
    plain = make_note(target=(0, 0, 0, 0))
    held = make_note(note_type=HOLD_NOTE_TYPE, target=(4000, 0, 0, 0))

    def held_pixels(note: bytes, name: str) -> int:
        out = tmp_path / name
        render_chart_image(parse_chart(make_chart(notes=(note,))), out, seed=0)
        return _count(out, NOTE_COLORS[0])

    assert held_pixels(plain, 'plain.png') < held_pixels(held, 'held.png')


def test_a_note_aimed_at_no_target_is_not_green(tmp_path: Path, make_chart: Callable[..., bytes],
                                                make_note: Callable[..., bytes]) -> None:
    out = tmp_path / 'chart.png'
    render_chart_image(parse_chart(make_chart(notes=(make_note(target=(0, 0, 0, 0)),))),
                       out,
                       seed=0)
    assert _count(out, ALTERNATE_TARGET_COLOR) == _baseline(tmp_path, make_chart,
                                                            ALTERNATE_TARGET_COLOR)


def _pair(make_note: Callable[..., bytes],
          *,
          side: int = 0,
          first: int = 0,
          second: int = 1000) -> tuple[bytes, bytes]:
    """Two notes linked as one chain, the first naming the second as the note after it."""
    return (make_note(note_id=1, chain=(-1, 2, 0, 0), side=side, spawn_time=first, travel_time=0),
            make_note(note_id=2, chain=(1, -1, 0, 0), side=side, spawn_time=second, travel_time=0))


def _loose(make_note: Callable[..., bytes]) -> tuple[bytes, bytes]:
    """Build the same two notes carrying no chain block, so neither follows the other."""
    return (make_note(note_id=1, spawn_time=0,
                      travel_time=0), make_note(note_id=2, spawn_time=1000, travel_time=0))


def test_chained_notes_are_joined(tmp_path: Path, make_chart: Callable[..., bytes],
                                  make_note: Callable[..., bytes]) -> None:
    chained = tmp_path / 'chained.png'
    apart = tmp_path / 'apart.png'
    render_chart_image(parse_chart(make_chart(notes=_pair(make_note))), chained, seed=0)
    render_chart_image(parse_chart(make_chart(notes=_loose(make_note))), apart, seed=0)
    assert _count(chained, NOTE_COLORS[0]) > _count(apart, NOTE_COLORS[0])


def test_a_chain_of_one_is_not_a_chain(tmp_path: Path, make_chart: Callable[..., bytes],
                                       make_note: Callable[..., bytes]) -> None:
    alone = tmp_path / 'alone.png'
    pair = tmp_path / 'pair.png'
    render_chart_image(parse_chart(make_chart(notes=(make_note(travel_time=0),))), alone, seed=0)
    render_chart_image(parse_chart(make_chart(notes=_pair(make_note))), pair, seed=0)
    # A chain joins its notes, so it puts a line on the page that a lone note does not.
    assert _count(pair, NOTE_COLORS[0]) > _count(alone, NOTE_COLORS[0])


def test_an_unlinked_pair_is_two_chains_of_one(tmp_path: Path, make_chart: Callable[..., bytes],
                                               make_note: Callable[..., bytes]) -> None:
    # A chain is the note's own linked list, so two notes that name each other are one chain and
    # two that name nothing are not.
    split = tmp_path / 'split.png'
    together = tmp_path / 'together.png'
    render_chart_image(parse_chart(make_chart(notes=_loose(make_note))), split, seed=0)
    render_chart_image(parse_chart(make_chart(notes=_pair(make_note))), together, seed=0)
    assert _count(together, NOTE_COLORS[0]) > _count(split, NOTE_COLORS[0])


def test_each_side_takes_its_own_colour(tmp_path: Path, make_chart: Callable[..., bytes],
                                        make_note: Callable[..., bytes]) -> None:
    out = tmp_path / 'chart.png'
    notes = (make_note(start_time=3, side=0, kind=0, travel_time=0),
             make_note(start_time=5, side=1, kind=0, spawn_time=1000, travel_time=0))
    render_chart_image(parse_chart(make_chart(notes=notes)), out)
    assert _count(out, NOTE_COLORS[0]) > 0
    assert _count(out, NOTE_COLORS[1]) > 0


def test_a_chain_crossing_a_column_is_not_joined(tmp_path: Path, make_chart: Callable[..., bytes],
                                                 make_note: Callable[..., bytes]) -> None:
    # The second note wraps into the next column, where a joining line would have nowhere to go.
    notes = _pair(make_note, first=0, second=40_000)
    chart = parse_chart(make_chart(notes=notes, end_time=60_000))
    assert render_chart_image(chart, tmp_path / 'chart.png', seconds_per_column=30)[0] > 0


def test_a_chain_whose_note_is_off_the_image_is_left_out(tmp_path: Path,
                                                         make_chart: Callable[..., bytes],
                                                         make_note: Callable[..., bytes]) -> None:
    # The second note sits on the far column boundary, which falls outside every column.
    notes = _pair(make_note, first=0, second=30_000)
    chart = parse_chart(make_chart(notes=notes, end_time=0))
    assert render_chart_image(chart, tmp_path / 'chart.png', seconds_per_column=30)[0] > 0


def test_a_free_note_is_drawn(tmp_path: Path, make_chart: Callable[..., bytes],
                              make_note: Callable[..., bytes]) -> None:
    # A free note belongs to no chain but is still struck, so it is drawn like any other.
    free = tmp_path / 'free.png'
    empty = tmp_path / 'empty.png'
    render_chart_image(parse_chart(make_chart(notes=(make_note(start_time=-1),))), free)
    render_chart_image(parse_chart(make_chart()), empty)
    assert _count(free, NOTE_COLORS[0]) > _count(empty, NOTE_COLORS[0])


def test_notes_struck_together_take_neighbouring_lanes(tmp_path: Path, make_chart: Callable[...,
                                                                                            bytes],
                                                       make_note: Callable[..., bytes]) -> None:
    # Two notes on one side at one moment cannot share a lane, so the picture is wider than one.
    both = tmp_path / 'both.png'
    apart = tmp_path / 'apart.png'
    together = (make_note(start_time=-1, kind=0,
                          travel_time=0), make_note(start_time=-1, kind=1, travel_time=0))
    spread = (make_note(start_time=-1, kind=0, travel_time=0),
              make_note(start_time=-1, kind=1, spawn_time=2000, travel_time=0))
    render_chart_image(parse_chart(make_chart(notes=together)), both)
    render_chart_image(parse_chart(make_chart(notes=spread)), apart)
    assert both.read_bytes() != apart.read_bytes()


def test_a_hold_is_pinned_to_its_colour_tone_lane(tmp_path: Path, make_chart: Callable[..., bytes],
                                                  make_note: Callable[..., bytes]) -> None:
    # A hold takes the lane its colour tone names, whatever the seed, so two seeds agree on it.
    notes = (make_note(start_time=3, hold_kind=HOLD_HEAD_KIND, target=(0, 2, 0, 0), travel_time=0),)
    first = tmp_path / 'first.png'
    second = tmp_path / 'second.png'
    render_chart_image(parse_chart(make_chart(notes=notes)), first, seed=1)
    render_chart_image(parse_chart(make_chart(notes=notes)), second, seed=99)
    assert first.read_bytes() == second.read_bytes()


def test_an_aimed_note_ignores_the_seed(tmp_path: Path, make_chart: Callable[..., bytes],
                                        make_note: Callable[..., bytes]) -> None:
    # A note naming its own target is not one the tracker places, so no seed moves it.
    notes = (make_note(hold_kind=1, target=(0, 1, 0, 0), travel_time=0),)
    first = tmp_path / 'first.png'
    second = tmp_path / 'second.png'
    render_chart_image(parse_chart(make_chart(notes=notes)), first, seed=1)
    render_chart_image(parse_chart(make_chart(notes=notes)), second, seed=99)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize('tone', [-1, LANE_COUNT + 3])
def test_a_tone_naming_no_lane_leaves_the_note_free(tmp_path: Path, make_chart: Callable[...,
                                                                                         bytes],
                                                    make_note: Callable[...,
                                                                        bytes], tone: int) -> None:
    # A colour tone outside the field pins nothing, so the seed picks the lane as usual.
    notes = (make_note(start_time=3,
                       hold_kind=HOLD_HEAD_KIND,
                       target=(0, tone, 0, 0),
                       travel_time=0),
             make_note(start_time=5,
                       note_type=SLIDE_NOTE_TYPE,
                       target=(0, tone, 0, 0),
                       spawn_time=2000,
                       travel_time=0))
    out = tmp_path / 'chart.png'
    assert render_chart_image(parse_chart(make_chart(notes=notes)), out)[0] > 0


def test_the_seed_changes_the_layout(tmp_path: Path, make_chart: Callable[..., bytes],
                                     make_note: Callable[..., bytes]) -> None:
    # Enough unpinned notes at distinct times that two seeds are very unlikely to agree.
    notes = tuple(
        make_note(start_time=index, kind=0, spawn_time=index * 400, travel_time=0)
        for index in range(1, 30))
    rendered = set()
    for seed in range(6):
        out = tmp_path / f'{seed}.png'
        render_chart_image(parse_chart(make_chart(notes=notes)), out, seed=seed)
        rendered.add(out.read_bytes())
    assert len(rendered) > 1


def test_a_chart_wider_than_the_field_still_lays_out(tmp_path: Path, make_chart: Callable[...,
                                                                                          bytes],
                                                     make_note: Callable[..., bytes]) -> None:
    # More notes struck at one moment than the field has lanes, which no chart should hold but the
    # layout must survive.
    notes = tuple(
        make_note(start_time=3, kind=index, travel_time=0) for index in range(LANE_COUNT + 3))
    out = tmp_path / 'chart.png'
    assert render_chart_image(parse_chart(make_chart(notes=notes)), out)[0] > 0


def test_the_header_text_is_drawn(tmp_path: Path, chart_bytes: bytes) -> None:
    out = tmp_path / 'chart.png'
    plain = render_chart_image(parse_chart(chart_bytes), out)
    titled = render_chart_image(parse_chart(chart_bytes),
                                out,
                                artist='Artist',
                                difficulty='basic',
                                level=7,
                                title='Title')
    # The header block is a fixed height, so adding text does not change the canvas.
    assert plain == titled


def test_a_longer_chart_takes_more_columns(tmp_path: Path, make_chart: Callable[..., bytes],
                                           make_note: Callable[..., bytes]) -> None:
    short = parse_chart(
        make_chart(notes=(make_note(spawn_time=0, travel_time=1000),), end_time=10_000))
    long = parse_chart(
        make_chart(notes=(make_note(spawn_time=0, travel_time=1000),), end_time=300_000))
    short_width, _ = render_chart_image(short, tmp_path / 'short.png')
    long_width, _ = render_chart_image(long, tmp_path / 'long.png')
    assert long_width > short_width


def test_an_empty_chart_still_renders(tmp_path: Path, make_chart: Callable[..., bytes]) -> None:
    out = tmp_path / 'empty.png'
    assert render_chart_image(parse_chart(make_chart(end_time=0)), out)[0] > 0
    assert out.is_file()


def test_seconds_per_column_changes_the_layout(tmp_path: Path, chart_bytes: bytes) -> None:
    chart = parse_chart(chart_bytes)
    tall = render_chart_image(chart, tmp_path / 'tall.png', seconds_per_column=60)
    short = render_chart_image(chart, tmp_path / 'short.png', seconds_per_column=10)
    assert tall[1] > short[1]


@pytest.mark.parametrize('seconds', [0, -5])
def test_a_non_positive_column_span_is_rejected(tmp_path: Path, chart_bytes: bytes,
                                                seconds: int) -> None:
    with pytest.raises(ValueError, match='must be positive'):
        render_chart_image(parse_chart(chart_bytes),
                           tmp_path / 'chart.png',
                           seconds_per_column=seconds)


def test_a_note_beyond_the_last_column_is_dropped(tmp_path: Path, make_chart: Callable[..., bytes],
                                                  make_note: Callable[..., bytes],
                                                  make_tempo_event: Callable[..., bytes]) -> None:
    # An event past the chart's own end time falls outside every column and must not be drawn.
    chart = parse_chart(
        make_chart(notes=(make_note(spawn_time=0, travel_time=1000),),
                   tempo_events=(make_tempo_event(kind=3, time=10_000_000),),
                   end_time=5_000))
    assert render_chart_image(chart, tmp_path / 'chart.png')[0] > 0


def test_a_note_on_the_far_column_boundary_is_dropped(tmp_path: Path, make_chart: Callable[...,
                                                                                           bytes],
                                                      make_note: Callable[..., bytes]) -> None:
    # The span is exactly one column wide, so a note at its far edge falls into a column that does
    # not exist and is skipped rather than drawn off the canvas.
    chart = parse_chart(
        make_chart(notes=(make_note(spawn_time=0,
                                    travel_time=0), make_note(spawn_time=30_000, travel_time=0)),
                   end_time=0))
    assert render_chart_image(chart, tmp_path / 'chart.png', seconds_per_column=30)[0] > 0


def test_an_unknown_side_is_drawn_on_the_first_track(tmp_path: Path, make_chart: Callable[...,
                                                                                          bytes],
                                                     make_note: Callable[..., bytes]) -> None:
    chart = parse_chart(make_chart(notes=(make_note(start_time=3, side=SIDE_COUNT + 3),)))
    assert render_chart_image(chart, tmp_path / 'chart.png')[0] > 0


def test_a_slot_beyond_the_bar_is_drawn_in_the_first(tmp_path: Path, make_chart: Callable[...,
                                                                                          bytes],
                                                     make_note: Callable[..., bytes]) -> None:
    chart = parse_chart(make_chart(notes=(make_note(start_time=3, kind=LANE_COUNT + 2),)))
    assert render_chart_image(chart, tmp_path / 'chart.png')[0] > 0


def _gold_baseline(tmp_path: Path, make_chart: Callable[..., bytes]) -> int:
    """Count the gold an empty chart carries, which is the legend's own mark."""
    out = tmp_path / 'gold-base.png'
    render_chart_image(parse_chart(make_chart()), out, seed=0)
    return _near(out, SIDE_OBJECT_COLOR)


def test_a_note_that_travels_across_is_gold(tmp_path: Path, make_chart: Callable[..., bytes],
                                            make_note: Callable[..., bytes]) -> None:
    out = tmp_path / 'chart.png'
    note = make_note(flags=SIDE_OBJECT_FLAG, path_points=(0,), travel_time=0)
    render_chart_image(parse_chart(make_chart(notes=(note,))), out, seed=0)
    assert _near(out, SIDE_OBJECT_COLOR) > _gold_baseline(tmp_path, make_chart)


def test_a_note_that_travels_keeps_its_side_colour(tmp_path: Path, make_chart: Callable[..., bytes],
                                                   make_note: Callable[..., bytes]) -> None:
    # Only half the note is gold, so it still says whose it is. Half a disc is small enough that the
    # reduction leaves no pixel holding either colour exactly, so both are counted by nearness.
    out = tmp_path / 'chart.png'
    empty = tmp_path / 'empty.png'
    note = make_note(flags=SIDE_OBJECT_FLAG, path_points=(0,), travel_time=0)
    render_chart_image(parse_chart(make_chart(notes=(note,))), out, seed=0)
    render_chart_image(parse_chart(make_chart()), empty, seed=0)
    assert _near(out, NOTE_COLORS[0]) > _near(empty, NOTE_COLORS[0])
    assert _near(out, SIDE_OBJECT_COLOR) > _near(empty, SIDE_OBJECT_COLOR)


def test_a_note_that_stays_is_not_gold(tmp_path: Path, make_chart: Callable[..., bytes],
                                       make_note: Callable[..., bytes]) -> None:
    out = tmp_path / 'chart.png'
    render_chart_image(parse_chart(make_chart(notes=(make_note(travel_time=0),))), out, seed=0)
    assert _near(out, SIDE_OBJECT_COLOR) == _gold_baseline(tmp_path, make_chart)


@pytest.mark.parametrize('speed', [1.0, 1.5, 2.0])
def test_the_speed_modifier_spreads_the_notes(tmp_path: Path, make_chart: Callable[..., bytes],
                                              make_note: Callable[...,
                                                                  bytes], speed: float) -> None:
    chart = parse_chart(make_chart(notes=(make_note(travel_time=0),)))
    plain = render_chart_image(chart, tmp_path / 'plain.png', seed=0)
    faster = render_chart_image(chart, tmp_path / 'fast.png', seed=0, speed=speed)
    # A column holds the same span of time either way, so only the height grows.
    assert faster[0] == plain[0]
    assert faster[1] >= plain[1]
    assert (faster[1] > plain[1]) == (speed > DEFAULT_SPEED)


@pytest.mark.parametrize('scale', [1.0, 2.0, 3.0])
def test_the_scale_writes_a_larger_image(tmp_path: Path, make_chart: Callable[..., bytes],
                                         make_note: Callable[..., bytes], scale: float) -> None:
    chart = parse_chart(make_chart(notes=(make_note(travel_time=0),)))
    plain = render_chart_image(chart, tmp_path / 'plain.png', seed=0)
    bigger = render_chart_image(chart, tmp_path / 'big.png', scale=scale, seed=0)
    assert bigger[0] == pytest.approx(plain[0] * scale, abs=2)
    assert bigger[1] == pytest.approx(plain[1] * scale, abs=2)


def _pixels_of(path: Path, wanted: tuple[int, int, int]) -> set[tuple[int, int]]:
    """Find every pixel of one colour, as column and row."""
    with Image.open(path) as image:
        pixels = image.convert('RGB').load()
        assert pixels is not None
        return {(x, y)
                for x in range(image.width)
                for y in range(image.height)
                if cast('tuple[int, int, int]', pixels[x, y]) == wanted}


@pytest.mark.parametrize('seed', range(8))
def test_a_hold_keeps_its_lane_until_released(tmp_path: Path, make_chart: Callable[..., bytes],
                                              make_note: Callable[..., bytes], seed: int) -> None:
    # A note struck while a hold is still running may not be put in the hold's lane. The hold's body
    # is drawn in a colour nothing else uses, so it says where the hold's lane is; between the
    # hold's own two ends the only note-coloured mark is the other note.
    out = tmp_path / f'chart{seed}.png'
    notes = (make_note(note_id=1, note_type=HOLD_NOTE_TYPE, target=(4000, 0, 0, 0),
                       travel_time=0), make_note(note_id=2, spawn_time=1000, travel_time=0))
    render_chart_image(parse_chart(make_chart(notes=notes)), out, seed=seed)
    drawn = _pixels_of(out, NOTE_COLORS[0])
    # The hold's bar is a tall run in one column, so the columns holding the most of it are its
    # lane; every other mark is the note struck while it runs.
    per_column = Counter(x for x, _ in drawn)
    tallest = max(per_column.values())
    held_lane = {x for x, count in per_column.items() if count > tallest // 2}
    rows = {y for x, y in drawn if x in held_lane}
    other = {x for x, y in drawn if min(rows) < y < max(rows) and x not in held_lane}
    assert held_lane
    assert other
    assert not (other & held_lane)


_MODERN = 14
"""A chart version past the one where the route selector is read through the remap."""


@pytest.mark.parametrize(('tone', 'pinned'), [(-3, False), (-4, False), (3, True), (5, True),
                                              (LANE_COUNT * 3, False)])
def test_a_modern_chart_reads_its_route_through_the_remap(tmp_path: Path,
                                                          make_chart: Callable[..., bytes],
                                                          make_note: Callable[..., bytes],
                                                          tone: int, *, pinned: bool) -> None:
    # Only a chart past version twelve takes the remap. A tone the remap sends into the seven lanes
    # pins the note there; the two swapped markers and a tone naming no lane leave it to the seed.
    chart = parse_chart(
        make_chart(notes=(make_note(target=(0, tone, 0, 0), travel_time=0),), version=_MODERN))
    places = set(_lane_positions(chart, tmp_path, seeds=tuple(range(12))))
    assert (len(places) == 1) is pinned


def _lane_positions(chart: object, tmp_path: Path, seeds: tuple[int, ...]) -> list[float]:
    """Find the mean column of the note colour under each of several seeds."""
    out = []
    for seed in seeds:
        path = tmp_path / f'seed{seed}.png'
        render_chart_image(cast('Any', chart), path, seed=seed)
        columns = [x for x, _ in _pixels_of(path, NOTE_COLORS[0])]
        out.append(sum(columns) / len(columns) if columns else 0.0)
    return out


def test_a_note_naming_a_lane_ignores_the_seed(tmp_path: Path, make_chart: Callable[..., bytes],
                                               make_note: Callable[..., bytes]) -> None:
    # A selector naming one of the seven lanes comes straight down into it, so no seed moves it.
    chart = parse_chart(
        make_chart(notes=(make_note(target=(0, 2, 0, 0), travel_time=0),), version=_MODERN))
    first, second = _lane_positions(chart, tmp_path, seeds=(1, 999))
    assert first == second


def test_a_slide_draws_its_track(tmp_path: Path, make_chart: Callable[..., bytes],
                                 make_note: Callable[..., bytes],
                                 make_slide: Callable[..., bytes]) -> None:
    out = tmp_path / 'chart.png'
    plain = tmp_path / 'plain.png'
    note = make_note(note_type=SLIDE_NOTE_TYPE, target=(0, 6, 0, 0), travel_time=0)
    slides = (make_slide(field2=0, lane=0, note_index=0, value_a=1000, value_b=0),
              make_slide(field2=1, lane=3, note_index=0, value_a=2000, value_b=0))
    render_chart_image(parse_chart(make_chart(notes=(note,), slides=slides, version=_MODERN)),
                       out,
                       seed=0)
    render_chart_image(parse_chart(make_chart(notes=(note,), version=_MODERN)), plain, seed=0)
    assert _count(out, SLIDE_COLOR) > _count(plain, SLIDE_COLOR)


def test_a_slide_naming_no_note_is_left_out(tmp_path: Path, make_chart: Callable[..., bytes],
                                            make_note: Callable[..., bytes],
                                            make_slide: Callable[..., bytes]) -> None:
    # A record whose note index is past the end of the chart names nothing to start from.
    note = make_note(note_type=SLIDE_NOTE_TYPE, target=(0, 6, 0, 0), travel_time=0)
    slides = (make_slide(note_index=99, lane=0, value_a=1000, value_b=0),)
    chart = parse_chart(make_chart(notes=(note,), slides=slides, version=_MODERN))
    assert render_chart_image(chart, tmp_path / 'chart.png', seed=0)[0] > 0


def test_a_waypoint_outside_the_image_is_left_out(tmp_path: Path, make_chart: Callable[..., bytes],
                                                  make_note: Callable[..., bytes],
                                                  make_slide: Callable[..., bytes]) -> None:
    note = make_note(note_type=SLIDE_NOTE_TYPE, target=(0, 6, 0, 0), travel_time=0)
    slides = (make_slide(lane=0, note_index=0, value_a=10_000_000, value_b=0),)
    chart = parse_chart(make_chart(notes=(note,), slides=slides, version=_MODERN, end_time=5000))
    assert render_chart_image(chart, tmp_path / 'chart.png', seed=0)[0] > 0


def test_a_slide_leg_across_two_columns_is_not_drawn(tmp_path: Path, make_chart: Callable[...,
                                                                                          bytes],
                                                     make_note: Callable[..., bytes],
                                                     make_slide: Callable[..., bytes]) -> None:
    # One column holds thirty seconds, so a waypoint a minute later lands in another and there is
    # nowhere to run the leg.
    out = tmp_path / 'chart.png'
    base = tmp_path / 'base.png'
    note = make_note(note_type=SLIDE_NOTE_TYPE, target=(0, 6, 0, 0), travel_time=0)
    far = (make_slide(lane=0, note_index=0, value_a=60_000, value_b=0),)
    near = (make_slide(lane=0, note_index=0, value_a=1000, value_b=0),)
    for slides, path in ((far, out), (near, base)):
        render_chart_image(parse_chart(
            make_chart(notes=(note,), slides=slides, version=_MODERN, end_time=90_000)),
                           path,
                           seconds_per_column=30,
                           seed=0)
    # The far waypoint leaves neither a leg nor a dot behind, while the near one draws both.
    assert _count(out, SLIDE_COLOR) < _count(base, SLIDE_COLOR)
