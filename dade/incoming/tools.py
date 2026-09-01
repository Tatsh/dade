"""Location and invocation of the native helper tools."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import subprocess as sp

from dade.common.tools import ToolNotFoundError, locate_tool

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('ToolNotFoundError', 'find_gdiextract', 'find_spvr2png', 'run_gdiextract')

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
