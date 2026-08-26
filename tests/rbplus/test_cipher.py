"""Tests for :py:mod:`dade.rbplus.cipher`."""
from __future__ import annotations

import hashlib

import pytest

from dade.rbplus.cipher import (
    DECODE_TYPE_COUNT,
    OBFUSCATED_KEYS,
    chart_key,
    chart_keys,
    deobfuscate,
    key_for_passphrase,
    passphrase,
)


def test_deobfuscate_recovers_the_two_passphrases() -> None:
    assert deobfuscate(OBFUSCATED_KEYS[0]) == b'Konami ReflecBeat For iOS.'
    assert deobfuscate(OBFUSCATED_KEYS[1]) == b'Konami ReflecBeatplus.'


def test_deobfuscate_wraps_at_a_byte() -> None:
    assert deobfuscate(bytes((0xFF, 0xFF))) == bytes((0xFF, 0x00))


def test_deobfuscate_of_nothing_is_nothing() -> None:
    assert deobfuscate(b'') == b''


def test_key_for_passphrase_is_the_md5() -> None:
    assert key_for_passphrase(b'abc') == hashlib.md5(b'abc', usedforsecurity=False).digest()


@pytest.mark.parametrize(('decode_type', 'expected'), [(0, '8f26f67751ad5494153a6c98fa85fe1f'),
                                                       (1, '404bd8026bec6466e532dbf02d0de5e4')])
def test_chart_key_matches_the_shipped_packages(decode_type: int, expected: str) -> None:
    assert chart_key(decode_type).hex() == expected


@pytest.mark.parametrize('decode_type', [0, 1])
def test_passphrase_derives_its_own_key(decode_type: int) -> None:
    assert key_for_passphrase(passphrase(decode_type)) == chart_key(decode_type)


def test_chart_keys_lists_every_key_in_order() -> None:
    assert chart_keys() == tuple(chart_key(index) for index in range(DECODE_TYPE_COUNT))
    assert len(chart_keys()) == DECODE_TYPE_COUNT == len(OBFUSCATED_KEYS)


def test_the_two_keys_differ() -> None:
    assert chart_key(0) != chart_key(1)


def test_an_unknown_decode_type_has_no_key() -> None:
    with pytest.raises(IndexError):
        passphrase(DECODE_TYPE_COUNT)
