"""
Location of the native helper tools the converters shell out to.

A tool is resolved from an explicit override first, then from the ambient override published by
:py:func:`dade.common.context.tool_path`, and finally from ``PATH``. Invocation stays with the
game that owns the tool, because the argument lists and environment handling are tool-specific.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which

from dade.common.context import tool_path

__all__ = ('ToolNotFoundError', 'locate_tool')


class ToolNotFoundError(Exception):
    """Raised when a required native helper tool cannot be located."""


def locate_tool(name: str, override: Path | None = None) -> Path:
    """
    Locate a native helper binary.

    Parameters
    ----------
    name : str
        The binary's name, as it would appear on ``PATH``.
    override : Path | None
        An explicit path that takes precedence over the context override and ``PATH``.

    Returns
    -------
    Path
        The resolved path to the binary.

    Raises
    ------
    ToolNotFoundError
        If an explicit path was given but is not a file, or the binary is not on ``PATH``.
    """
    if (candidate := override or tool_path(name)) is not None:
        if not candidate.is_file():
            msg = f'Specified path for `{name}` does not exist: {candidate}.'
            raise ToolNotFoundError(msg)
        return candidate
    if (found := which(name)) is not None:
        return Path(found)
    msg = f'Could not find `{name}`. Put it on PATH or pass `--{name}-path`.'
    raise ToolNotFoundError(msg)
