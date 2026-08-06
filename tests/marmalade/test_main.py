"""Tests for :mod:`destin.marmalade.main`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from destin.marmalade.main import main, marm

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_marm_group_lists_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(marm, ('--help',))
    assert result.exit_code == 0
    assert 'extract-dz' in result.output
    assert 'extract-group' in result.output


def test_main_invokes_group(mocker: MockerFixture) -> None:
    marm_mock = mocker.patch('destin.marmalade.main.marm')
    main()
    marm_mock.assert_called_once_with()
