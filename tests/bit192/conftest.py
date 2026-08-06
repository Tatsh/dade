"""Shared pytest configuration."""
from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture(autouse=True)
def _isolate_command_logging(mocker: MockerFixture) -> None:
    """Stop command callbacks from configuring real logging during the test run."""
    mocker.patch('destin.common.cli.setup_logging')


@pytest.fixture
def runner() -> CliRunner:
    """
    Provide a Click :py:class:`~click.testing.CliRunner` for command tests.

    Returns
    -------
    click.testing.CliRunner
        A fresh runner for invoking commands.
    """
    return CliRunner()
