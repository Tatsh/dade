from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin import __version__
from destin.main import main

if TYPE_CHECKING:
    from click.testing import CliRunner

_GAMES = (
    'amplitude',
    'bit192',
    'bitrock',
    'ddrsplus',
    'frequency',
    'i76',
    'incoming',
    'jubeatplus',
    'marmalade',
    'misc',
    'monopoly08',
    'rhythmin',
    'thps2pc',
    'xg2',
)


def test_main_lists_every_game(runner: CliRunner) -> None:
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    for game in _GAMES:
        assert game in result.output


def test_main_version(runner: CliRunner) -> None:
    result = runner.invoke(main, ['--version'])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_main_registers_games_alphabetically() -> None:
    assert tuple(main.commands) == tuple(sorted(main.commands))
    assert set(main.commands) == set(_GAMES)


@pytest.mark.parametrize('game', _GAMES)
def test_each_game_group_has_help(runner: CliRunner, game: str) -> None:
    result = runner.invoke(main, [game, '--help'])
    assert result.exit_code == 0
    assert result.output


@pytest.mark.parametrize(('game', 'subcommand'), [
    ('amplitude', 'unpack'),
    ('frequency', 'unpack'),
    ('bitrock', 'crack'),
    ('bitrock', 'extract'),
    ('incoming', 'extract'),
    ('incoming', 'extract-pvr-pack'),
    ('incoming', 'ian2obj'),
    ('monopoly08', 'extract'),
])
def test_wrapped_single_commands_are_mounted(runner: CliRunner, game: str, subcommand: str) -> None:
    result = runner.invoke(main, [game, subcommand, '--help'])
    assert result.exit_code == 0
    assert subcommand in result.output
