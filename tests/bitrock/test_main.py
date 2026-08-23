from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from destin.bitrock.commands.extract import extract_main as main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner


def test_main_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    assert 'Usage:' in result.output


def test_main_missing_archive(runner: CliRunner) -> None:
    result = runner.invoke(main, [])
    assert result.exit_code != 0


@pytest.fixture
def installer(tmp_path: Path, build_cookfs: Callable[..., bytes]) -> Path:
    path = tmp_path / 'demo.run'
    path.write_bytes(build_cookfs({'dir/a.txt': b'alpha', 'dir/b.txt': b'beta'}))
    return path


@pytest.fixture
def encrypted_installer(tmp_path: Path, build_encrypted_cookfs: Callable[..., bytes]) -> Path:
    path = tmp_path / 'secret.run'
    path.write_bytes(build_encrypted_cookfs({'dir/a.txt': b'alpha'}, b'hunter2'))
    return path


def test_main_list(runner: CliRunner, installer: Path) -> None:
    result = runner.invoke(main, ['--list', str(installer)])
    assert result.exit_code == 0
    assert 'dir/a.txt' in result.output
    assert 'dir/b.txt' in result.output
    assert '2 members' in result.output


def test_main_extract(runner: CliRunner, installer: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(main, [str(installer), '--output-dir', str(out)])
    assert result.exit_code == 0
    assert 'extracting: dir/a.txt' in result.output
    assert '2 members extracted.' in result.output
    assert (out / 'dir/a.txt').read_bytes() == b'alpha'


def test_main_extract_single_member(runner: CliRunner, installer: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(main, [str(installer), 'dir/a.txt', '--output-dir', str(out)])
    assert result.exit_code == 0
    assert '1 member extracted.' in result.output


def test_main_dry_run(runner: CliRunner, installer: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(main, [str(installer), '--dry-run', '--output-dir', str(out)])
    assert result.exit_code == 0
    assert 'would extract: dir/a.txt' in result.output
    assert not out.exists()


def test_main_quiet(runner: CliRunner, installer: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(main, [str(installer), '--quiet', '--output-dir', str(out)])
    assert result.exit_code == 0
    assert 'extracting:' not in result.output


def test_main_missing_member(runner: CliRunner, installer: Path, tmp_path: Path) -> None:
    result = runner.invoke(main, [str(installer), 'nope', '--output-dir', str(tmp_path / 'out')])
    assert result.exit_code != 0
    assert 'nope' in result.output


def test_main_password_option(runner: CliRunner, encrypted_installer: Path, tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(
        main, [str(encrypted_installer), '--password', 'hunter2', '--output-dir',
               str(out)])
    assert result.exit_code == 0
    assert (out / 'dir/a.txt').read_bytes() == b'alpha'


def test_main_prompts_for_password(runner: CliRunner, encrypted_installer: Path,
                                   tmp_path: Path) -> None:
    out = tmp_path / 'out'
    result = runner.invoke(main, [str(encrypted_installer), '--output-dir',
                                  str(out)],
                           input='hunter2\n')
    assert result.exit_code == 0
    assert (out / 'dir/a.txt').read_bytes() == b'alpha'


def test_main_wrong_password_exits_cleanly(runner: CliRunner, encrypted_installer: Path,
                                           tmp_path: Path) -> None:
    result = runner.invoke(
        main, [str(encrypted_installer), '--password', 'nope', '--output-dir',
               str(tmp_path)])
    assert result.exit_code == 1
    assert 'Invalid password' in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_main_list_encrypted_without_password(runner: CliRunner, encrypted_installer: Path) -> None:
    result = runner.invoke(main, ['--list', str(encrypted_installer)])
    assert result.exit_code == 0
    assert 'dir/a.txt' in result.output


def test_main_compression_override(runner: CliRunner, tmp_path: Path,
                                   build_encrypted_cookfs: Callable[..., bytes]) -> None:
    path = tmp_path / 'mislabelled.run'
    path.write_bytes(build_encrypted_cookfs({'a.txt': b'alpha'}, b'pw', decompress_command='lzham'))
    out = tmp_path / 'out'
    result = runner.invoke(
        main, [str(path), '--password', 'pw', '--compression', 'zip', '--output-dir',
               str(out)])
    assert result.exit_code == 0
    assert (out / 'a.txt').read_bytes() == b'alpha'


def test_main_corrupt_archive_exits_cleanly(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / 'broken.run'
    path.write_bytes(b'not a cookfs archive at all')
    result = runner.invoke(main, ['--list', str(path)])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
