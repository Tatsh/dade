from __future__ import annotations

from pathlib import Path

from destin.common.context import input_root, tool_path, using_input_root, using_tool_paths


def test_input_root_default() -> None:
    assert input_root() is None


def test_using_input_root() -> None:
    with using_input_root(Path('/src')):
        assert input_root() == Path('/src')
    assert input_root() is None


def test_tool_path_default() -> None:
    assert tool_path('spvr2png') is None


def test_using_tool_paths() -> None:
    with using_tool_paths({'spvr2png': Path('/bin/spvr2png'), 'gdiextract': None}):
        assert tool_path('spvr2png') == Path('/bin/spvr2png')
        assert tool_path('gdiextract') is None
    assert tool_path('spvr2png') is None
