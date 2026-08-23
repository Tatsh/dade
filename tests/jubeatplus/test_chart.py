"""Tests for :py:mod:`destin.jubeatplus.chart`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.jubeatplus.chart import MAGICS, SECTORS_PER_SECOND, parse_chart

if TYPE_CHECKING:
    from collections.abc import Callable


def test_header_fields(make_chart: Callable[..., bytes]) -> None:
    chart = parse_chart(make_chart(events=((1, 300, 3),)))
    header = chart['header']
    assert header['magic'] == 'IJBQ'
    assert header['event_count'] == 1
    assert header['end_sector'] == 3000
    assert header['end_time'] == pytest.approx(10.0)
    assert header['first_marker'] == 8
    assert header['first_marker_sector'] == 300
    assert header['first_marker_time'] == pytest.approx(1.0)
    assert header['unknown_0x10'] == 2
    assert header['music_bar'] == bytes(range(60)).hex()
    assert header['reserved'] == bytes(12).hex()
    assert chart['sectors_per_second'] == SECTORS_PER_SECOND


@pytest.mark.parametrize('magic', MAGICS)
def test_every_accepted_magic(magic: bytes, make_chart: Callable[..., bytes]) -> None:
    assert parse_chart(make_chart(magic))['header']['magic'] == magic.decode()


def test_a_tap_event(make_chart: Callable[..., bytes]) -> None:
    event = parse_chart(make_chart(events=((1, 600, 12),)))['events'][0]
    assert event['kind'] == 'tap'
    assert event['kind_id'] == 1
    assert event['panel'] == 12
    assert event['sector'] == 600
    assert event['time'] == pytest.approx(2.0)
    assert event['bpm'] is None
    assert event['hold_length_sectors'] is None


def test_a_hold_event(make_chart: Callable[..., bytes]) -> None:
    # Panel 5 in the low nibble, direction 2 above it, and a 300-sector length from bit eight up.
    event = parse_chart(make_chart(events=((6, 900, (300 << 8) | (2 << 4) | 5),)))['events'][0]
    assert event['kind'] == 'hold'
    assert event['panel'] == 5
    assert event['move'] == 2
    assert event['hold_length_sectors'] == 300


def test_a_tempo_event(make_chart: Callable[..., bytes]) -> None:
    event = parse_chart(make_chart(events=((5, 0, 500000),)))['events'][0]
    assert event['kind'] == 'tempo'
    assert event['microseconds_per_beat'] == 500000
    assert event['bpm'] == pytest.approx(120.0)


def test_a_zero_tempo_is_left_alone(make_chart: Callable[..., bytes]) -> None:
    event = parse_chart(make_chart(events=((5, 0, 0),)))['events'][0]
    assert event['microseconds_per_beat'] is None
    assert event['bpm'] is None


def test_an_unknown_kind_keeps_its_number(make_chart: Callable[..., bytes]) -> None:
    assert parse_chart(make_chart(events=((9, 0, 0),)))['events'][0]['kind'] == 'unknown_9'


def test_counts_and_note_count(make_chart: Callable[..., bytes]) -> None:
    chart = parse_chart(
        make_chart(events=((1, 0, 0), (1, 10, 1), (6, 20, 2), (3, 30, 0), (4, 40, 0))))
    assert chart['counts'] == {'beat': 1, 'hold': 1, 'measure': 1, 'tap': 2}
    # A hold scores at its head and again at its release, so it counts twice.
    assert chart['note_count'] == 4


def test_the_recorded_note_count_is_kept_separately(make_chart: Callable[..., bytes]) -> None:
    chart = parse_chart(make_chart(events=((1, 0, 0),), note_count=99))
    assert chart['header']['note_count'] == 99
    assert chart['note_count'] == 1


def test_the_difficulty_is_recorded(make_chart: Callable[..., bytes]) -> None:
    assert parse_chart(make_chart(), 'extreme')['difficulty'] == 'extreme'
    assert parse_chart(make_chart())['difficulty'] is None


def test_the_counts_are_sorted_by_name(make_chart: Callable[..., bytes]) -> None:
    chart = parse_chart(make_chart(events=((5, 0, 1), (1, 10, 0), (2, 20, 0), (6, 30, 0))))
    assert list(chart['counts']) == ['end', 'hold', 'tap', 'tempo']


def test_the_event_word_splits_at_its_low_byte(make_chart: Callable[..., bytes]) -> None:
    # The widest sector the packing can hold, beside a kind byte that fills its own eight bits.
    event = parse_chart(make_chart(events=((0xFF, 0xFF_FFFF, 0),)))['events'][0]
    assert event['kind_id'] == 0xFF
    assert event['kind'] == 'unknown_255'
    assert event['sector'] == 0xFF_FFFF


def test_a_hold_packed_to_its_limits(make_chart: Callable[..., bytes]) -> None:
    event = parse_chart(
        make_chart(events=((6, 0, (0xFF_FFFF << 8) | (15 << 4) | 15),)))['events'][0]
    assert event['panel'] == 15
    assert event['move'] == 15
    assert event['hold_length_sectors'] == 0xFF_FFFF


def test_a_header_and_nothing_else(make_chart: Callable[..., bytes]) -> None:
    header = make_chart()
    assert len(header) == 0x60
    chart = parse_chart(header)
    assert chart['events'] == []
    assert chart['counts'] == {}
    assert chart['note_count'] == 0
    with pytest.raises(ValueError, match='Too short for a 96-byte chart header: 95 bytes'):
        parse_chart(header[:-1])


def test_one_byte_short_of_the_event_table(make_chart: Callable[..., bytes]) -> None:
    blob = make_chart(events=((1, 0, 0), (1, 8, 1)))
    assert len(blob) == 0x60 + 16
    assert len(parse_chart(blob)['events']) == 2
    with pytest.raises(ValueError, match='Too short for 2 events: 111 bytes, 112 needed'):
        parse_chart(blob[:-1])


def test_bytes_after_the_event_table_are_ignored(make_chart: Callable[..., bytes]) -> None:
    blob = make_chart(events=((1, 300, 3),))
    assert parse_chart(blob + b'\xff' * 9) == parse_chart(blob)


def test_a_short_blob_is_rejected() -> None:
    with pytest.raises(ValueError, match='Too short for a 96-byte chart header'):
        parse_chart(b'IJBQ')


def test_a_foreign_magic_is_rejected(make_chart: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='Not a chart'):
        parse_chart(make_chart(b'NOPE'))


def test_a_truncated_event_table_is_rejected(make_chart: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='Too short for 2 events'):
        parse_chart(make_chart(events=((1, 0, 0), (1, 8, 1)))[:-8])
