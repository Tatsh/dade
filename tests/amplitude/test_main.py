from __future__ import annotations

from typing import TYPE_CHECKING

from destin.amplitude.main import main

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_main_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ('--help',))
    assert result.exit_code == 0
    assert '--jobs' in result.output


def test_main_requires_arguments(runner: CliRunner) -> None:
    result = runner.invoke(main)
    assert result.exit_code == 2


def test_main_runs_game(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    run_game = mocker.patch('destin.amplitude.main.run_game', return_value={'GEN/MAIN.ARK': 'ok'})
    result = runner.invoke(main, (str(tmp_path), str(tmp_path / 'out'), '--jobs', '3'))
    assert result.exit_code == 0
    assert 'GEN/MAIN.ARK: ok' in result.output
    assert run_game.call_args.kwargs['jobs'] == 3


def test_main_rejects_zero_jobs(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, (str(tmp_path), str(tmp_path / 'out'), '--jobs', '0'))
    assert result.exit_code == 2
