"""Tests for :py:mod:`destin.rhythmin.render`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.rhythmin.render import japanese_font_path, load_font

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_japanese_font_path_returns_none_without_fc_match(clear_font_caches: None,
                                                          mocker: MockerFixture) -> None:
    mocker.patch('destin.rhythmin.render.which', return_value=None)
    assert japanese_font_path() is None


def test_japanese_font_path_reports_the_matched_font(clear_font_caches: None,
                                                     mocker: MockerFixture) -> None:
    mocker.patch('destin.rhythmin.render.which', return_value='/usr/bin/fc-match')
    mocker.patch('destin.rhythmin.render.sp.run',
                 return_value=mocker.Mock(stdout='/fonts/japanese.otf\n'))
    assert japanese_font_path() == '/fonts/japanese.otf'


def test_japanese_font_path_returns_none_when_fc_match_cannot_run(clear_font_caches: None,
                                                                  mocker: MockerFixture) -> None:
    mocker.patch('destin.rhythmin.render.which', return_value='/usr/bin/fc-match')
    mocker.patch('destin.rhythmin.render.sp.run', side_effect=OSError)
    assert japanese_font_path() is None


def test_load_font_uses_the_built_in_font_without_a_match(clear_font_caches: None,
                                                          mocker: MockerFixture) -> None:
    mocker.patch('destin.rhythmin.render.japanese_font_path', return_value=None)
    assert load_font(12) is not None


def test_load_font_loads_the_matched_font(clear_font_caches: None, mocker: MockerFixture) -> None:
    mocker.patch('destin.rhythmin.render.japanese_font_path', return_value='/fonts/x.otf')
    sentinel = object()
    truetype = mocker.patch('destin.rhythmin.render.ImageFont.truetype', return_value=sentinel)
    assert load_font(13) is sentinel
    truetype.assert_called_once_with('/fonts/x.otf', 13)


def test_load_font_falls_back_when_the_matched_font_will_not_load(clear_font_caches: None,
                                                                  mocker: MockerFixture) -> None:
    mocker.patch('destin.rhythmin.render.japanese_font_path', return_value='/fonts/x.otf')
    mocker.patch('destin.rhythmin.render.ImageFont.truetype', side_effect=OSError)
    fallback = object()
    mocker.patch('destin.rhythmin.render.ImageFont.load_default', return_value=fallback)
    assert load_font(14) is fallback
