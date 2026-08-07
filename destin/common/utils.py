"""Small general-purpose helpers shared by the game submodules."""
from __future__ import annotations

__all__ = ('align_up', 'pluralize', 'safe_name')

_SAFE_PUNCTUATION = '._-+()'
"""Punctuation :py:func:`safe_name` keeps verbatim.

:meta hide-value:
"""


def align_up(value: int, alignment: int) -> int:
    """
    Round a value up to a multiple of an alignment.

    Parameters
    ----------
    value : int
        The value to round.
    alignment : int
        The alignment, which must be a power of two.

    Returns
    -------
    int
        The rounded value.
    """
    return (value + alignment - 1) & ~(alignment - 1)


def pluralize(count: int, noun: str) -> str:
    """
    Format a count with a regularly pluralised noun.

    Parameters
    ----------
    count : int
        The quantity.
    noun : str
        The singular form of the noun; an ``s`` is appended when *count* is not 1.

    Returns
    -------
    str
        The count followed by the noun, pluralised when *count* is not 1.
    """
    return f'{count} {noun}' if count == 1 else f'{count} {noun}s'


def safe_name(name: str, *, allow_spaces: bool = False) -> str:
    """
    Reduce an asset or object name to a single safe filename component.

    Any leading directory component is dropped, surrounding whitespace is stripped, and every
    character that is neither alphanumeric nor one of ``._-+()`` is replaced with an underscore.

    Parameters
    ----------
    name : str
        The raw object or sample name (may contain path separators).
    allow_spaces : bool
        Keep spaces verbatim instead of replacing them. Callers writing names into a
        whitespace-delimited format, such as Wavefront OBJ, must leave this off.

    Returns
    -------
    str
        A filename-safe basename, or ``object`` when nothing survives.
    """
    name = name.replace('\\', '/').split('/')[-1].strip()
    kept = f' {_SAFE_PUNCTUATION}' if allow_spaces else _SAFE_PUNCTUATION
    return ''.join(c if (c.isalnum() or c in kept) else '_' for c in name) or 'object'
