"""Typing helpers shared by the game submodules."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict

__all__ = ('ConvertFunction', 'Endian', 'IconSysMeta', 'InvalidFormatError', 'MatchFunction')

Endian: TypeAlias = Literal['<', '>']
"""Struct byte-order prefix: ``'<'`` for little-endian, ``'>'`` for big-endian."""


class InvalidFormatError(ValueError):
    """Raised when a parser is given data that does not match its expected format."""


class IconSysMeta(TypedDict):
    """Decoded PS2 ``icon.sys`` save metadata."""

    background_transparency: int
    """Background transparency (``0..128``)."""
    icon_copy: str
    """Filename of the copy-action icon."""
    icon_delete: str
    """Filename of the delete-action icon."""
    icon_normal: str
    """Filename of the normal icon."""
    magic: str
    """Always ``'PS2D'``."""
    title: str
    """The save's display title (Shift-JIS decoded)."""
    title_line_break: int
    """Character offset at which the title wraps to a second line."""


# yapf cannot parse the PEP 695 `type` statement that UP040 prefers, so TypeAlias is used instead.
MatchFunction: TypeAlias = Callable[[Path], bool]
"""Predicate deciding whether a converter applies to a path."""
ConvertFunction: TypeAlias = Callable[[Path, Path], 'Path | tuple[Path, ...]']
"""Convert a source file, writing into the given destination directory and returning the outputs."""
