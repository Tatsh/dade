"""Tests for :py:mod:`dade.common.ssq`."""
from __future__ import annotations

import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.common.ssq import (
    TICKS_PER_MEASURE,
    Chart,
    TempoMap,
    chart_notes,
    parse_ssq,
)


def _step_chunk(parameter: int,
                ticks: tuple[int, ...],
                steps: bytes,
                freezes: bytes = b'') -> bytes:
    body = (struct.pack('<I', len(ticks)) + struct.pack(f'<{len(ticks)}I', *ticks) + steps +
            bytes(len(steps) % 2) + freezes)
    body += bytes(-len(body) % 4)
    return struct.pack('<IHH', 8 + len(body), 3, parameter) + body


def _tempo_chunk(beats: tuple[int, ...], times: tuple[int, ...], fps: int = 150) -> bytes:
    body = (struct.pack('<I', len(beats)) + struct.pack(f'<{len(beats)}i', *beats) +
            struct.pack(f'<{len(times)}i', *times))
    return struct.pack('<IHH', 8 + len(body), 1, fps) + body


def test_an_empty_file_parses_to_nothing() -> None:
    assert parse_ssq(b'') == (None, ())


def test_the_terminator_stops_the_walk() -> None:
    assert parse_ssq(bytes(4) + _step_chunk(0x0114, (0,), b'\x01')).charts == ()


@pytest.mark.parametrize(('parameter', 'difficulty', 'panels', 'division'), [(0x0114, 1, 4, 1),
                                                                             (0x0214, 2, 4, 1),
                                                                             (0x0314, 3, 4, 1),
                                                                             (0x0414, 4, 4, 1),
                                                                             (0x0118, 1, 8, 1),
                                                                             (0x0318, 3, 8, 1)])
def test_the_parameter_splits_into_difficulty_panels_and_division(parameter: int, difficulty: int,
                                                                  panels: int,
                                                                  division: int) -> None:
    chart = parse_ssq(_step_chunk(parameter, (0,), b'\x01')).charts[0]
    assert (chart.difficulty, chart.panels, chart.division) == (difficulty, panels, division)


def test_a_step_byte_is_a_panel_bitmask() -> None:
    chart = parse_ssq(_step_chunk(0x0114, (0, 1024), b'\x01\x0a')).charts[0]
    assert chart.events() == {0: {0: '1'}, 1024: {1: '1', 3: '1'}}


def test_a_shock_arrow_becomes_a_row_of_mines() -> None:
    chart = parse_ssq(_step_chunk(0x0114, (0,), b'\xff')).charts[0]
    assert chart.events() == {0: dict.fromkeys(range(4), 'M')}


def test_a_freeze_marker_promotes_the_previous_note_in_that_column() -> None:
    # A tap on panel 0, then a freeze end naming panel 0.
    chart = parse_ssq(_step_chunk(0x0114, (0, 1024), b'\x01\x00', b'\x01\x01')).charts[0]
    assert chart.events() == {0: {0: '2'}, 1024: {0: '3'}}


def test_a_freeze_of_an_unknown_kind_is_ignored() -> None:
    chart = parse_ssq(_step_chunk(0x0114, (0, 1024), b'\x01\x00', b'\x01\x09')).charts[0]
    assert chart.events() == {0: {0: '1'}}


def test_a_freeze_with_no_earlier_note_is_dropped() -> None:
    chart = parse_ssq(_step_chunk(0x0114, (0,), b'\x00', b'\x01\x01')).charts[0]
    assert chart.events() == {}


def test_the_note_count_ignores_freeze_markers() -> None:
    chart = parse_ssq(_step_chunk(0x0114, (0, 1024, 2048), b'\x01\x00\x02', b'\x01\x01')).charts[0]
    assert chart.note_count == 2


def test_the_tempo_map_yields_the_bpm_the_deltas_imply() -> None:
    # 256 beats in 14583/150 seconds is 158 BPM.
    tempo = parse_ssq(_tempo_chunk((0, 262144), (0, 14583))).tempo
    assert tempo is not None
    (beat, bpm), = tempo.bpms()
    assert beat == pytest.approx(0.0)
    assert bpm == pytest.approx(157.99, rel=1e-3)


def test_a_constant_tempo_collapses_to_one_entry() -> None:
    tempo = TempoMap(150, (0, 4096, 8192), (0, 227, 454))
    assert len(tempo.bpms()) == 1


def test_a_map_with_no_usable_span_still_yields_one_entry() -> None:
    assert TempoMap(150, (0,), (0,)).bpms() == ((0.0, 0.0),)


def test_entries_sharing_a_beat_are_a_stop() -> None:
    tempo = TempoMap(150, (0, 4096, 4096, 8192), (0, 227, 377, 604))
    assert tempo.stops() == ((4.0, 1.0),)


def test_a_zero_length_segment_produces_no_tempo_change() -> None:
    tempo = TempoMap(150, (0, 4096, 4096), (0, 227, 377))
    assert len(tempo.bpms()) == 1


def test_unknown_chunk_types_are_skipped() -> None:
    trigger = struct.pack('<IHH', 12, 2, 1) + struct.pack('<I', 0)
    assert parse_ssq(trigger + _step_chunk(0x0114, (0,), b'\x01')).charts[0].difficulty == 1


def test_a_chunk_running_past_the_end_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='does not fit'):
        parse_ssq(struct.pack('<IHH', 4096, 3, 0x0114) + struct.pack('<I', 0))


def test_a_chunk_too_short_for_a_count_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='does not fit'):
        parse_ssq(struct.pack('<IHH', 8, 3, 0x0114))


def test_a_chunk_claiming_more_entries_than_it_holds_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='does not hold'):
        parse_ssq(struct.pack('<IHH', 16, 3, 0x0114) + struct.pack('<II', 999, 0))


def test_notes_render_one_measure_per_block() -> None:
    chart = Chart(0x0114, (0, TICKS_PER_MEASURE), b'\x01\x02', ())
    assert chart_notes(chart).count(',') == 1


def test_an_empty_chart_renders_a_single_empty_row() -> None:
    assert chart_notes(Chart(0x0114, (), b'', ())) == '0000'
