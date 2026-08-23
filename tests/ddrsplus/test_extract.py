"""Tests for :py:mod:`destin.ddrsplus.extract`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

from PIL import Image
import pytest

from destin.ddrsplus.extract import extract_gen
from destin.ddrsplus.pvr import BANNER_SIZE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_every_section_is_written_out(make_gen: Callable[..., bytes], tmp_path: Path) -> None:
    extract_gen(make_gen(), 'song', tmp_path)
    assert {path.name
            for path in tmp_path.iterdir()} >= {
                'song.0.mp3', 'song.1.mp3', 'song.2.pvr', 'song.3.ssq', 'song.4.ssq', 'song.5.info',
                'song.6.tbl', 'song.7.tbl'
            }


def test_the_raw_sections_are_kept_beside_the_conversions(make_gen: Callable[..., bytes],
                                                          tmp_path: Path) -> None:
    extract_gen(make_gen(), 'song', tmp_path)
    assert (tmp_path / 'song.2.pvr').is_file()
    assert (tmp_path / 'song.2.png').is_file()


def test_the_banner_is_cropped_by_default(make_gen: Callable[..., bytes], tmp_path: Path) -> None:
    extract_gen(make_gen(), 'song', tmp_path)
    with Image.open(tmp_path / 'song.2.png') as image:
        assert image.size == BANNER_SIZE


def test_cropping_can_be_turned_off(make_gen: Callable[..., bytes], tmp_path: Path) -> None:
    extract_gen(make_gen(), 'song', tmp_path, crop_banner=False)
    with Image.open(tmp_path / 'song.2.png') as image:
        assert image.size == (256, 64)


def test_the_record_sections_also_become_json(make_gen: Callable[..., bytes],
                                              tmp_path: Path) -> None:
    extract_gen(make_gen(), 'song', tmp_path)
    assert json.loads((tmp_path / 'song.5.json').read_text())['musicId'] == 259
    assert json.loads((tmp_path / 'song.6.json').read_text())['minBpm'] == 158
    assert (tmp_path / 'song.7.json').is_file()


def test_each_chart_section_becomes_a_simfile(make_gen: Callable[..., bytes],
                                              tmp_path: Path) -> None:
    extract_gen(make_gen(), 'song', tmp_path)
    assert (tmp_path / 'song.sm').is_file()
    assert (tmp_path / 'song.shake.sm').is_file()


def test_the_simfile_points_at_the_extracted_media(make_gen: Callable[..., bytes],
                                                   tmp_path: Path) -> None:
    extract_gen(make_gen(), 'song', tmp_path)
    text = (tmp_path / 'song.sm').read_text()
    assert '#MUSIC:song.0.mp3;' in text
    assert '#BANNER:song.2.png;' in text


def test_the_standard_charts_get_their_recorded_meters(make_gen: Callable[..., bytes],
                                                       tmp_path: Path) -> None:
    # The sample holds a beginner and a basic chart, rated 2 and 5.
    extract_gen(make_gen(), 'song', tmp_path)
    text = (tmp_path / 'song.sm').read_text()
    assert '     2:' in text
    assert '     5:' in text


def test_a_given_gap_is_used_verbatim(make_gen: Callable[..., bytes], tmp_path: Path) -> None:
    result = extract_gen(make_gen(), 'song', tmp_path, gap=5.339)
    assert result.gap == pytest.approx(5.339)
    assert '#OFFSET:-5.339;' in (tmp_path / 'song.sm').read_text()


def test_without_ffmpeg_the_gap_falls_back_to_zero(make_gen: Callable[..., bytes],
                                                   tmp_path: Path) -> None:
    assert extract_gen(make_gen(), 'song', tmp_path).gap == pytest.approx(0.0)


def test_the_output_directory_is_created(make_gen: Callable[..., bytes], tmp_path: Path) -> None:
    target = tmp_path / 'nested' / 'deeper'
    extract_gen(make_gen(), 'song', target)
    assert target.is_dir()


def test_the_result_lists_every_file_written(make_gen: Callable[..., bytes],
                                             tmp_path: Path) -> None:
    result = extract_gen(make_gen(), 'song', tmp_path)
    assert set(result.paths) == set(tmp_path.iterdir())


def test_the_gap_is_measured_when_ffmpeg_is_supplied(make_gen: Callable[..., bytes], tmp_path: Path,
                                                     mocker: MockerFixture) -> None:
    mocker.patch('destin.ddrsplus.extract.estimate_gap', return_value=1.234)
    result = extract_gen(make_gen(), 'song', tmp_path, ffmpeg=tmp_path / 'ffmpeg')
    assert result.gap == pytest.approx(1.234)
    assert '#OFFSET:-1.234;' in (tmp_path / 'song.sm').read_text()


def test_missing_optional_sections_are_skipped(make_gen: Callable[..., bytes],
                                               tmp_path: Path) -> None:
    extract_gen(make_gen(sections={2: b'', 7: b''}), 'song', tmp_path)
    assert not (tmp_path / 'song.2.png').exists()
    assert not (tmp_path / 'song.7.json').exists()
    # The banner reference in the simfile falls back to empty.
    assert '#BANNER:;' in (tmp_path / 'song.sm').read_text()


def test_a_chart_section_with_no_charts_is_skipped(make_gen: Callable[..., bytes],
                                                   make_ssq: Callable[..., bytes],
                                                   tmp_path: Path) -> None:
    extract_gen(make_gen(sections={3: make_ssq(parameters=())}), 'song', tmp_path)
    assert not (tmp_path / 'song.sm').exists()
    assert (tmp_path / 'song.shake.sm').is_file()
