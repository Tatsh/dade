from __future__ import annotations

from typing import TYPE_CHECKING

from dade.common.context import using_tool_paths
from dade.common.tools import run_unshield

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture
    import pytest


def test_run_unshield_with_lib(tmp_path: Path, mocker: MockerFixture,
                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('LD_LIBRARY_PATH', raising=False)
    build = tmp_path / 'build'
    (build / 'src').mkdir(parents=True)
    (build / 'lib').mkdir()
    binary = build / 'src' / 'unshield'
    binary.write_text('x')
    run = mocker.patch('dade.common.tools.sp.run')
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
    run = mocker.patch('dade.common.tools.sp.run')
    with using_tool_paths({'unshield': binary}):
        run_unshield(tmp_path / 'c.cab', tmp_path / 'out')
    assert run.call_args.kwargs['env']['LD_LIBRARY_PATH'].endswith(':/existing')


def test_run_unshield_no_lib(tmp_path: Path, mocker: MockerFixture) -> None:
    binary = tmp_path / 'unshield'
    binary.write_text('x')
    run = mocker.patch('dade.common.tools.sp.run')
    with using_tool_paths({'unshield': binary}):
        run_unshield(tmp_path / 'c.cab', tmp_path / 'out')
    run.assert_called_once()
