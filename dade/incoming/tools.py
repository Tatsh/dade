"""Location and invocation of the native helper tools."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import os
import subprocess as sp

from dade.common.tools import ToolNotFoundError, locate_tool

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('ToolNotFoundError', 'find_gdiextract', 'find_spvr2png', 'find_unshield',
           'run_gdiextract', 'run_unshield')

log = logging.getLogger(__name__)


def find_spvr2png(override: Path | None = None) -> Path:
    """
    Locate the ``spvr2png`` binary.

    Parameters
    ----------
    override : Path | None
        An explicit path that takes precedence over the context override and ``PATH``.

    Returns
    -------
    Path
        The resolved path to the binary.
    """
    return locate_tool('spvr2png', override)


def find_gdiextract(override: Path | None = None) -> Path:
    """
    Locate the ``gdiextract`` binary.

    Parameters
    ----------
    override : Path | None
        An explicit path that takes precedence over the context override and ``PATH``.

    Returns
    -------
    Path
        The resolved path to the binary.
    """
    return locate_tool('gdiextract', override)


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
        The ``DATA1.CAB`` file to unpack.
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


def run_gdiextract(gdi: Path, output_dir: Path) -> None:
    """
    Extract the file system from a Dreamcast GDI with ``gdiextract``.

    Parameters
    ----------
    gdi : Path
        The ``.gdi`` track index file.
    output_dir : Path
        The directory the contents are extracted to.
    """
    gdiextract = find_gdiextract()
    log.debug('Extracting `%s` to `%s`.', gdi, output_dir)
    sp.run((str(gdiextract), '-o', str(output_dir), str(gdi)), check=True, capture_output=True)
