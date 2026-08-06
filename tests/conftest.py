"""Configuration for Pytest."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NoReturn
import contextlib
import os

from click.testing import CliRunner
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture

_SETUP_LOGGING_BINDINGS = (
    'destin.amplitude.main',
    'destin.bitrock.commands.crack',
    'destin.bitrock.commands.extract',
    'destin.common.cli',
    'destin.incoming.main',
    'destin.monopoly08.main',
    'destin.xg2.main',
)
"""Modules that import :py:func:`bascom.setup_logging` and are neutralised during tests.

:meta hide-value:
"""

if os.getenv('_PYTEST_RAISE', '0') != '0':  # pragma no cover

    @pytest.hookimpl(tryfirst=True)
    def pytest_exception_interact(call: pytest.CallInfo[None]) -> NoReturn:
        assert call.excinfo is not None
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)
    def pytest_internalerror(excinfo: pytest.ExceptionInfo[BaseException]) -> NoReturn:
        raise excinfo.value


@pytest.fixture(autouse=True)
def _isolate_setup_logging(mocker: MockerFixture) -> None:
    """
    Stop the command callbacks from configuring global logging during the test run.

    Each game's command layer calls :py:func:`bascom.setup_logging`, which replaces the root
    logger's handlers. Now that the suites share one process, the configuration installed by the
    first suite to run would otherwise remove the handler :py:func:`caplog` relies on and hide log
    records from every suite that runs later. Patching the imported name in each module keeps the
    suites independent while still recording the calls.
    """
    for binding in _SETUP_LOGGING_BINDINGS:
        with contextlib.suppress(AttributeError, ImportError):
            mocker.patch(f'{binding}.setup_logging')


@pytest.fixture(autouse=True)
def recover_stale_process_cwd(request: pytest.FixtureRequest) -> None:
    """
    Recover when the process cwd was removed mid-session.

    Gentoo Portage test phases often run pytest with aggressive temporary-directory retention.
    The process working directory can then point at a path that no longer exists, so
    ``Path.cwd()`` raises ``FileNotFoundError`` before ``monkeypatch.chdir`` can save the
    prior cwd.
    """
    try:
        Path.cwd()
    except FileNotFoundError:
        os.chdir(Path(request.config.rootpath))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def make_lzss() -> Callable[[bytes], bytes]:
    """
    Build an LZSS stream of literals only.

    Returns
    -------
    collections.abc.Callable[[bytes], bytes]
        A callable turning a payload into a stream that decodes back to it.
    """
    def build(payload: bytes) -> bytes:
        out = bytearray()
        for i in range(0, len(payload), 8):
            out.append(0xFF)  # Eight literal flags.
            out += payload[i:i + 8]
        return bytes(out)

    return build
