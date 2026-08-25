"""
Generic converter dispatch registry.

A game describes its conversions as an ordered tuple of :py:class:`Rule` objects, each pairing a
predicate with the function that handles a matching file. The first matching rule wins, so the
order of a game's tuple is the priority order and more specific rules must come first.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from dade.common.typing import ConvertFunction, MatchFunction

__all__ = ('Rule', 'name_match', 'suffix_match')


class Rule(NamedTuple):
    """A single converter registration."""

    name: str
    """Human-readable format name, used in log messages."""
    match: MatchFunction
    """Predicate deciding whether this rule handles a given path."""
    convert: ConvertFunction
    """Conversion function returning the paths written next to the original."""


def suffix_match(*suffixes: str) -> MatchFunction:
    """
    Build a predicate matching files by case-insensitive extension.

    Parameters
    ----------
    suffixes : str
        Extensions to match, each including the leading dot (for example ``.ppm``).

    Returns
    -------
    MatchFunction
        A predicate returning true when a path's suffix is one of *suffixes*.
    """
    lowered = tuple(s.lower() for s in suffixes)
    return lambda path: path.suffix.lower() in lowered


def name_match(*endings: str) -> MatchFunction:
    """
    Build a predicate matching files whose name ends with one of *endings*.

    This is used for compound suffixes such as ``_T.PVR`` or ``_ML.BIN`` that a plain extension
    match cannot express.

    Parameters
    ----------
    endings : str
        Case-insensitive name endings to match (for example ``_t.pvr``).

    Returns
    -------
    MatchFunction
        A predicate returning true when a path's name ends with one of *endings*.
    """
    lowered = tuple(e.lower() for e in endings)
    return lambda path: path.name.lower().endswith(lowered)
