"""Tests for :py:mod:`dade.i76.main`."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.i76.main import cli

if TYPE_CHECKING:
    from click.testing import CliRunner

_I76_SUBCOMMANDS = ('build-horizon', 'decode-texture', 'inspect-chunks', 'pak-extract', 'sdf2obj',
                    'zfs-extract', 'zfs-list')
_I82_SUBCOMMANDS = ('stage-i82', 'stage-i82-objects', 'unpack-i82sim')
_SUBCOMMANDS = (*_I76_SUBCOMMANDS, *_I82_SUBCOMMANDS)


def test_group_name() -> None:
    assert cli.name == 'i76'


@pytest.mark.parametrize('name', _SUBCOMMANDS)
def test_subcommand_registered(name: str) -> None:
    assert name in cli.commands


def test_no_unexpected_subcommands() -> None:
    assert set(cli.commands) == set(_SUBCOMMANDS)


@pytest.mark.parametrize('flag', ['-h', '--help'])
def test_help_option_names(runner: CliRunner, flag: str) -> None:
    result = runner.invoke(cli, [flag])
    assert result.exit_code == 0
    assert 'zfs-extract' in result.output


@pytest.mark.parametrize('name', _SUBCOMMANDS)
def test_subcommand_help(runner: CliRunner, name: str) -> None:
    result = runner.invoke(cli, [name, '-h'])
    assert result.exit_code == 0
    assert '--debug' in result.output
