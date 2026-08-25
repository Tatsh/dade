"""Tests for the ``dade ddrsplus`` commands."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dade.common.tools import ToolNotFoundError
from dade.ddrsplus.main import ddrsplus, main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_extract_gen_writes_a_directory_per_input(make_gen: Callable[..., bytes], runner: CliRunner,
                                                  tmp_path: Path) -> None:
    source = tmp_path / '259.gen'
    source.write_bytes(make_gen())
    result = runner.invoke(ddrsplus, ('extract-gen', str(source), '--gap', '1.5'))
    assert result.exit_code == 0
    assert (tmp_path / '259' / '259.sm').is_file()


def test_extract_gen_honours_the_output_directory(make_gen: Callable[..., bytes], runner: CliRunner,
                                                  tmp_path: Path) -> None:
    source = tmp_path / '259.gen'
    source.write_bytes(make_gen())
    target = tmp_path / 'out'
    result = runner.invoke(ddrsplus, ('extract-gen', str(source), '-o', str(target), '--gap', '0'))
    assert result.exit_code == 0
    assert (target / '259.5.json').is_file()


def test_extract_gen_reports_the_gap_it_used(make_gen: Callable[..., bytes], runner: CliRunner,
                                             tmp_path: Path) -> None:
    source = tmp_path / '259.gen'
    source.write_bytes(make_gen())
    result = runner.invoke(ddrsplus, ('extract-gen', str(source), '--gap', '5.339'))
    assert 'gap 5.339s' in result.output


def test_extract_gen_accepts_several_inputs(make_gen: Callable[..., bytes], runner: CliRunner,
                                            tmp_path: Path) -> None:
    for name in ('a.gen', 'b.gen'):
        (tmp_path / name).write_bytes(make_gen())
    result = runner.invoke(
        ddrsplus, ('extract-gen', str(tmp_path / 'a.gen'), str(tmp_path / 'b.gen'), '--gap', '0'))
    assert result.exit_code == 0
    assert (tmp_path / 'a' / 'a.sm').is_file()
    assert (tmp_path / 'b' / 'b.sm').is_file()


def test_extract_gen_aborts_on_a_bad_container(runner: CliRunner, tmp_path: Path) -> None:
    source = tmp_path / 'bad.gen'
    source.write_bytes(b'not a container')
    result = runner.invoke(ddrsplus, ('extract-gen', str(source), '--gap', '0'))
    assert result.exit_code == 1
    assert 'Too short' in result.output


def test_extract_gen_needs_an_existing_file(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(ddrsplus, ('extract-gen', str(tmp_path / 'missing.gen')))
    assert result.exit_code != 0


def test_extract_gen_locates_ffmpeg_when_neither_flag_is_given(make_gen: Callable[..., bytes],
                                                               runner: CliRunner, tmp_path: Path,
                                                               mocker: MockerFixture) -> None:
    source = tmp_path / '259.gen'
    source.write_bytes(make_gen())
    mocker.patch('dade.ddrsplus.commands.extract_gen.locate_tool', return_value=tmp_path / 'ffmpeg')
    result = runner.invoke(ddrsplus, ('extract-gen', str(source)))
    assert result.exit_code == 0


def test_extract_gen_warns_when_ffmpeg_cannot_be_found(make_gen: Callable[..., bytes],
                                                       runner: CliRunner, tmp_path: Path,
                                                       mocker: MockerFixture) -> None:
    source = tmp_path / '259.gen'
    source.write_bytes(make_gen())
    mocker.patch('dade.ddrsplus.commands.extract_gen.locate_tool', side_effect=ToolNotFoundError)
    result = runner.invoke(ddrsplus, ('extract-gen', str(source)))
    assert result.exit_code == 0


def test_the_group_entry_point(mocker: MockerFixture) -> None:
    group = mocker.patch('dade.ddrsplus.main.ddrsplus')
    main()
    group.assert_called_once_with()
