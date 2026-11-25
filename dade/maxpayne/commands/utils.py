"""Shared helpers for the Max Payne commands."""
from __future__ import annotations

from typing import TYPE_CHECKING
import re

import bascom

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('debug_option', 'find_path')

debug_option = bascom.debug_option({'dade.common': {}, 'dade.maxpayne': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""

_SEPARATORS = re.compile(r'[\\/]+')


def find_path(base: Path, relative: str) -> Path | None:
    """
    Resolve a path the game records, ignoring case.

    The game was written for Windows, and its scripts and models refer to files in whatever case
    the author typed. The second game's skins look in ``sharedtextures`` for a directory shipped as
    ``Sharedtextures``.

    Parameters
    ----------
    base : pathlib.Path
        The directory the path is relative to.
    relative : str
        The path as recorded, with either separator.

    Returns
    -------
    pathlib.Path | None
        The existing file or directory, or :py:obj:`None` when there is none.
    """
    current = base
    for part in _SEPARATORS.split(relative.strip()):
        if part in {'', '.'}:
            continue
        if part == '..':
            current = current.parent
            continue
        if (exact := current / part).exists():
            current = exact
            continue
        if not current.is_dir():
            return None
        lowered = part.lower()
        if (match := next((p for p in current.iterdir() if p.name.lower() == lowered),
                          None)) is None:
            return None
        current = match
    return current
