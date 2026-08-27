"""Tests for ``dade.rbplus.reading``."""
from __future__ import annotations

import pytest

from dade.rbplus.reading import gojuon_row, initial, to_romaji


@pytest.mark.parametrize(('reading', 'expected'), [
    ('', ''),
    ('アイウエオ', 'aiueo'),
    ('あいうえお', 'aiueo'),
    ('テスト', 'tesuto'),
    ('ンヲヰヱ', 'noie'),
    ('ガギグゲゴ', 'gagigugego'),
    ('パピプペポ', 'papipupepo'),
    ('ヂヅ', 'jizu'),
    ('ヮヵヶ', 'wakake'),
])
def test_to_romaji_writes_each_kana(reading: str, expected: str) -> None:
    assert to_romaji(reading) == expected


@pytest.mark.parametrize(('reading', 'expected'), [
    ('シャ', 'sha'),
    ('シュ', 'shu'),
    ('ショ', 'sho'),
    ('チョ', 'cho'),
    ('ジャ', 'ja'),
    ('キャ', 'kya'),
    ('ギョ', 'gyo'),
    ('ニュ', 'nyu'),
    ('ヒャ', 'hya'),
    ('ビュ', 'byu'),
    ('ピョ', 'pyo'),
    ('ミャ', 'mya'),
    ('リョ', 'ryo'),
    ('ヴュ', 'vyu'),
])
def test_to_romaji_joins_a_small_y_to_the_kana_before_it(reading: str, expected: str) -> None:
    assert to_romaji(reading) == expected


@pytest.mark.parametrize(('reading', 'expected'), [
    ('ウィ', 'wi'),
    ('クァ', 'kwa'),
    ('シェ', 'she'),
    ('チェ', 'che'),
    ('ツァ', 'tsa'),
    ('ティ', 'ti'),
    ('テュ', 'tyu'),
    ('デュ', 'dyu'),
    ('トゥ', 'tu'),
    ('イェ', 'ye'),
    ('ファ', 'fa'),
    ('フュ', 'fyu'),
    ('ヴォ', 'vo'),
])
def test_to_romaji_writes_a_named_pair_as_one_sound(reading: str, expected: str) -> None:
    assert to_romaji(reading) == expected


def test_to_romaji_writes_an_unnamed_pair_as_two_sounds() -> None:
    assert to_romaji('カァ') == 'kaa'


@pytest.mark.parametrize(('reading', 'expected'), [
    ('カー', 'ka'),
    ('カヽ', 'ka'),
    ('カヾ', 'ka'),
    ('ーカ', 'ka'),
])
def test_to_romaji_drops_the_long_mark(reading: str, expected: str) -> None:
    assert to_romaji(reading) == expected


@pytest.mark.parametrize(('reading', 'expected'), [
    ('ッカ', 'kka'),
    ('ッシャ', 'ssha'),
    ('ハッピー', 'happi'),
    ('ッ', ''),
])
def test_to_romaji_doubles_the_letter_after_a_geminate(reading: str, expected: str) -> None:
    assert to_romaji(reading) == expected


@pytest.mark.parametrize(('reading', 'expected'), [
    ('FLOWER', 'flower'),
    ('Test 123', 'test 123'),
    ('テスト2', 'tesuto2'),
])
def test_to_romaji_carries_anything_that_is_not_kana_through_in_lowercase(
        reading: str, expected: str) -> None:
    assert to_romaji(reading) == expected


@pytest.mark.parametrize(('reading', 'expected'), [
    ('アイ', 'ア'),
    ('カレー', 'カ'),
    ('ガクエン', 'カ'),
    ('サヨナラ', 'サ'),
    ('シャイン', 'サ'),
    ('ジユウ', 'サ'),
    ('タイヨウ', 'タ'),
    ('チカラ', 'タ'),
    ('ツキ', 'タ'),
    ('デンワ', 'タ'),
    ('ナミダ', 'ナ'),
    ('ハナ', 'ハ'),
    ('フユ', 'ハ'),
    ('バラ', 'ハ'),
    ('パレード', 'ハ'),
    ('ヴォイス', 'ハ'),
    ('ミライ', 'マ'),
    ('ユメ', 'ヤ'),
    ('リズム', 'ラ'),
    ('ワタシ', 'ワ'),
    ('ヲンナ', 'ア'),
    ('ゆめ', 'ヤ'),
])
def test_gojuon_row_files_a_reading_under_its_first_sound(reading: str, expected: str) -> None:
    assert gojuon_row(reading) == expected


@pytest.mark.parametrize(('reading', 'expected'), [
    ('ーアイ', 'ア'),
    ('ッカ', 'カ'),
])
def test_gojuon_row_steps_over_a_mark_that_heads_nothing(reading: str, expected: str) -> None:
    assert gojuon_row(reading) == expected


@pytest.mark.parametrize('readings', [
    ('FLOWER',),
    ('2 many DJs',),
    ('',),
    ('ー',),
    ('FLOWER', '1234'),
])
def test_gojuon_row_files_a_reading_that_begins_with_no_kana_nowhere(
        readings: tuple[str, ...]) -> None:
    assert gojuon_row(*readings) == '?'


def test_gojuon_row_falls_through_to_the_next_reading() -> None:
    assert gojuon_row('', 'FLOWER', 'ハナ') == 'ハ'


@pytest.mark.parametrize(('names', 'expected'), [
    (('Test',), 'T'),
    (('test',), 'T'),
    (('  Test',), 'T'),
    (('123',), '#'),
    (('#1',), '?'),
    (('テスト',), '?'),
    (('テスト', 'tesuto'), 'T'),
    (('', 'Test'), 'T'),
    (('   ', 'Test'), 'T'),
    ((), '?'),
])
def test_initial_files_a_name_under_its_first_letter(names: tuple[str, ...], expected: str) -> None:
    assert initial(*names) == expected
