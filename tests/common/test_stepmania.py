"""Tests for :py:mod:`destin.common.stepmania`."""
from __future__ import annotations

from destin.common.stepmania import SimfileChart, quantize_measures, write_sm
import pytest

_MEASURE = 4096


def test_an_empty_chart_renders_a_single_empty_row() -> None:
    assert quantize_measures({}, 4, _MEASURE) == '0000'


def test_quarter_notes_stay_four_rows() -> None:
    events = {offset: {0: '1'} for offset in (0, 1024, 2048, 3072)}
    assert quantize_measures(events, 4, _MEASURE).count('\n') == 3


def test_a_sixteenth_forces_sixteen_rows() -> None:
    assert quantize_measures({256: {0: '1'}}, 4, _MEASURE).count('\n') == 15


def test_measures_are_separated_by_commas() -> None:
    events = {0: {0: '1'}, _MEASURE * 2: {1: '1'}}
    assert quantize_measures(events, 4, _MEASURE).count(',') == 2


def test_a_triplet_is_matched_within_tolerance() -> None:
    # A twelfth of a measure is 341.33 ticks, which no power of two divides.
    events = {round(_MEASURE * index / 12): {0: '1'} for index in range(12)}
    assert quantize_measures(events, 4, _MEASURE).count('\n') == 11


def test_an_offset_no_candidate_fits_falls_back_to_the_finest_grid() -> None:
    # A note at tick 11 sits within tolerance of no candidate row grid, so the finest, 192, is
    # used.
    assert quantize_measures({11: {0: '1'}}, 4, _MEASURE).count('\n') == 191


def test_columns_past_the_panel_count_are_dropped() -> None:
    assert quantize_measures({0: {7: '1'}}, 4, _MEASURE).splitlines()[0] == '0000'


def test_a_row_holds_one_character_per_panel() -> None:
    assert len(quantize_measures({0: {0: '1'}}, 8, _MEASURE).splitlines()[0]) == 8


@pytest.mark.parametrize(('gap', 'expected'), [(0.0, '#OFFSET:-0.000;'), (5.339, '#OFFSET:-5.339;'),
                                               (1.5, '#OFFSET:-1.500;')])
def test_the_offset_is_the_negated_gap(gap: float, expected: str) -> None:
    assert expected in write_sm((), ((0.0, 158.0),), gap=gap)


def test_the_headers_carry_the_song_details() -> None:
    out = write_sm((), ((0.0, 158.0),),
                   artist='kors k',
                   banner='b.png',
                   music='m.mp3',
                   title='All My Love')
    assert '#TITLE:All My Love;' in out
    assert '#ARTIST:kors k;' in out
    assert '#BANNER:b.png;' in out
    assert '#MUSIC:m.mp3;' in out


def test_bpms_and_stops_are_formatted_as_beat_equals_value() -> None:
    out = write_sm((), ((0.0, 158.0), (4.0, 160.0)), stops=((8.0, 0.5),))
    assert '#BPMS:0.000=158.000,\n4.000=160.000;' in out
    assert '#STOPS:8.000=0.500;' in out


def test_each_chart_becomes_a_notes_block() -> None:
    charts = (SimfileChart('dance-single', 'Hard', 10,
                           '0000'), SimfileChart('dance-double', 'Easy', 0, '00000000'))
    out = write_sm(charts, ((0.0, 158.0),))
    assert out.count('#NOTES:') == 2
    assert '     dance-single:' in out
    assert '     10:' in out


def test_the_notes_block_has_five_fields_before_the_data() -> None:
    out = write_sm((SimfileChart('dance-single', 'Hard', 10, '0000'),), ((0.0, 158.0),))
    block = out.split('#NOTES:')[1]
    assert block.split(';')[0].count(':') == 5
