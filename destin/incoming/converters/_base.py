"""Shared types and helpers for converters."""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from incoming_extractor.typing import ConvertFunction, MatchFunction

__all__ = ('ConversionError', 'Rule', 'UnsupportedFormatError', 'name_match', 'suffix_match')


class UnsupportedFormatError(Exception):
    """
    Raised by a converter that matches a file whose format is not yet decoded.

    The dispatcher treats this as a skip with a warning rather than a failure.
    """


class ConversionError(Exception):
    """Raised when a converter matches a file but fails to convert it."""


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
