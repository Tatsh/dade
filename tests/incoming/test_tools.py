from __future__ import annotations

from typing import TYPE_CHECKING

from destin.common.context import using_tool_paths
from destin.incoming.tools import ToolNotFoundError, find_spvr2png, run_gdiextract, run_unshield
import pytest

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
    mocker.patch('destin.common.tools.which', return_value=str(binary))
    assert find_spvr2png() == binary


def test_locate_not_found(mocker: MockerFixture) -> None:
    mocker.patch('destin.common.tools.which', return_value=None)
    with pytest.raises(ToolNotFoundError, match='Could not find'):
        find_spvr2png()


def test_run_unshield_with_lib(tmp_path: Path, mocker: MockerFixture,
                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('LD_LIBRARY_PATH', raising=False)
    build = tmp_path / 'build'
    (build / 'src').mkdir(parents=True)
    (build / 'lib').mkdir()
    binary = build / 'src' / 'unshield'
    binary.write_text('x')
    run = mocker.patch('destin.incoming.tools.sp.run')
    with using_tool_paths({'unshield': binary}):
        run_unshield(tmp_path / 'DATA1.CAB', tmp_path / 'out')
    env = run.call_args.kwargs['env']
    assert env['LD_LIBRARY_PATH'] == str(build / 'lib')


def test_run_unshield_lib_appends(tmp_path: Path, mocker: MockerFixture,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    build = tmp_path / 'build'
    (build / 'src').mkdir(parents=True)
    (build / 'lib').mkdir()
    binary = build / 'src' / 'unshield'
    binary.write_text('x')
    monkeypatch.setenv('LD_LIBRARY_PATH', '/existing')
    run = mocker.patch('destin.incoming.tools.sp.run')
    with using_tool_paths({'unshield': binary}):
        run_unshield(tmp_path / 'c.cab', tmp_path / 'out')
    assert run.call_args.kwargs['env']['LD_LIBRARY_PATH'].endswith(':/existing')


def test_run_unshield_no_lib(tmp_path: Path, mocker: MockerFixture) -> None:
    binary = tmp_path / 'unshield'
    binary.write_text('x')
    run = mocker.patch('destin.incoming.tools.sp.run')
    with using_tool_paths({'unshield': binary}):
        run_unshield(tmp_path / 'c.cab', tmp_path / 'out')
    run.assert_called_once()


def test_run_gdiextract(tmp_path: Path, mocker: MockerFixture) -> None:
    binary = tmp_path / 'gdiextract'
    binary.write_text('x')
    run = mocker.patch('destin.incoming.tools.sp.run')
    with using_tool_paths({'gdiextract': binary}):
        run_gdiextract(tmp_path / 'x.gdi', tmp_path / 'out')
    run.assert_called_once()
