"""CLI tests for the ``tonesphere extract`` command."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dade.bit192.commands.extract import extract

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_extract_invokes_library_and_reports_root(runner: CliRunner, mocker: MockerFixture,
                                                  tmp_path: Path) -> None:
    bundle = tmp_path / 'app.xapk'
    bundle.write_bytes(b'PK')
    out = tmp_path / 'out'
    extract_assets = mocker.patch('dade.bit192.commands.extract.extract_assets', return_value=out)
    result = runner.invoke(extract, [str(bundle), '-o', str(out)])
    assert result.exit_code == 0
    # Rich may hard-wrap the long tmp_path, so match the unwrapped prefix only.
    assert 'Extracted all assets' in result.output
    extract_assets.assert_called_once_with((bundle,), out, keep_group_bin=False)


def test_extract_keep_group_bin_flag(runner: CliRunner, mocker: MockerFixture,
                                     tmp_path: Path) -> None:
    bundle = tmp_path / 'app.xapk'
    bundle.write_bytes(b'PK')
    out = tmp_path / 'out'
    extract_assets = mocker.patch('dade.bit192.commands.extract.extract_assets', return_value=out)
    result = runner.invoke(extract, [str(bundle), '-o', str(out), '--keep-group-bin'])
    assert result.exit_code == 0
    extract_assets.assert_called_once_with((bundle,), out, keep_group_bin=True)


def test_extract_requires_output(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    bundle = tmp_path / 'app.xapk'
    bundle.write_bytes(b'PK')
    extract_assets = mocker.patch('dade.bit192.commands.extract.extract_assets')
    result = runner.invoke(extract, [str(bundle)])
    assert result.exit_code == 2
    extract_assets.assert_not_called()
