from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from destin.amplitude.main import main

if TYPE_CHECKING:
    from collections.abc import Callable

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
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'MAIN.ARK').write_bytes(bytes(16))  # No ARK\0 magic: the Amplitude layout.
    mocker.patch('destin.harmonix.unpacker.materialize')
    run_game = mocker.patch('destin.harmonix.unpacker.run_game',
                            return_value={'GEN/MAIN.ARK': 'ok'})
    out = tmp_path / 'out'
    result = runner.invoke(main, (str(game), '-o', str(out), '--jobs', '3'))
    assert result.exit_code == 0
    assert 'GEN/MAIN.ARK: ok' in result.output
    assert run_game.call_args.args == (out,)  # Processed in place in the output directory.
    assert run_game.call_args.kwargs['jobs'] == 3
    assert run_game.call_args.kwargs['layout'] == 'amplitude'
    assert run_game.call_args.kwargs['on_status'] is not None


def test_main_accepts_iso_file(make_iso9660: Callable[..., bytes], mocker: MockerFixture,
                               runner: CliRunner, tmp_path: Path) -> None:
    iso = tmp_path / 'game.iso'
    iso.write_bytes(make_iso9660(ark_data=bytes(16)))  # No ARK\0 magic: the Amplitude layout.
    seen: dict[str, bytes] = {}

    def capture(work_dir: Path, **_kwargs: object) -> dict[str, str]:
        seen['ark'] = (work_dir / 'GEN' / 'MAIN.ARK').read_bytes()
        return {'GEN/MAIN.ARK': 'ok'}

    mocker.patch('destin.harmonix.unpacker.run_game', side_effect=capture)
    result = runner.invoke(main, (str(iso), '-o', str(tmp_path / 'out')))
    assert result.exit_code == 0
    assert seen['ark'] == bytes(16)  # The ISO was extracted into the output directory.


def test_main_delete_flag(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'MAIN.ARK').write_bytes(bytes(16))
    mocker.patch('destin.harmonix.unpacker.materialize')
    run_game = mocker.patch('destin.harmonix.unpacker.run_game',
                            return_value={'GEN/MAIN.ARK': 'ok'})
    result = runner.invoke(main, (str(game), '-o', str(tmp_path / 'out'), '--delete'))
    assert result.exit_code == 0
    assert run_game.call_args.kwargs['delete'] is True


def test_main_default_output_dir(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(bytes(16))
    mocker.patch('destin.harmonix.unpacker.materialize')
    run_game = mocker.patch('destin.harmonix.unpacker.run_game',
                            return_value={'GEN/MAIN.ARK': 'ok'})
    result = runner.invoke(main, (str(tmp_path),))
    assert result.exit_code == 0
    assert run_game.call_args.args == (Path(),)
    assert run_game.call_args.kwargs['jobs'] == 0


def test_main_debug_skips_spinner(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(bytes(16))
    mocker.patch('destin.harmonix.unpacker.materialize')
    run_game = mocker.patch('destin.harmonix.unpacker.run_game',
                            return_value={'GEN/MAIN.ARK': 'ok'})
    console = mocker.patch('destin.amplitude.main.console')
    result = runner.invoke(main, (str(tmp_path), '--debug'))
    assert result.exit_code == 0
    console.status.assert_not_called()
    assert run_game.call_args.kwargs['on_status'] is None


def test_main_uses_spinner(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(bytes(16))
    mocker.patch('destin.harmonix.unpacker.materialize')
    mocker.patch('destin.harmonix.unpacker.run_game', return_value={'GEN/MAIN.ARK': 'ok'})
    console = mocker.patch('destin.amplitude.main.console')
    result = runner.invoke(main, (str(tmp_path),))
    assert result.exit_code == 0
    console.status.assert_called_once()


def test_main_rejects_negative_jobs(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'MAIN.ARK').write_bytes(bytes(16))
    result = runner.invoke(main, (str(tmp_path), '--jobs', '-1'))
    assert result.exit_code == 2


def test_main_aborts_on_unaccepted_source(runner: CliRunner, tmp_path: Path) -> None:
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'ROOT.ARK').write_bytes(b'ARK\x00' + bytes(12))  # FreQuency layout, not Amplitude.
    result = runner.invoke(main, (str(game), '-o', str(tmp_path / 'out')))
    assert result.exit_code == 1
    assert 'No Amplitude ARK' in result.output
