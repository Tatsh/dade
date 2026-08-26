"""Tests for the ``dade rbplus`` commands."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json

from dade.rbplus.main import main, rbplus

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture
    import pytest


def test_the_standalone_entry_point_runs_the_group(mocker: MockerFixture) -> None:
    group = mocker.patch('dade.rbplus.main.rbplus')
    main()
    group.assert_called_once_with()


def test_the_group_lists_its_commands(runner: CliRunner) -> None:
    result = runner.invoke(rbplus, ('--help',))
    assert result.exit_code == 0
    assert 'dump-chart' in result.output
    assert 'extract-assets' in result.output
    assert 'unpack' in result.output


def test_no_help_text_carries_a_numpy_section(runner: CliRunner) -> None:
    for command in ('dump-chart', 'extract-assets', 'unpack'):
        result = runner.invoke(rbplus, (command, '--help'))
        assert result.exit_code == 0
        assert 'Raises' not in result.output
        assert 'Parameters\n' not in result.output


def test_unpack_converts_a_bundle(runner: CliRunner, app_bundle: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        rbplus, ('unpack', str(app_bundle), '-o', str(tmp_path / 'out'), '--no-audio', '--no-png'))
    assert result.exit_code == 0
    assert 'package' in result.output
    assert (tmp_path / 'out' / 'Rb' / '100000109' / 'info.json').is_file()


def test_unpack_reports_a_missing_tool(runner: CliRunner, app_bundle: Path, tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    # An empty PATH is how the tool really goes missing, which avoids patching a name the command
    # module and the Click command inside it both answer to.
    monkeypatch.setenv('PATH', '')
    result = runner.invoke(rbplus, ('unpack', str(app_bundle), '-o', str(tmp_path / 'out')))
    assert result.exit_code == 1
    assert 'ffmpeg' in result.output


def test_unpack_reports_a_source_with_no_bundle(runner: CliRunner, tmp_path: Path) -> None:
    empty = tmp_path / 'empty'
    empty.mkdir()
    result = runner.invoke(
        rbplus, ('unpack', str(empty), '-o', str(tmp_path / 'out'), '--no-audio', '--no-png'))
    assert result.exit_code == 1
    assert 'No .app bundle' in result.output


def test_extract_assets_unpacks_an_archive(runner: CliRunner, make_asset_archive: Callable[...,
                                                                                           Path],
                                           tmp_path: Path, make_png: Callable[..., bytes]) -> None:
    archive = make_asset_archive(entries={'a.png': make_png()}, manifest=('a.png',))
    result = runner.invoke(
        rbplus, ('extract-assets', str(archive), '-o', str(tmp_path / 'out'), '--no-png'))
    assert result.exit_code == 0
    assert (tmp_path / 'out' / 'iPad' / 'a.png').is_file()
    assert (tmp_path / 'out' / 'iPad' / 'manifest.json').is_file()


def test_extract_assets_reports_a_missing_tool(runner: CliRunner,
                                               make_asset_archive: Callable[...,
                                                                            Path], tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PATH', '')
    result = runner.invoke(
        rbplus, ('extract-assets', str(make_asset_archive()), '-o', str(tmp_path / 'out')))
    assert result.exit_code == 1
    assert 'pngdefry' in result.output


def test_extract_assets_reports_a_bad_archive(runner: CliRunner, tmp_path: Path) -> None:
    broken = tmp_path / 'broken.zip'
    broken.write_bytes(b'not a zip')
    result = runner.invoke(rbplus,
                           ('extract-assets', str(broken), '-o', str(tmp_path / 'out'), '--no-png'))
    assert result.exit_code == 1
    assert 'not a ZIP archive' in result.output


def test_dump_chart_writes_json(runner: CliRunner, tune_package: Path) -> None:
    result = runner.invoke(rbplus, ('dump-chart', str(tune_package), 'bas'))
    assert result.exit_code == 0
    chart = json.loads(result.output)
    assert chart['header']['version'] == 11
    assert len(chart['notes']) == chart['header']['note_count']


def test_dump_chart_defaults_to_basic(runner: CliRunner, tune_package: Path) -> None:
    result = runner.invoke(rbplus, ('dump-chart', str(tune_package)))
    assert result.exit_code == 0
    assert json.loads(result.output)['header']['note_count'] == 4


def test_dump_chart_summary_drops_the_notes(runner: CliRunner, tune_package: Path) -> None:
    result = runner.invoke(rbplus, ('dump-chart', str(tune_package), 'bas', '--summary'))
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert 'notes' not in payload
    assert payload['tempo_event_count'] == 2


def test_dump_chart_renders_an_image(runner: CliRunner, tune_package: Path, tmp_path: Path) -> None:
    image = tmp_path / 'chart.png'
    result = runner.invoke(rbplus, ('dump-chart', str(tune_package), 'har', '--image', str(image)))
    assert result.exit_code == 0
    assert image.is_file()


def test_dump_chart_reports_an_absent_difficulty(runner: CliRunner, make_package: Callable[...,
                                                                                           Path],
                                                 chart_bytes: bytes) -> None:
    package = make_package(entries={'note_bas': chart_bytes})
    result = runner.invoke(rbplus, ('dump-chart', str(package), 'har'))
    assert result.exit_code == 1
    assert 'holds no note_har chart' in result.output
    assert 'note_bas' in result.output


def test_dump_chart_reports_a_package_that_will_not_open(runner: CliRunner, tmp_path: Path) -> None:
    broken = tmp_path / 'broken.rb'
    broken.write_bytes(b'not a zip')
    result = runner.invoke(rbplus, ('dump-chart', str(broken)))
    assert result.exit_code == 1
    assert 'not a ZIP archive' in result.output


def test_dump_chart_reports_a_chart_that_will_not_parse(runner: CliRunner,
                                                        make_package: Callable[..., Path]) -> None:
    package = make_package(entries={'note_bas': b'NOPE' + bytes(64)})
    result = runner.invoke(rbplus, ('dump-chart', str(package)))
    assert result.exit_code == 1
    assert 'Not a chart' in result.output


def test_an_unknown_difficulty_is_refused(runner: CliRunner, tune_package: Path) -> None:
    result = runner.invoke(rbplus, ('dump-chart', str(tune_package), 'nope'))
    assert result.exit_code != 0


def test_dump_chart_reads_a_bare_chart_named_by_its_file(
        runner: CliRunner, make_chart_file: Callable[..., Path]) -> None:
    result = runner.invoke(rbplus, ('dump-chart', str(make_chart_file('note_har')), '--summary'))
    assert result.exit_code == 0
    assert json.loads(result.output)['header']['version']


def test_dump_chart_reads_a_deciphered_chart(runner: CliRunner,
                                             make_chart_file: Callable[..., Path]) -> None:
    path = make_chart_file('note_med', decode_type=None)
    result = runner.invoke(rbplus, ('dump-chart', str(path), '--summary'))
    assert result.exit_code == 0
    assert json.loads(result.output)['header']['version']


def test_dump_chart_takes_the_difficulty_when_the_name_is_silent(
        runner: CliRunner, make_chart_file: Callable[..., Path]) -> None:
    path = make_chart_file('mystery')
    result = runner.invoke(rbplus, ('dump-chart', str(path), 'har', '--summary'))
    assert result.exit_code == 0
    assert json.loads(result.output)['header']['version']


def test_dump_chart_needs_a_difficulty_when_the_name_is_silent(
        runner: CliRunner, make_chart_file: Callable[..., Path]) -> None:
    result = runner.invoke(rbplus, ('dump-chart', str(make_chart_file('mystery')), '--summary'))
    assert result.exit_code != 0
    assert 'does not say which difficulty' in result.output


def test_dump_chart_takes_a_key_and_an_iv(runner: CliRunner,
                                          make_chart_file: Callable[..., Path]) -> None:
    key, iv = bytes(range(16)), bytes(range(8))
    path = make_chart_file('note_har', iv=iv, key=key)
    result = runner.invoke(
        rbplus, ('dump-chart', str(path), '--key', key.hex(), '--iv', iv.hex(), '--summary'))
    assert result.exit_code == 0
    assert json.loads(result.output)['header']['version']


def test_dump_chart_reports_a_key_that_is_not_hex(runner: CliRunner,
                                                  make_chart_file: Callable[..., Path]) -> None:
    result = runner.invoke(
        rbplus, ('dump-chart', str(make_chart_file('note_har')), '--key', 'not a hex string'))
    assert result.exit_code != 0
    assert 'not hex' in result.output


def test_dump_chart_reports_a_chart_under_no_known_key(
        runner: CliRunner, make_chart_file: Callable[..., Path]) -> None:
    path = make_chart_file('note_har', key=bytes(range(16)))
    result = runner.invoke(rbplus, ('dump-chart', str(path), '--summary'))
    assert result.exit_code != 0
    assert '--key' in result.output


def test_dump_chart_draws_an_image_from_a_bare_chart(runner: CliRunner, tmp_path: Path,
                                                     make_chart_file: Callable[..., Path]) -> None:
    out = tmp_path / 'chart.png'
    result = runner.invoke(
        rbplus, ('dump-chart', str(make_chart_file('note_har')), '--image', str(out), '--summary'))
    assert result.exit_code == 0
    assert out.is_file()
