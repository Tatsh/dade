"""
Ambient per-conversion context.

Converters that resolve sibling assets (for example a model's textures) need to know the root of the
source tree, and they may need an explicit path to a native helper tool. Rather than thread these
through every converter signature, the dispatcher and the command line publish them here for the
duration of a run.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

__all__ = ('input_root', 'tool_path', 'using_input_root', 'using_tool_paths')

_input_root: ContextVar[Path | None] = ContextVar('input_root', default=None)
_tool_paths: ContextVar[Mapping[str, Path] | None] = ContextVar('tool_paths', default=None)


def input_root() -> Path | None:
    """
    Return the current source-tree root, or ``None`` if conversion is running outside a tree.

    Returns
    -------
    Path | None
        The root of the source tree being converted.
    """
    return _input_root.get()


@contextmanager
def using_input_root(root: Path) -> Iterator[None]:
    """
    Publish *root* as the source-tree root for the duration of the context.

    Parameters
    ----------
    root : Path
        The root to publish.

    Yields
    ------
    None
        Nothing; the value is read with :py:func:`input_root`.
    """
    token = _input_root.set(root)
    try:
        yield
    finally:
        _input_root.reset(token)


def tool_path(name: str) -> Path | None:
    """
    Return the user-specified path to a native helper tool, if any.

    Parameters
    ----------
    name : str
        The tool name (for example ``spvr2png``).

    Returns
    -------
    Path | None
        The explicit path, or ``None`` to fall back to ``PATH``.
    """
    paths = _tool_paths.get()
    return paths.get(name) if paths is not None else None


@contextmanager
def using_tool_paths(paths: Mapping[str, Path | None]) -> Iterator[None]:
    """
    Publish explicit native-tool paths for the duration of the context.

    Parameters
    ----------
    paths : Mapping[str, Path | None]
        Map of tool name to path; entries whose value is ``None`` are ignored.

    Yields
    ------
    None
        Nothing; the values are read with :py:func:`tool_path`.
    """
    token = _tool_paths.set({name: path for name, path in paths.items() if path is not None})
    try:
        yield
    finally:
        _tool_paths.reset(token)
