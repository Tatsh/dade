"""Tests for ``dade rbplus site``."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
import json
import logging

import pytest

from dade.rbplus.commands.site import site

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from _pytest.logging import LogCaptureFixture
    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def _read(path: Path) -> dict[str, Any]:
    return cast('dict[str, Any]', json.loads(path.read_text(encoding='utf-8')))


def _index(output_dir: Path) -> dict[str, Any]:
    return _read(output_dir / 'data' / 'index.json')


def _charts(output_dir: Path, tune_id: int) -> dict[str, Any]:
    return _read(output_dir / 'data' / f'{tune_id}.json')


def test_site_builds_a_site(runner: CliRunner, tune_package: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(site, (str(tune_package), '-o', str(out)))
    assert result.exit_code == 0
    assert '1 tunes' in result.output
    assert (out / 'index.html').is_file()
    assert (out / '.nojekyll').is_file()
    entry = _index(out)['tunes'][0]
    assert entry['title'] == 'Test Tune'
    assert entry['artist'] == 'Test Artist'
    assert entry['titleRomaji'] == 'tesuto'
    assert entry['letter'] == 'T'
    assert entry['row'] == 'タ'
    assert entry['bpm'] == [190, 190]
    assert entry['special'] is None
    assert entry['levels'] == {'basic': 2, 'hard': 7, 'medium': 5}
    assert sorted(_charts(out, entry['id'])) == ['basic', 'hard', 'medium']


def test_site_searches_a_directory_all_the_way_down(runner: CliRunner, make_package: Callable[...,
                                                                                              Path],
                                                    chart_bytes: bytes, tmp_path: Path) -> None:
    (tmp_path / 'deep').mkdir()
    make_package(name='deep/100000109.rb', entries={'note_bas': chart_bytes})
    out = tmp_path / 'out'
    assert runner.invoke(site, (str(tmp_path / 'deep'), '-o', str(out))).exit_code == 0
    assert len(_index(out)['tunes']) == 1


def test_site_reads_a_package_named_twice_once(runner: CliRunner, tune_package: Path,
                                               tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(site, (str(tune_package), str(tune_package.parent), '-o', str(out)))
    assert result.exit_code == 0
    assert len(_index(out)['tunes']) == 1


def test_site_aborts_when_nothing_can_be_read(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'rubbish.rb').write_bytes(b'not a zip')
    result = runner.invoke(site, (str(tmp_path / 'rubbish.rb'), '-o', str(tmp_path / 'out')))
    assert result.exit_code == 1
    assert 'No tune packages could be read.' in result.output


def test_site_steps_over_a_package_that_will_not_open(runner: CliRunner, tune_package: Path,
                                                      tmp_path: Path) -> None:
    (tmp_path / 'rubbish.rb').write_bytes(b'not a zip')
    out = tmp_path / 'out'
    assert runner.invoke(site, (str(tmp_path), '-o', str(out))).exit_code == 0
    assert len(_index(out)['tunes']) == 1


def test_site_leaves_out_a_chart_that_will_not_parse(runner: CliRunner,
                                                     make_package: Callable[..., Path],
                                                     chart_bytes: bytes, tmp_path: Path) -> None:
    package = make_package(entries={'note_bas': chart_bytes, 'note_har': b'rubbish'})
    out = tmp_path / 'out'
    assert runner.invoke(site, (str(package), '-o', str(out))).exit_code == 0
    assert _index(out)['tunes'][0]['levels'] == {'basic': 2}


def test_site_takes_a_tune_identifier_from_the_file_name(runner: CliRunner,
                                                         make_package: Callable[..., Path],
                                                         tune_info: dict[str, object],
                                                         chart_bytes: bytes,
                                                         tmp_path: Path) -> None:
    del tune_info['ID']
    package = make_package(name='100000222.rb', entries={'note_bas': chart_bytes}, info=tune_info)
    out = tmp_path / 'out'
    assert runner.invoke(site, (str(package), '-o', str(out))).exit_code == 0
    assert _index(out)['tunes'][0]['id'] == 100000222


def test_site_names_a_tune_after_its_file_when_the_metadata_does_not(runner: CliRunner,
                                                                     make_package: Callable[...,
                                                                                            Path],
                                                                     tune_info: dict[str, object],
                                                                     chart_bytes: bytes,
                                                                     tmp_path: Path) -> None:
    del tune_info['ID']
    tune_info['MusicName'] = ''
    package = make_package(name='mystery.rb', entries={'note_bas': chart_bytes}, info=tune_info)
    out = tmp_path / 'out'
    assert runner.invoke(site, (str(package), '-o', str(out))).exit_code == 0
    entry = _index(out)['tunes'][0]
    assert entry['title'] == 'mystery'
    assert entry['id'] == 0


def test_site_files_an_extend_note_under_the_tune_it_extends(runner: CliRunner, tune_package: Path,
                                                             make_package: Callable[..., Path],
                                                             tune_info: dict[str, object],
                                                             chart_bytes: bytes,
                                                             tmp_path: Path) -> None:
    tune_info['Basic'] = 11
    tune_info['ID'] = 100050109
    make_package(name='100050109.rb', entries={'note_bas': chart_bytes}, info=tune_info)
    out = tmp_path / 'out'
    result = runner.invoke(site, (str(tmp_path), '-o', str(out)))
    assert result.exit_code == 0
    assert '1 with a SPECIAL chart' in result.output
    entry = _index(out)['tunes'][0]
    assert len(_index(out)['tunes']) == 1
    assert entry['special'] == 100050109
    assert entry['levels']['special'] == 11
    assert 'special' in _charts(out, entry['id'])


def test_site_lists_an_extend_note_with_no_tune_on_its_own(runner: CliRunner,
                                                           make_package: Callable[..., Path],
                                                           tune_info: dict[str, object],
                                                           chart_bytes: bytes,
                                                           tmp_path: Path) -> None:
    tune_info['ID'] = 100050109
    make_package(name='100050109.rb', entries={'note_bas': chart_bytes}, info=tune_info)
    out = tmp_path / 'out'
    assert runner.invoke(site, (str(tmp_path), '-o', str(out))).exit_code == 0
    entry = _index(out)['tunes'][0]
    assert entry['id'] == 100050109
    assert entry['special'] is None


def test_site_writes_the_base_into_the_page(runner: CliRunner, tune_package: Path,
                                            tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(site, (str(tune_package), '--base', '/rbpcharts', '-o', str(out)))
    assert result.exit_code == 0
    page = (out / 'index.html').read_text(encoding='utf-8')
    assert '<base href="/rbpcharts/">' in page
    assert 'data-base="/rbpcharts/"' in page
    assert (out / '404.html').read_text(encoding='utf-8') == page


@pytest.mark.parametrize('base', ['rbpcharts', 'rbpcharts/'])
def test_site_refuses_a_base_that_does_not_begin_with_a_slash(runner: CliRunner, tune_package: Path,
                                                              base: str, tmp_path: Path) -> None:
    result = runner.invoke(site, (str(tune_package), '--base', base, '-o', str(tmp_path / 'out')))
    assert result.exit_code == 2
    assert 'must begin with a slash' in result.output


def test_site_refuses_a_page_it_cannot_tell_where_it_is(runner: CliRunner, tune_package: Path,
                                                        tmp_path: Path,
                                                        mocker: MockerFixture) -> None:
    built = tmp_path / 'built'
    (built / 'site').mkdir(parents=True)
    (built / 'site' / 'index.html').write_text('nothing to write into', encoding='utf-8')
    mocker.patch('importlib.resources.files', return_value=built)
    result = runner.invoke(site, (str(tune_package), '--base', '/x', '-o', str(tmp_path / 'out')))
    assert result.exit_code == 1
    assert 'cannot be told where it is' in result.output


def test_site_warns_when_the_bundle_has_not_been_built(runner: CliRunner, tune_package: Path,
                                                       tmp_path: Path, caplog: LogCaptureFixture,
                                                       mocker: MockerFixture) -> None:
    built = tmp_path / 'built'
    (built / 'site' / 'nested').mkdir(parents=True)
    mocker.patch('importlib.resources.files', return_value=built)
    out = tmp_path / 'out'
    with caplog.at_level(logging.WARNING, logger='dade.rbplus.commands.site'):
        assert runner.invoke(site, (str(tune_package), '-o', str(out))).exit_code == 0
    assert not (out / 'index.html').exists()
    assert 'yarn build' in caplog.text


def test_site_reports_an_output_it_cannot_write(runner: CliRunner, tune_package: Path,
                                                tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('pathlib.Path.mkdir', side_effect=OSError('Permission denied'))
    result = runner.invoke(site, (str(tune_package), '-o', str(tmp_path / 'out')))
    assert result.exit_code == 1
    assert 'Permission denied' in result.output
