"""Tests for :py:mod:`dade.rbplus.chart`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.rbplus.chart import ChartError, flag_names, parse_chart

if TYPE_CHECKING:
    from collections.abc import Callable


def test_parse_chart_reads_the_header(chart_bytes: bytes) -> None:
    header = parse_chart(chart_bytes)['header']
    assert header == {
        'end_time': 30000,
        'free_note_count': 1,
        'initial_speed': 400,
        'note_count': 4,
        'seed': 7,
        'slide_record_count': 1,
        'tempo_event_count': 2,
        'version': 11,
    }


def test_parse_chart_reads_every_record(chart_bytes: bytes) -> None:
    chart = parse_chart(chart_bytes)
    assert len(chart['notes']) == chart['header']['note_count']
    assert len(chart['tempo_events']) == chart['header']['tempo_event_count']
    assert len(chart['slides']) == chart['header']['slide_record_count']


def test_hit_time_is_the_two_times_added(chart_bytes: bytes) -> None:
    first = parse_chart(chart_bytes)['notes'][0]
    assert first['spawn_time'] == 0
    assert first['travel_time'] == 1000
    assert first['hit_time'] == 1000


def test_a_note_carries_its_path_points(chart_bytes: bytes) -> None:
    assert parse_chart(chart_bytes)['notes'][1]['path_points'] == (3, 4)


def test_a_note_without_a_path_has_none(chart_bytes: bytes) -> None:
    assert parse_chart(chart_bytes)['notes'][0]['path_points'] == ()


def test_a_long_note_head_carries_its_chain(chart_bytes: bytes) -> None:
    notes = parse_chart(chart_bytes)['notes']
    assert notes[2]['chain'] == (4, 0, 0, 0)
    assert notes[2]['flags'] & 0x08
    assert notes[0]['chain'] is None


def test_a_free_note_has_no_start_time(chart_bytes: bytes) -> None:
    assert parse_chart(chart_bytes)['notes'][1]['start_time'] == -1


def test_the_speed_change_is_read(chart_bytes: bytes) -> None:
    events = parse_chart(chart_bytes)['tempo_events']
    assert events[0]['kind'] == 3
    assert events[0]['speed'] == 800
    assert events[0]['time'] == 2000
    assert len(events[0]['raw']) == 72


def test_a_non_speed_event_is_still_reported(chart_bytes: bytes) -> None:
    assert parse_chart(chart_bytes)['tempo_events'][1]['kind'] == 1


def test_a_slide_record_is_read(chart_bytes: bytes) -> None:
    slide = parse_chart(chart_bytes)['slides'][0]
    assert slide['note_index'] == 1
    assert slide['lane'] == 6


@pytest.mark.parametrize(('raw', 'expected'), [(0, 6), (6, 0), (7, 9), (9, 7), (0xFFFF, -2),
                                               (0xFFFE, -2), (0xFFFD, -4), (0xFFFC, -3),
                                               (0x1234, 0x1234)])
def test_slide_lanes_are_remapped(make_chart: Callable[..., bytes], make_slide: Callable[...,
                                                                                         bytes],
                                  raw: int, expected: int) -> None:
    chart = parse_chart(make_chart(slides=(make_slide(lane=raw),)))
    assert chart['slides'][0]['lane'] == expected


def test_a_chart_with_no_records_parses(make_chart: Callable[..., bytes]) -> None:
    chart = parse_chart(make_chart())
    assert chart['notes'] == []
    assert chart['tempo_events'] == []
    assert chart['slides'] == []


def test_a_negative_slide_count_reads_no_slides(make_chart: Callable[..., bytes]) -> None:
    data = bytearray(make_chart())
    struct.pack_into('<i', data, 16 + 0x14, -3)
    assert parse_chart(bytes(data))['slides'] == []


@pytest.mark.parametrize('version', [10, 11, 12, 13, 14])
def test_every_modern_version_parses(make_chart: Callable[..., bytes], version: int) -> None:
    assert parse_chart(make_chart(version=version))['header']['version'] == version


def test_a_wrong_magic_is_not_a_chart(make_chart: Callable[..., bytes]) -> None:
    with pytest.raises(ChartError, match='Not a chart'):
        parse_chart(make_chart(magic=b'JBSQ'))


@pytest.mark.parametrize('version', [6, 7])
def test_a_legacy_version_is_named_as_such(make_chart: Callable[..., bytes], version: int) -> None:
    with pytest.raises(ChartError, match='legacy layout'):
        parse_chart(make_chart(version=version))


def test_an_unknown_version_is_rejected(make_chart: Callable[..., bytes]) -> None:
    with pytest.raises(ChartError, match='no known layout'):
        parse_chart(make_chart(version=99))


def test_a_chart_that_ends_inside_a_note_is_rejected(make_chart: Callable[..., bytes],
                                                     make_note: Callable[..., bytes]) -> None:
    truncated = make_chart(notes=(make_note(),))[:-4]
    with pytest.raises(ChartError, match='ends inside a record'):
        parse_chart(truncated)


def test_a_chart_promising_more_notes_than_it_holds_is_rejected(
        make_chart: Callable[..., bytes], make_note: Callable[..., bytes]) -> None:
    with pytest.raises(ChartError, match='ends inside a record'):
        parse_chart(make_chart(notes=(make_note(),), note_count=4))


def test_a_truncated_tempo_event_is_rejected(make_chart: Callable[..., bytes],
                                             make_tempo_event: Callable[..., bytes]) -> None:
    truncated = make_chart(tempo_events=(make_tempo_event(),))[:-8]
    with pytest.raises(ChartError, match='Truncated tempo event'):
        parse_chart(truncated)


def test_a_truncated_slide_record_is_rejected(make_chart: Callable[..., bytes],
                                              make_slide: Callable[..., bytes]) -> None:
    truncated = make_chart(slides=(make_slide(),))[:-4]
    with pytest.raises(ChartError, match='ends inside a record'):
        parse_chart(truncated)


@pytest.mark.parametrize(('flags', 'expected'), [
    (0, ()),
    (0x01, ('same_lane',)),
    (0x10, ('free',)),
    (0x05, ('same_lane', 'different_lane')),
    (0x7D, ('same_lane', 'different_lane', 'long_head', 'free', 'has_path', 'side_object')),
    (0x02, ()),
])
def test_flag_names_names_the_set_bits(flags: int, expected: tuple[str, ...]) -> None:
    assert flag_names(flags) == expected
