"""Tests for :mod:`destin.thps2pc.main`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.thps2pc.main import cli
import pytest

if TYPE_CHECKING:
    from click.testing import CliRunner

_EXPECTED = ('convert-scene', 'decode-textures', 'dump-descriptors', 'psx-info',
             'render-authoritative', 'render-layers', 'render-node-map', 'render-object-models',
             'render-objects', 'unpack-pkr')


def test_group_registers_every_subcommand() -> None:
    assert tuple(sorted(cli.commands)) == _EXPECTED


@pytest.mark.parametrize('name', _EXPECTED)
def test_subcommand_help(runner: CliRunner, name: str) -> None:
    result = runner.invoke(cli, [name, '--help'])
    assert result.exit_code == 0
    assert 'Usage:' in result.output


def test_group_help_lists_the_commands(runner: CliRunner) -> None:
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    for name in _EXPECTED:
        assert name in result.output


def test_short_help_flag_is_accepted(runner: CliRunner) -> None:
    assert runner.invoke(cli, ['-h']).exit_code == 0
