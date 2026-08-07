from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from destin.frequency.main import main

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_main_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ('--help',))
    assert result.exit_code == 0
    assert '--output-dir' in result.output
    assert '--jobs' in result.output


def test_main_requires_arguments(runner: CliRunner) -> None:
    result = runner.invoke(main)
    assert result.exit_code == 2


def test_main_runs_game(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(b'ARK\x00' + bytes(12))  # ARK\0 magic: FreQuency layout.
    run_game = mocker.patch('destin.harmonix.unpacker.run_game',
                            return_value={'ARK/ROOT.ARK': 'ok'})
    out = tmp_path / 'out'
    result = runner.invoke(main, (str(tmp_path), '-o', str(out), '--jobs', '3'))
    assert result.exit_code == 0
    assert 'ARK/ROOT.ARK: ok' in result.output
    assert run_game.call_args.args == (tmp_path, out)
    assert run_game.call_args.kwargs['jobs'] == 3
    assert run_game.call_args.kwargs['layout'] == 'frequency'
    assert run_game.call_args.kwargs['on_status'] is not None


def test_main_default_output_dir(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(b'ARK\x00' + bytes(12))
    run_game = mocker.patch('destin.harmonix.unpacker.run_game',
                            return_value={'ARK/ROOT.ARK': 'ok'})
    result = runner.invoke(main, (str(tmp_path),))
    assert result.exit_code == 0
    assert run_game.call_args.args[1] == Path()
    assert run_game.call_args.kwargs['jobs'] == 0


def test_main_debug_skips_spinner(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(b'ARK\x00' + bytes(12))
    run_game = mocker.patch('destin.harmonix.unpacker.run_game',
                            return_value={'ARK/ROOT.ARK': 'ok'})
    console = mocker.patch('destin.frequency.main.console')
    result = runner.invoke(main, (str(tmp_path), '--debug'))
    assert result.exit_code == 0
    console.status.assert_not_called()
    assert run_game.call_args.kwargs['on_status'] is None


def test_main_uses_spinner(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(b'ARK\x00' + bytes(12))
    mocker.patch('destin.harmonix.unpacker.run_game', return_value={'ARK/ROOT.ARK': 'ok'})
    console = mocker.patch('destin.frequency.main.console')
    result = runner.invoke(main, (str(tmp_path),))
    assert result.exit_code == 0
    console.status.assert_called_once()


def test_main_rejects_negative_jobs(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'ROOT.ARK').write_bytes(b'ARK\x00' + bytes(12))
    result = runner.invoke(main, (str(tmp_path), '--jobs', '-1'))
    assert result.exit_code == 2
