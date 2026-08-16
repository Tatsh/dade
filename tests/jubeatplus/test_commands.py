"""Tests for the ``destin jubeatplus unpack`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.jubeatplus.commands.unpack import unpack
from destin.jubeatplus.main import jubeatplus, main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture
    import pytest


def test_unpack_converts_a_bundle(runner: CliRunner, tmp_path: Path, make_bundle: Callable[...,
                                                                                           Path],
                                  fake_ffmpeg: Path, fake_pngdefry: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(unpack,
                           (str(make_bundle()), '-o', str(out), '--ffmpeg-path', str(fake_ffmpeg),
                            '--pngdefry-path', str(fake_pngdefry), '-j', '1'))
    assert result.exit_code == 0
    assert 'png' in result.output
    assert (out / 'Example.app' / 'texture.png').is_file()


def test_unpack_summarises_every_action(runner: CliRunner, tmp_path: Path,
                                        make_bundle: Callable[..., Path], fake_ffmpeg: Path,
                                        fake_pngdefry: Path) -> None:
    result = runner.invoke(unpack,
                           (str(make_bundle()), '-o', str(tmp_path / 'out'), '--ffmpeg-path',
                            str(fake_ffmpeg), '--pngdefry-path', str(fake_pngdefry), '-j', '1'))
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        'copy       1 ok, 0 fail', 'coredata   1 ok, 0 fail', 'jbt        1 ok, 0 fail',
        'macho      1 ok, 0 fail', 'plist      2 ok, 0 fail', 'png        1 ok, 0 fail',
        'strings    1 ok, 0 fail', 'tex        1 ok, 0 fail', 'zip        1 ok, 0 fail'
    ]


def test_unpack_without_the_helper_tools(runner: CliRunner, tmp_path: Path,
                                         make_bundle: Callable[..., Path]) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(
        unpack, (str(make_bundle()), '-o', str(out), '--no-audio', '--no-png', '-j', '1'))
    assert result.exit_code == 0
    assert b'CgBI' in (out / 'Example.app' / 'icon.png').read_bytes()


def test_unpack_rejects_a_tool_path_that_is_not_there(runner: CliRunner, tmp_path: Path,
                                                      make_bundle: Callable[..., Path]) -> None:
    result = runner.invoke(unpack, (str(make_bundle()), '-o', str(
        tmp_path / 'out'), '--pngdefry-path', str(tmp_path / 'absent')))
    assert result.exit_code != 0
    assert 'does not exist' in result.output


def test_unpack_aborts_when_a_tool_is_not_on_the_path(runner: CliRunner, tmp_path: Path,
                                                      make_bundle: Callable[..., Path],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PATH', str(tmp_path / 'nothing-here'))
    result = runner.invoke(unpack, (str(make_bundle()), '-o', str(tmp_path / 'out')))
    assert result.exit_code != 0
    assert 'Could not find `ffmpeg`' in result.output


def test_unpack_aborts_when_there_is_no_bundle(runner: CliRunner, tmp_path: Path, fake_ffmpeg: Path,
                                               fake_pngdefry: Path) -> None:
    empty = tmp_path / 'empty'
    empty.mkdir()
    result = runner.invoke(unpack, (str(empty), '-o', str(tmp_path / 'out'), '--ffmpeg-path',
                                    str(fake_ffmpeg), '--pngdefry-path', str(fake_pngdefry)))
    assert result.exit_code != 0
    assert 'No .app bundle' in result.output


def test_the_group_lists_unpack(runner: CliRunner) -> None:
    result = runner.invoke(jubeatplus, ('--help',))
    assert result.exit_code == 0
    assert 'unpack' in result.output


def test_the_group_entry_point(mocker: MockerFixture) -> None:
    group = mocker.patch('destin.jubeatplus.main.jubeatplus')
    main()
    group.assert_called_once_with()
