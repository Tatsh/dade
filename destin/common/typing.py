"""Typing helpers shared by the game submodules."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

__all__ = ('ConvertFunction', 'MatchFunction')

# yapf cannot parse the PEP 695 `type` statement that UP040 prefers, so TypeAlias is used instead.
MatchFunction: TypeAlias = Callable[[Path], bool]
"""Predicate deciding whether a converter applies to a path."""
ConvertFunction: TypeAlias = Callable[[Path, Path], 'Path | tuple[Path, ...]']
"""Convert a source file, writing into the given destination directory and returning the outputs."""
