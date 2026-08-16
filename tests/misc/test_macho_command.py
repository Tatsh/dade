"""Tests for the ``destin misc macho`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

from destin.misc.commands.macho import macho
from destin.misc.main import misc

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


def test_group_is_mounted_under_misc(runner: CliRunner) -> None:
    result = runner.invoke(misc, ('--help',))
    assert result.exit_code == 0
    assert 'macho' in result.output


def test_group_lists_dump(runner: CliRunner) -> None:
    result = runner.invoke(macho, ('--help',))
    assert result.exit_code == 0
    assert 'dump' in result.output


def test_macho_dump_writes_json(runner: CliRunner, macho_arm64: Path) -> None:
    result = runner.invoke(macho, ('dump', str(macho_arm64)))
    assert result.exit_code == 0
    info = json.loads(result.output)
    assert info['architectures'][0]['architecture'] == 'arm64'
    assert info['is_universal'] is False


def test_macho_dump_reads_every_slice(runner: CliRunner, macho_universal: Path) -> None:
    result = runner.invoke(macho, ('dump', str(macho_universal)))
    assert result.exit_code == 0
    assert len(json.loads(result.output)['architectures']) == 2


def test_macho_dump_aborts_on_a_foreign_file(runner: CliRunner, text_strings: Path) -> None:
    result = runner.invoke(macho, ('dump', str(text_strings)))
    assert result.exit_code != 0
    assert 'Not a little-endian Mach-O slice' in result.output
