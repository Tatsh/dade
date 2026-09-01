"""
Location and invocation of the native helper tools the converters shell out to.

A tool is resolved from an explicit override first, then from the ambient override published by
:py:func:`dade.common.context.tool_path`, and finally from ``PATH``.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which
import logging
import os
import subprocess as sp

from dade.common.context import tool_path

__all__ = ('ToolNotFoundError', 'find_unshield', 'locate_tool', 'run_unshield')

log = logging.getLogger(__name__)


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


def find_unshield(override: Path | None = None) -> Path:
    """
    Locate the ``unshield`` binary.

    Parameters
    ----------
    override : Path | None
        An explicit path that takes precedence over the context override and ``PATH``.

    Returns
    -------
    Path
        The resolved path to the binary.
    """
    return locate_tool('unshield', override)


def run_unshield(cabinet: Path, output_dir: Path) -> None:
    """
    Extract an InstallShield cabinet with ``unshield``.

    Parameters
    ----------
    cabinet : Path
        The ``DATA1.CAB`` file to unpack. Its ``DATA1.HDR`` and ``DATA2.CAB`` siblings must sit
        beside it.
    output_dir : Path
        The directory the contents are extracted to.
    """
    unshield = find_unshield()
    env = dict(os.environ)
    lib_dir = unshield.parent.parent / 'lib'
    if lib_dir.is_dir():
        existing = env.get('LD_LIBRARY_PATH', '')
        env['LD_LIBRARY_PATH'] = f'{lib_dir}{os.pathsep}{existing}' if existing else str(lib_dir)
    log.debug('Extracting `%s` to `%s`.', cabinet, output_dir)
    sp.run((str(unshield), '-d', str(output_dir), 'x', str(cabinet)),
           check=True,
           env=env,
           capture_output=True)
