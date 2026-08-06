"""
Host-side candidate generators: word-mangling rules and a word combinator.

Passwords built from dictionary words (for example ``RandomGeneratedPassword``) are unreachable by
pure brute force but fall quickly to a dictionary attack. :py:func:`mangle` expands one word into
common variants, and :py:func:`combine` joins several dictionary words. Both yield ``bytes`` ready
for :py:func:`destin.bitrock.password_cracker.crack.crack`, which verifies them on the GPU or CPU.
"""
from __future__ import annotations

from itertools import product
from typing import TYPE_CHECKING, Literal

from typing_extensions import assert_never

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

__all__ = ('Rule', 'combine', 'mangle')

Rule = Literal['none', 'capitalize', 'upper', 'lower', 'leet', 'append_digits', 'append_years']
"""A single word-mangling transform applied by :py:func:`mangle`."""

_LEET = bytes.maketrans(b'aAeEiIoOsStT', b'@43310055771')
"""Substitution table for the ``leet`` rule."""
_DEFAULT_RULES: tuple[Rule, ...] = ('none', 'capitalize', 'upper', 'lower')
"""Rules applied when the caller does not name any."""
_APPENDED_DIGITS = tuple(str(n).encode() for n in range(10))
"""Single digits appended by the ``append_digits`` rule."""
_APPENDED_YEARS = tuple(str(year).encode() for year in range(1940, 2031))
"""Years appended by the ``append_years`` rule."""


def _apply(word: bytes, rule: Rule) -> Iterator[bytes]:
    """
    Yield the variants of ``word`` produced by a single rule.

    Parameters
    ----------
    word : bytes
        The base word.
    rule : Rule
        The transform to apply.

    Yields
    ------
    bytes
        Each variant. Most rules yield one value; the append rules yield several.
    """
    match rule:
        case 'none':
            yield word
        case 'capitalize':
            yield word.capitalize()
        case 'upper':
            yield word.upper()
        case 'lower':
            yield word.lower()
        case 'leet':
            yield word.translate(_LEET)
        case 'append_digits':
            for digit in _APPENDED_DIGITS:
                yield word + digit
        case 'append_years':
            for year in _APPENDED_YEARS:
                yield word + year
        case _:  # pragma: no cover
            assert_never(rule)


def mangle(words: Iterable[str | bytes], rules: Sequence[Rule] = _DEFAULT_RULES) -> Iterator[bytes]:
    """
    Expand each word into candidate variants using the named rules.

    Parameters
    ----------
    words : Iterable[str | bytes]
        The base words, for example lines from a wordlist.
    rules : Sequence[Rule]
        Transforms to apply to every word. Duplicate variants are suppressed per word.

    Yields
    ------
    bytes
        Each distinct candidate, base words first.
    """
    for word in words:
        base = word.encode() if isinstance(word, str) else word
        seen: set[bytes] = set()
        for rule in rules:
            for variant in _apply(base, rule):
                if variant not in seen:
                    seen.add(variant)
                    yield variant


def combine(words: Sequence[str | bytes],
            count: int = 2,
            *,
            rules: Sequence[Rule] | None = None,
            separator: bytes = b'') -> Iterator[bytes]:
    """
    Join ``count`` words from ``words`` into every ordered combination.

    Parameters
    ----------
    words : Sequence[str | bytes]
        The dictionary to draw from.
    count : int
        Number of words to concatenate per candidate.
    rules : Sequence[Rule] | None
        When given, each drawn word is first expanded by :py:func:`mangle` with these rules, so the
        combinations range over the mangled variants. When ``None`` the words are used verbatim.
    separator : bytes
        Bytes inserted between joined words.

    Yields
    ------
    bytes
        Each combined candidate.

    Raises
    ------
    ValueError
        If ``count`` is less than one.
    """
    if count < 1:
        msg = 'count must be at least 1.'
        raise ValueError(msg)
    pool: tuple[bytes, ...] = (tuple(mangle(words, rules)) if rules is not None else tuple(
        word.encode() if isinstance(word, str) else word for word in words))
    for combination in product(pool, repeat=count):
        yield separator.join(combination)
