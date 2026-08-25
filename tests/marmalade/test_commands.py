"""Tests for the ``marm`` command-line tool."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dade.marmalade.main import marm
from dade.marmalade.test_utils import build_derbh, build_model, build_resgroup, build_texture

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


def _write_dz(tmp_path: Path) -> Path:
    archive = tmp_path / 'game.dz'
    archive.write_bytes(build_derbh([('a.bin', b'one'), ('sub/b.bin', b'two')]))
    return archive


def _write_group(tmp_path: Path) -> Path:
    group = tmp_path / 'title.group.bin'
    body = build_resgroup(
        'demo', {
            'CIwModel': [build_model([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])],
            'CIwTexture': [build_texture(2, 2, 4, bytes(range(16)))]
        })
    group.write_bytes(body)
    return group


def test_extract_dz_writes_files_and_deletes_source(runner: CliRunner, tmp_path: Path) -> None:
    archive = _write_dz(tmp_path)
    out = tmp_path / 'out'
    result = runner.invoke(marm, ('extract-dz', str(archive), str(out)))
    assert result.exit_code == 0
    assert (out / 'a.bin').read_bytes() == b'one'
    assert (out / 'sub' / 'b.bin').read_bytes() == b'two'
    assert 'Extracted a.bin' in result.output
    assert not archive.exists()


def test_extract_dz_no_delete_keeps_source(runner: CliRunner, tmp_path: Path) -> None:
    archive = _write_dz(tmp_path)
    result = runner.invoke(marm, ('extract-dz', str(archive), str(tmp_path / 'out'), '--no-delete'))
    assert result.exit_code == 0
    assert archive.exists()


def test_extract_dz_quiet_and_debug(runner: CliRunner, tmp_path: Path) -> None:
    archive = _write_dz(tmp_path)
    result = runner.invoke(
        marm, ('extract-dz', str(archive), str(tmp_path / 'out'), '--quiet', '--debug'))
    assert result.exit_code == 0
    assert 'Extracted a.bin' not in result.output
    assert 'Extracted 2 files' in result.output


def test_extract_group_decodes_resources(runner: CliRunner, tmp_path: Path) -> None:
    group = _write_group(tmp_path)
    out = tmp_path / 'out'
    result = runner.invoke(marm, ('extract-group', str(group), str(out)))
    assert result.exit_code == 0
    assert list((out / 'CIwModel').glob('*.obj'))
    assert list((out / 'CIwTexture').glob('*.png'))
    assert not group.exists()


def test_extract_group_raw_and_no_delete(runner: CliRunner, tmp_path: Path) -> None:
    group = _write_group(tmp_path)
    out = tmp_path / 'out'
    result = runner.invoke(marm, ('extract-group', str(group), str(out), '--raw', '--no-delete'))
    assert result.exit_code == 0
    assert list((out / 'CIwModel').glob('*.bin'))
    assert not list((out / 'CIwModel').glob('*.obj'))
    assert group.exists()
