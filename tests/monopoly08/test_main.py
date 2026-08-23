from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.monopoly08.main import main
from destin.monopoly08.pipeline import StepStats

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture

_STATS = {'archives': StepStats(2, 0), 'packs': StepStats(5, 1)}


def test_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    run = mocker.patch('destin.monopoly08.main.run', return_value=_STATS)
    result = runner.invoke(main, [str(tmp_path)])
    assert result.exit_code == 0
    assert result.output == 'archives   2 ok, 0 fail\npacks      5 ok, 1 fail\n'
    run.assert_called_once_with(tmp_path, no_movies=False, workers=None)


@pytest.mark.parametrize(('args', 'no_movies', 'workers'), [(['--no-movies'], True, None),
                                                            (['-j', '4'], False, 4),
                                                            (['--workers', '8'], False, 8),
                                                            (['-d'], False, None),
                                                            (['--debug'], False, None)])
def test_main_options(*, args: list[str], mocker: MockerFixture, no_movies: bool, runner: CliRunner,
                      tmp_path: Path, workers: int | None) -> None:
    run = mocker.patch('destin.monopoly08.main.run', return_value={})
    result = runner.invoke(main, [str(tmp_path), *args])
    assert result.exit_code == 0
    run.assert_called_once_with(tmp_path, no_movies=no_movies, workers=workers)


def test_main_rejects_a_missing_root(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, [str(tmp_path / 'nope')])
    assert result.exit_code == 2
    assert 'does not exist' in result.output


def test_main_rejects_a_file(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'disc.iso'
    source.write_bytes(b'')
    result = runner.invoke(main, [str(source)])
    assert result.exit_code == 2
    assert 'is a file' in result.output


@pytest.mark.parametrize('flag', ['-h', '--help'])
def test_main_help(flag: str, runner: CliRunner) -> None:
    result = runner.invoke(main, [flag])
    assert result.exit_code == 0
    assert 'Unpack and convert an extracted Monopoly 2008 disc ROOT' in result.output
