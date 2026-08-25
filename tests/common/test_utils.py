from __future__ import annotations

import pytest

from dade.common.utils import align_up, pluralize, safe_name


@pytest.mark.parametrize(('value', 'alignment', 'expected'), [(0, 4, 0), (1, 4, 4), (4, 4, 4),
                                                              (5, 4, 8), (31, 32, 32), (32, 32, 32),
                                                              (33, 32, 64), (7, 1, 7)])
def test_align_up(value: int, alignment: int, expected: int) -> None:
    assert align_up(value, alignment) == expected


@pytest.mark.parametrize(('count', 'noun', 'expected'), [(0, 'file', '0 files'),
                                                         (1, 'file', '1 file'),
                                                         (2, 'file', '2 files')])
def test_pluralize(count: int, noun: str, expected: str) -> None:
    assert pluralize(count, noun) == expected


@pytest.mark.parametrize(('name', 'expected'), [('plain', 'plain'), ('dir/leaf.mesh', 'leaf.mesh'),
                                                ('dir\\leaf.mesh', 'leaf.mesh'),
                                                ('  padded  ', 'padded'),
                                                ('keep._-+()', 'keep._-+()'),
                                                ('drop:me*', 'drop_me_'), ('', 'object'),
                                                ('///', 'object')])
def test_safe_name(name: str, expected: str) -> None:
    assert safe_name(name) == expected


def test_safe_name_replaces_spaces_by_default() -> None:
    assert safe_name('two words') == 'two_words'


def test_safe_name_keeps_spaces_when_allowed() -> None:
    assert safe_name('two words', allow_spaces=True) == 'two words'
