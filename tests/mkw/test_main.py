"""Tests for the Mario Kart World command group."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dade.mkw.main import mkw

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_extract_command_reports_counts(runner: CliRunner, mocker: MockerFixture,
                                        tmp_path: Path) -> None:
    convert = mocker.patch('dade.mkw.main.extract', return_value={'models': 2, 'audio': 1})
    result = runner.invoke(mkw, [
        'extract',
        str(tmp_path), '-o',
        str(tmp_path / 'output'), '--limit', '3', '--pattern', 'Model/*', '--force'
    ])

    assert result.exit_code == 0
    assert 'models: 2, audio: 1' in result.output
    convert.assert_called_once_with(tmp_path, tmp_path / 'output', 3, 'Model/*', force=True)


def test_extract_command_reports_conversion_error(runner: CliRunner, mocker: MockerFixture,
                                                  tmp_path: Path) -> None:
    mocker.patch('dade.mkw.main.extract', side_effect=ValueError('bad archive'))
    result = runner.invoke(mkw, ['extract', str(tmp_path), '-o', str(tmp_path / 'output')])

    assert result.exit_code != 0
    assert 'bad archive' in result.output
