from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dade.common.context import using_tool_paths
from dade.incoming.tools import ToolNotFoundError, find_spvr2png, run_gdiextract

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_locate_override(tmp_path: Path) -> None:
    binary = tmp_path / 'spvr2png'
    binary.write_text('x')
    assert find_spvr2png(binary) == binary


def test_locate_override_missing(tmp_path: Path) -> None:
    with pytest.raises(ToolNotFoundError, match='does not exist'):
        find_spvr2png(tmp_path / 'nope')


def test_locate_from_context(tmp_path: Path) -> None:
    binary = tmp_path / 'spvr2png'
    binary.write_text('x')
    with using_tool_paths({'spvr2png': binary}):
        assert find_spvr2png() == binary


def test_locate_from_path(tmp_path: Path, mocker: MockerFixture) -> None:
    binary = tmp_path / 'spvr2png'
    binary.write_text('x')
    mocker.patch('dade.common.tools.which', return_value=str(binary))
    assert find_spvr2png() == binary


def test_locate_not_found(mocker: MockerFixture) -> None:
    mocker.patch('dade.common.tools.which', return_value=None)
    with pytest.raises(ToolNotFoundError, match='Could not find'):
        find_spvr2png()


def test_run_gdiextract(tmp_path: Path, mocker: MockerFixture) -> None:
    binary = tmp_path / 'gdiextract'
    binary.write_text('x')
    run = mocker.patch('dade.incoming.tools.sp.run')
    with using_tool_paths({'gdiextract': binary}):
        run_gdiextract(tmp_path / 'x.gdi', tmp_path / 'out')
    run.assert_called_once()
