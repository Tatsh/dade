"""Tests for :py:mod:`dade.rbplus.package`."""
from __future__ import annotations

from typing import TYPE_CHECKING, cast
import zipfile

import pytest

from dade.rbplus.cipher import DECODE_TYPE_COUNT
from dade.rbplus.package import (
    AUDIO_ENTRIES,
    CHART_ENTRIES,
    EntryKind,
    PackageError,
    chart_difficulty,
    chart_level,
    classify_entry,
    infer_difficulty,
    open_package,
    read_chart_file,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture

    from dade.rbplus.typing import TuneInfoDict


@pytest.mark.parametrize(('name', 'expected'), [
    ('info', EntryKind.INFO),
    ('note_bas', EntryKind.CHART),
    ('note_har2', EntryKind.CHART),
    ('bgm', EntryKind.AUDIO),
    ('bgm_h', EntryKind.AUDIO),
    ('pre', EntryKind.AUDIO),
    ('artwork', EntryKind.IMAGE),
    ('title_w2x_h', EntryKind.IMAGE),
    ('something_new', EntryKind.IMAGE),
])
def test_classify_entry(name: str, expected: str) -> None:
    assert classify_entry(name) == expected


def test_every_named_chart_and_audio_entry_classifies() -> None:
    assert all(classify_entry(name) == EntryKind.CHART for name in CHART_ENTRIES)
    assert all(classify_entry(name) == EntryKind.AUDIO for name in AUDIO_ENTRIES)


@pytest.mark.parametrize(('name', 'expected'), [('note_bas', 'basic'), ('note_med', 'medium'),
                                                ('note_har', 'hard'), ('note_bas2', 'basic-light'),
                                                ('artwork', 'artwork')])
def test_chart_difficulty(name: str, expected: str) -> None:
    assert chart_difficulty(name) == expected


@pytest.mark.parametrize(('name', 'expected'), [('note_bas', 2), ('note_med', 5), ('note_har', 7),
                                                ('note_bas2', 2)])
def test_chart_level_reads_the_metadata(name: str, expected: int) -> None:
    info: TuneInfoDict = {'Basic': 2, 'Medium': 5, 'Hard': 7}
    assert chart_level(info, name) == expected


@pytest.mark.parametrize('name', ['artwork', 'bgm', 'info', 'something_new'])
def test_chart_level_is_none_for_an_entry_with_no_level(name: str) -> None:
    assert chart_level({'Basic': 2}, name) is None


def test_chart_level_is_none_when_the_metadata_omits_it() -> None:
    assert chart_level({}, 'note_bas') is None


def test_chart_level_is_none_when_the_metadata_holds_the_wrong_type() -> None:
    assert chart_level(cast('TuneInfoDict', {'Basic': 'two'}), 'note_bas') is None


@pytest.mark.parametrize('decode_type', [0, 1])
def test_open_package_finds_the_decode_type(make_package: Callable[..., Path],
                                            decode_type: int) -> None:
    with open_package(make_package(decode_type=decode_type)) as package:
        assert package.decode_type == decode_type
        assert package.info()['ID'] == 100000109


def test_the_package_reports_its_path(make_package: Callable[..., Path]) -> None:
    path = make_package()
    with open_package(path) as package:
        assert package.path == path


def test_reading_an_entry_deciphers_it(make_package: Callable[..., Path]) -> None:
    with open_package(make_package(entries={'artwork': b'plain bytes'})) as package:
        assert package.read('artwork') == b'plain bytes'


def test_names_lists_every_entry(make_package: Callable[..., Path]) -> None:
    with open_package(make_package(entries={'artwork': b'x', 'bgm': b'y'})) as package:
        assert set(package.names) == {'info', 'artwork', 'bgm'}


def test_reading_an_absent_entry_raises(make_package: Callable[..., Path]) -> None:
    with open_package(make_package()) as package, pytest.raises(KeyError):
        package.read('nothing')


def test_charts_yields_them_in_difficulty_order(tune_package: Path) -> None:
    with open_package(tune_package) as package:
        assert [name for name, _ in package.charts()] == ['note_bas', 'note_med', 'note_har']


def test_charts_skips_what_the_package_lacks(make_package: Callable[..., Path],
                                             chart_bytes: bytes) -> None:
    with open_package(make_package(entries={'note_med': chart_bytes})) as package:
        assert [name for name, _ in package.charts()] == ['note_med']


def test_closing_twice_is_harmless(make_package: Callable[..., Path]) -> None:
    package = open_package(make_package())
    package.close()
    package.close()


def test_a_file_that_is_not_a_zip_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'broken.rb'
    path.write_bytes(b'not a zip at all')
    with pytest.raises(PackageError, match='not a ZIP archive'):
        open_package(path)


def test_a_package_without_info_is_rejected(make_package: Callable[..., Path]) -> None:
    with pytest.raises(PackageError, match='holds no info entry'):
        open_package(make_package(omit_info=True))


def test_a_package_under_no_known_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'foreign.rb'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('info', bytes(64))
    with pytest.raises(PackageError, match='deciphers under no known key'):
        open_package(path)


def test_info_reports_a_metadata_entry_that_will_not_parse(make_package: Callable[..., Path],
                                                           mocker: MockerFixture) -> None:
    path = make_package()
    with open_package(path) as package:
        mocker.patch.object(package, 'read', return_value=b'not a property list')
        with pytest.raises(PackageError, match='no readable info entry'):
            package.info()


def test_a_deciphered_chart_file_is_read_as_it_stands(make_chart_file: Callable[..., Path],
                                                      chart_bytes: bytes) -> None:
    assert read_chart_file(make_chart_file(decode_type=None)) == chart_bytes


@pytest.mark.parametrize('decode_type', range(DECODE_TYPE_COUNT))
def test_an_enciphered_chart_file_is_read_under_either_key(make_chart_file: Callable[..., Path],
                                                           chart_bytes: bytes,
                                                           decode_type: int) -> None:
    assert read_chart_file(make_chart_file(decode_type=decode_type)) == chart_bytes


def test_a_chart_file_under_another_key_is_read_with_it(make_chart_file: Callable[..., Path],
                                                        chart_bytes: bytes) -> None:
    key = bytes(range(16))
    assert read_chart_file(make_chart_file(key=key), key=key) == chart_bytes


def test_a_chart_file_under_another_iv_is_read_with_it(make_chart_file: Callable[..., Path],
                                                       chart_bytes: bytes) -> None:
    key, iv = bytes(range(16)), bytes(range(8))
    assert read_chart_file(make_chart_file(iv=iv, key=key), iv=iv, key=key) == chart_bytes


def test_a_chart_file_under_no_known_key_reports_so(make_chart_file: Callable[..., Path]) -> None:
    with pytest.raises(PackageError, match='--key'):
        read_chart_file(make_chart_file(key=bytes(range(16))))


def test_a_chart_file_under_the_wrong_key_reports_so(make_chart_file: Callable[..., Path]) -> None:
    with pytest.raises(PackageError, match='does not decipher'):
        read_chart_file(make_chart_file(key=bytes(range(16))), key=bytes(range(1, 17)))


def test_a_chart_file_with_a_short_iv_reports_so(make_chart_file: Callable[..., Path]) -> None:
    with pytest.raises(PackageError, match='initialisation vector'):
        read_chart_file(make_chart_file(), iv=b'short', key=bytes(range(16)))


@pytest.mark.parametrize(('name', 'expected'), [('note_har', 'note_har'), ('har', 'note_har'),
                                                ('note_bas', 'note_bas'), ('MED', 'note_med'),
                                                ('note_har.bin', 'note_har'), ('mystery', None),
                                                ('', None)])
def test_a_chart_file_name_says_which_difficulty(tmp_path: Path, name: str,
                                                 expected: str | None) -> None:
    assert infer_difficulty(tmp_path / name) == expected
