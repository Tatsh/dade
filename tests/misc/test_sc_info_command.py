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
    # One entry per bundle read, so the shape does not change when there are several.
    rendered = json.loads(result.output)
    assert len(rendered) == 1
    assert rendered[0]['bundle'] == 'Payload/Example.app'
    assert rendered[0]['isMain'] is True
    assert rendered[0]['sinf']['accountName'] == 'Example Buyer'
    assert rendered[0]['supf']['certificate']['publicKey']['algorithm'] == 'EC'
    assert rendered[0]['manifest']['SinfPaths'] == ['SC_Info/Example.sinf']


def test_dump_accepts_the_directory_itself(runner: CliRunner, sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir / 'Example.app' / 'SC_Info')))
    assert result.exit_code == 0


def test_dump_aborts_without_an_sc_info_directory(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(tmp_path)))
    assert result.exit_code == 1
    assert 'No SC_Info directory' in result.output


def test_dump_on_an_empty_directory(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'SC_Info').mkdir()
    result = runner.invoke(sc_info, ('dump', str(tmp_path)))
    assert result.exit_code == 0
    assert 'Files' in result.output


def test_dump_region_option(runner: CliRunner, sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir), '--region', 'JP', '--json'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)[0]
    # The code is accepted in either case and lands in the link lowercased.
    assert rendered['region'] == 'jp'
    assert rendered['appStoreURL'] == 'https://apps.apple.com/jp/app/id472140433'


def test_dump_without_a_region_falls_back_to_the_region_less_url(runner: CliRunner,
                                                                 sc_info_dir: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_dir)))
    assert result.exit_code == 0
    assert 'App Store URL: https://apps.apple.com/app/id472140433' in result.output
    assert 'Store item ID: 472140433' in result.output


def test_dump_accepts_an_ipa(runner: CliRunner, sc_info_ipa: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(sc_info_ipa), '--json'))
    assert result.exit_code == 0
    rendered = json.loads(result.output)[0]
    assert rendered['region'] == 'jp'
    assert rendered['supp']['records']


def test_dump_rejects_a_file_that_is_not_an_ipa(runner: CliRunner, text_strings: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(text_strings)))
    assert result.exit_code == 1
    assert 'is a file but not an .ipa' in result.output


def test_dump_reads_every_bundle(runner: CliRunner, nested_ipa: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(nested_ipa), '--json'))
    assert result.exit_code == 0
    assert [entry['bundle'] for entry in json.loads(result.output)] == [
        'Payload/Example.app', 'Payload/Example.app/PlugIns/Widget.appex'
    ]


def test_dump_main_bundle_option(runner: CliRunner, nested_ipa: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(nested_ipa), '--main-bundle', '--json'))
    assert result.exit_code == 0
    assert [entry['bundle'] for entry in json.loads(result.output)] == ['Payload/Example.app']


def test_dump_bundle_option(runner: CliRunner, nested_ipa: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(nested_ipa), '--bundle', 'Widget.appex'))
    assert result.exit_code == 0
    assert 'Bundle: Payload/Example.app/PlugIns/Widget.appex (not the application)' in result.output
    assert 'Payload/Example.app\n' not in result.output


def test_dump_bundle_option_rejects_an_unknown_name(runner: CliRunner, nested_ipa: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(nested_ipa), '--bundle', 'Nope'))
    assert result.exit_code == 1
    assert "No bundle named 'Nope'" in result.output


def test_dump_separates_the_bundles_it_reports(runner: CliRunner, nested_ipa: Path) -> None:
    result = runner.invoke(sc_info, ('dump', str(nested_ipa)))
    assert result.exit_code == 0
    assert result.output.count('Bundle: ') == 2
