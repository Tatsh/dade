"""Tests for the ``destin misc sc-info`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

from destin.misc.commands.sc_info import sc_info
from destin.misc.main import misc

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


def test_group_is_mounted_under_misc(runner: CliRunner) -> None:
    result = runner.invoke(misc, ('--help',))
    assert result.exit_code == 0
    assert 'sc-info' in result.output


def test_group_lists_dump(runner: CliRunner) -> None:
    result = runner.invoke(sc_info, ('--help',))
    assert result.exit_code == 0
    assert 'dump' in result.output


def test_dump_writes_a_report(runner: CliRunner, sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir)))
    assert result.exit_code == 0
    assert 'Purchase record (.sinf)' in result.output
    assert 'Example Buyer' in result.output
    assert 'CN=Example EC Leaf' in result.output


def test_dump_json(runner: CliRunner, sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir), '--json'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    assert rendered['sinf']['accountName'] == 'Example Buyer'
    assert rendered['supf']['certificate']['publicKey']['algorithm'] == 'EC'
    assert rendered['manifest']['SinfPaths'] == ['SC_Info/Example.sinf']


def test_dump_accepts_the_directory_itself(runner: CliRunner, sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir / 'Example.app' / 'SC_Info')))
    assert result.exit_code == 0


def test_dump_aborts_without_an_sc_info_directory(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(tmp_path)))
    assert result.exit_code == 1
    assert 'No SC_Info directory' in result.output


def test_dump_rejects_a_file(runner: CliRunner, compiled_strings: Path) -> None:
    assert runner.invoke(sc_info, ('dump', str(compiled_strings))).exit_code == 2


def test_dump_on_an_empty_directory(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'SC_Info').mkdir()
    result = runner.invoke(sc_info, ('dump', str(tmp_path)))
    assert result.exit_code == 0
    assert 'Files' in result.output


def test_dump_region_option(runner: CliRunner, sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir), '--region', 'JP', '--json'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)
    # The code is accepted in either case and lands in the link lowercased.
    assert rendered['region'] == 'jp'
    assert rendered['appStoreURL'] == 'https://apps.apple.com/jp/app/id472140433'


def test_dump_without_a_region_says_why_there_is_no_url(runner: CliRunner,
                                                        sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir)))
    assert result.exit_code == 0
    assert 'App Store URL: unknown' in result.output
    assert 'Store item ID: 472140433' in result.output
