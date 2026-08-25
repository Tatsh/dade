"""Tests for :py:mod:`dade.rhythmin.sheet`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct
import zipfile

from PIL import Image
import pytest

from dade.rhythmin.bfcodec import encipher
from dade.rhythmin.sheet import (
    arcade_strip,
    arcade_to_json,
    detect_format,
    parse_arcade,
    parse_standard,
    read_sheet,
    render_strip_image,
    standard_strip,
    standard_to_json,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _record(tick: int,
            end: int,
            record_type: int,
            value: int,
            positions: Sequence[int] = (0, 0, 0, 0, 0, 0)) -> bytes:
    return (struct.pack('<II', tick, end) + bytes([record_type, 0, 0, 0]) +
            struct.pack('<H', value) + bytes(positions))


def test_read_sheet_standard(orb_package: Path) -> None:
    sheet = read_sheet(orb_package, 'n')
    assert sheet.entry == 'sheet_n'
    assert sheet.info is not None
    assert sheet.info['MusicName'] == 'テスト'
    assert detect_format(sheet.payload, orb_package.suffix) == 'standard'


def test_read_sheet_arcade(acv_package: Path) -> None:
    sheet = read_sheet(acv_package, 'ex')
    assert sheet.info is not None
    assert sheet.info['GenreName'] == 'ビタミンポップ'
    assert detect_format(sheet.payload, acv_package.suffix) == 'arcade'


def test_read_sheet_rejects_an_absent_difficulty(orb_package: Path) -> None:
    with pytest.raises(KeyError, match=r"No 'sheet_h' in"):
        read_sheet(orb_package, 'h')


def test_detect_format_rejects_rubbish() -> None:
    with pytest.raises(ValueError, match='Unrecognised chart payload'):
        detect_format(b'\1\2\3')


def test_parse_standard(standard_chart_bytes: bytes) -> None:
    chart = parse_standard(standard_chart_bytes)
    assert chart.hi_speed == pytest.approx(1.5)
    assert [record.type_name
            for record in chart.records] == ['tempo', 'mark', 'note', 'note', 'bar', 'bar', 'end']
    assert chart.records[2].kind == 1
    assert chart.records[2].is_hold is False
    assert chart.records[3].is_hold is True
    assert chart.records[3].positions == (10, 20, 30, 40, 99, 60)


def test_parse_arcade(arcade_chart_bytes: bytes) -> None:
    units = parse_arcade(arcade_chart_bytes)
    assert len(units) == 11
    assert units[0].pad == ord('E')
    assert units[0].type_name == 'tempo'
    assert units[0].value == 120
    assert [unit.lane for unit in units if unit.type_name == 'tap'] == [0, 4, 8, 8]
    # Only the value's low nibble is the lane; the bits above it are carried but unused here.
    assert units[6].value == 0x0018
    assert units[6].lane == 8


def test_standard_to_json(standard_chart_bytes: bytes) -> None:
    rendered = standard_to_json(parse_standard(standard_chart_bytes))
    assert rendered['format'] == 'standard'
    assert rendered['summary']['notes'] == 2
    assert rendered['summary']['holds'] == 1
    assert rendered['summary']['bars'] == 2
    assert rendered['summary']['bpmRange'] == [240, 240]
    assert rendered['summary']['endTick'] == 3000
    assert rendered['records'][3]['hold'] is True


def test_standard_to_json_summary_only(standard_chart_bytes: bytes) -> None:
    assert 'records' not in standard_to_json(parse_standard(standard_chart_bytes),
                                             summary_only=True)


def test_arcade_to_json(arcade_chart_bytes: bytes) -> None:
    rendered = arcade_to_json(parse_arcade(arcade_chart_bytes))
    assert rendered['format'] == 'arcade'
    assert rendered['summary']['taps'] == 4
    assert rendered['summary']['measures'] == 2
    assert rendered['summary']['beats'] == 2
    assert rendered['summary']['tapsPerLane'] == {0: 1, 4: 1, 8: 2}
    assert rendered['units'][0]['pad'] == ord('E')


def test_arcade_to_json_summary_only(arcade_chart_bytes: bytes) -> None:
    assert 'units' not in arcade_to_json(parse_arcade(arcade_chart_bytes), summary_only=True)


def test_arcade_strip(arcade_chart_bytes: bytes) -> None:
    strip = arcade_strip(parse_arcade(arcade_chart_bytes))
    assert strip.lane_count == 9
    assert strip.measure_ticks == (0, 1000)
    assert strip.beat_ticks == (0, 500)
    assert strip.tempos == ((0, 120),)
    assert len(strip.notes) == 4


def test_arcade_strip_needs_measures() -> None:
    with pytest.raises(ValueError, match='no measure events'):
        arcade_strip(())


def test_standard_strip_buckets_by_target_x(standard_chart_bytes: bytes) -> None:
    strip = standard_strip(parse_standard(standard_chart_bytes), 7)
    assert strip.lane_count == 7
    # Target x percentages of 50 and 99 bucket into 7 columns as 3 and 6.
    assert [note.lane for note in strip.notes] == [3, 6]
    assert strip.measure_ticks == (0, 1000)


def test_standard_strip_synthesises_measures_without_bars(standard_chart_bytes: bytes) -> None:
    chart = parse_standard(standard_chart_bytes)
    without_bars = chart._replace(records=tuple(r for r in chart.records if r.type_name != 'bar'))
    strip = standard_strip(without_bars)
    # 240 BPM means a 4/4 measure lasts 1000 ticks, so the 3000-tick chart gets three lines.
    assert strip.measure_ticks == (0, 1000, 2000)


def test_standard_strip_rejects_a_bad_lane_count(standard_chart_bytes: bytes) -> None:
    with pytest.raises(ValueError, match='must be positive'):
        standard_strip(parse_standard(standard_chart_bytes), 0)


def test_standard_strip_needs_a_grid(standard_chart_bytes: bytes) -> None:
    chart = parse_standard(standard_chart_bytes)
    bare = chart._replace(records=tuple(
        r for r in chart.records if r.type_name not in {'bar', 'tempo'}))
    with pytest.raises(ValueError, match='no bar records and no usable tempo map'):
        standard_strip(bare)


@pytest.mark.parametrize('top_down', [False, True])
def test_render_strip_image_arcade(arcade_chart_bytes: bytes, tmp_path: Path, *,
                                   top_down: bool) -> None:
    path = tmp_path / 'chart.png'
    width, height = render_strip_image(arcade_strip(parse_arcade(arcade_chart_bytes)),
                                       path,
                                       source='test',
                                       title='WORLD COLOR',
                                       artist='ビタミンポップ',
                                       level=38,
                                       top_down=top_down)
    with Image.open(path) as image:
        assert image.size == (width, height)


def test_render_strip_image_draws_holds(standard_chart_bytes: bytes, tmp_path: Path) -> None:
    path = tmp_path / 'chart.png'
    render_strip_image(standard_strip(parse_standard(standard_chart_bytes)),
                       path,
                       source='test',
                       top_down=True)
    assert path.is_file()


def test_render_strip_image_needs_a_grid(arcade_chart_bytes: bytes, tmp_path: Path) -> None:
    strip = arcade_strip(parse_arcade(arcade_chart_bytes))._replace(measure_ticks=())
    with pytest.raises(ValueError, match='no measure grid'):
        render_strip_image(strip, tmp_path / 'chart.png', source='test')


def test_render_strip_image_rejects_missing_sprites(arcade_chart_bytes: bytes,
                                                    tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='Cannot load the button sprite'):
        render_strip_image(arcade_strip(parse_arcade(arcade_chart_bytes)),
                           tmp_path / 'chart.png',
                           buttons_dir=tmp_path,
                           source='test')


def test_detect_format_uses_the_extension_to_break_a_tie() -> None:
    # A 24-byte payload with the arcade magic satisfies both format checks.
    payload = bytes(4) + b'E' + bytes(19)
    assert detect_format(payload, '.acv') == 'arcade'
    assert detect_format(payload, '.orb') == 'standard'


def test_read_sheet_without_info(tmp_path: Path, standard_chart_bytes: bytes) -> None:
    path = tmp_path / 'no_info.orb'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('sheet_n', encipher(standard_chart_bytes))
    assert read_sheet(path, 'n').info is None


def test_read_sheet_with_unreadable_info(tmp_path: Path, standard_chart_bytes: bytes) -> None:
    path = tmp_path / 'bad_info.orb'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('sheet_n', encipher(standard_chart_bytes))
        archive.writestr('info', encipher(b'not a plist'))
    assert read_sheet(path, 'n').info is None


def test_standard_summary_without_tempo_has_no_bpm_range() -> None:
    chart_bytes = struct.pack('<f', 1.0) + _record(0, 0, 4, 0) + _record(1000, 1000, 3, 0)
    assert standard_to_json(parse_standard(chart_bytes))['summary']['bpmRange'] is None


def test_standard_strip_skips_a_zero_bpm_tempo() -> None:
    chart_bytes = (struct.pack('<f', 1.0) + _record(0, 0, 2, 240) + _record(500, 0, 2, 0) +
                   _record(0, 0, 0, 1, (0, 0, 0, 50, 0, 0)) + _record(2000, 2000, 3, 0))
    assert standard_strip(parse_standard(chart_bytes)).measure_ticks


def test_standard_strip_ignores_an_unknown_record() -> None:
    chart_bytes = (struct.pack('<f', 1.0) + _record(0, 0, 2, 240) + _record(0, 0, 5, 0) +
                   _record(0, 0, 4, 0) + _record(1000, 1000, 4, 0))
    assert standard_strip(parse_standard(chart_bytes)).measure_ticks == (0, 1000)


def test_render_strip_image_with_button_sprites(arcade_chart_bytes: bytes, tmp_path: Path) -> None:
    buttons = tmp_path / 'buttons'
    buttons.mkdir()
    for number in range(1, 6):
        Image.new('RGBA', (20, 20),
                  (255, 0, 0, 255)).save(buttons / f'login_popn{number:02d}@2x.png')
    path = tmp_path / 'chart.png'
    render_strip_image(arcade_strip(parse_arcade(arcade_chart_bytes)),
                       path,
                       buttons_dir=buttons,
                       source='test')
    assert path.is_file()


def test_render_places_a_tick_before_the_first_measure(arcade_chart_bytes: bytes,
                                                       tmp_path: Path) -> None:
    strip = arcade_strip(parse_arcade(arcade_chart_bytes))._replace(measure_ticks=(500, 1000))
    path = tmp_path / 'chart.png'
    render_strip_image(strip, path, source='test')
    assert path.is_file()


def test_render_skips_notes_outside_the_lane_count(arcade_chart_bytes: bytes,
                                                   tmp_path: Path) -> None:
    strip = arcade_strip(parse_arcade(arcade_chart_bytes))._replace(lane_count=1)
    path = tmp_path / 'chart.png'
    render_strip_image(strip, path, source='test')
    assert path.is_file()


def test_render_reports_no_bpm_without_tempos(arcade_chart_bytes: bytes, tmp_path: Path) -> None:
    strip = arcade_strip(parse_arcade(arcade_chart_bytes))._replace(tempos=())
    path = tmp_path / 'chart.png'
    render_strip_image(strip, path, source='test', title='No Tempo')
    assert path.is_file()


def test_render_reports_a_bpm_range(arcade_chart_bytes: bytes, tmp_path: Path) -> None:
    strip = arcade_strip(parse_arcade(arcade_chart_bytes))._replace(tempos=((0, 120), (500, 240)))
    path = tmp_path / 'chart.png'
    render_strip_image(strip, path, source='test', title='Range')
    assert path.is_file()
