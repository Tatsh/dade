from __future__ import annotations

from typing import TYPE_CHECKING

from dade.incoming.dispatch import ConversionSummary
from dade.incoming.main import main
from dade.incoming.sources import PreparedSource, SourceError

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_main_success(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    source = tmp_path / 'in'
    source.mkdir()
    mocker.patch('dade.incoming.main.prepare_source', return_value=PreparedSource(source, ()))
    mocker.patch('dade.incoming.main.run_conversions',
                 new_callable=mocker.AsyncMock,
                 return_value=ConversionSummary(2, 3, 0, 0, 0))
    result = runner.invoke(main, ['-o', str(tmp_path / 'out'), str(source)])
    assert result.exit_code == 0
    assert 'Converted 2 files' in result.output


def test_main_jobs_option(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    source = tmp_path / 'in'
    source.mkdir()
    mocker.patch('dade.incoming.main.prepare_source', return_value=PreparedSource(source, ()))
    run_conversions = mocker.patch('dade.incoming.main.run_conversions',
                                   new_callable=mocker.AsyncMock,
                                   return_value=ConversionSummary(1, 1, 0, 0, 0))
    result = runner.invoke(main, ['-j', '3', '-o', str(tmp_path / 'out'), str(source)])
    assert result.exit_code == 0
    assert run_conversions.await_args.kwargs['jobs'] == 3


def test_main_loose_files(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    asset = tmp_path / 't.raw'
    asset.write_text('x')
    mocker.patch('dade.incoming.main.prepare_source', return_value=PreparedSource(None, (asset,)))
    run_conversions = mocker.patch('dade.incoming.main.run_conversions',
                                   new_callable=mocker.AsyncMock,
                                   return_value=ConversionSummary(1, 1, 0, 0, 0))
    result = runner.invoke(main, ['-o', str(tmp_path / 'out'), str(asset)])
    assert result.exit_code == 0
    run_conversions.assert_awaited_once()


def test_main_source_error(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    source = tmp_path / 'in'
    source.mkdir()
    mocker.patch('dade.incoming.main.prepare_source', side_effect=SourceError('bad source'))
    result = runner.invoke(main, ['-o', str(tmp_path / 'out'), str(source)])
    assert result.exit_code == 1


def test_main_reports_failures(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    source = tmp_path / 'in'
    source.mkdir()
    mocker.patch('dade.incoming.main.prepare_source', return_value=PreparedSource(source, ()))
    mocker.patch('dade.incoming.main.run_conversions',
                 new_callable=mocker.AsyncMock,
                 return_value=ConversionSummary(0, 0, 0, 0, 1))
    result = runner.invoke(main, ['-o', str(tmp_path / 'out'), str(source)])
    assert result.exit_code == 1
