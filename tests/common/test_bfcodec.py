"""Tests for :py:mod:`dade.common.bfcodec`."""
from __future__ import annotations

import hashlib
import struct

import pytest

from dade.common.bfcodec import DEFAULT_IV, BFCodec, Blowfish, decipher, encipher

_KEY = hashlib.md5(b'example passphrase', usedforsecurity=False).digest()


def test_a_round_trip() -> None:
    assert decipher(encipher(b'the plaintext', _KEY), _KEY) == b'the plaintext'


def test_the_free_functions_match_the_class() -> None:
    assert encipher(b'payload', _KEY) == BFCodec(_KEY).encipher(b'payload')


@pytest.mark.parametrize('payload', [b'', b'\0', b'x' * 8, b'y' * 9, bytes(range(256))])
def test_every_length_survives_a_round_trip(payload: bytes) -> None:
    assert decipher(encipher(payload, _KEY), _KEY) == payload


def test_a_different_key_gives_different_ciphertext() -> None:
    other = hashlib.md5(b'another passphrase', usedforsecurity=False).digest()
    assert encipher(b'payload', _KEY) != encipher(b'payload', other)


def test_the_body_is_cbc_chained_from_the_default_iv() -> None:
    # Rebuilt from the block cipher and the documented chaining rather than from the codec, so a
    # chain that stopped feeding itself would still round-trip but would not match this.
    payload = b'two whole blocks'
    cipher = Blowfish(_KEY)
    left = int.from_bytes(DEFAULT_IV[:4], 'big')
    right = int.from_bytes(DEFAULT_IV[4:], 'big')
    expected = bytearray()
    for offset in range(0, len(payload), 8):
        left, right = cipher.encrypt_block(
            int.from_bytes(payload[offset:offset + 4], 'big') ^ left,
            int.from_bytes(payload[offset + 4:offset + 8], 'big') ^ right)
        expected += left.to_bytes(4, 'big') + right.to_bytes(4, 'big')
    assert encipher(payload, _KEY) == bytes(expected) + struct.pack('>II', 16, 16)


def test_a_repeated_block_does_not_repeat_in_the_ciphertext() -> None:
    ciphertext = encipher(b'\xa5' * 24, _KEY)
    assert len({ciphertext[offset:offset + 8] for offset in range(0, 24, 8)}) == 3


@pytest.mark.parametrize(('length', 'padded'), [(0, 0), (1, 8), (7, 8), (8, 8), (9, 16)])
def test_the_trailer_records_both_lengths(length: int, padded: int) -> None:
    ciphertext = encipher(b'z' * length, _KEY)
    assert len(ciphertext) == padded + 8
    assert ciphertext[-8:] == struct.pack('>II', length, padded)


def test_the_padding_is_zero_filled() -> None:
    # The trailer truncates, so the fill only shows through a codec that is told the block is whole.
    assert decipher(encipher(b'abc', _KEY)[:-8] + struct.pack('>II', 8, 8),
                    _KEY) == b'abc\0\0\0\0\0'


def test_an_explicit_iv_changes_the_whole_body() -> None:
    payload = b'two whole blocks'
    other = BFCodec(_KEY, bytes(range(1, 9))).encipher(payload)
    default = BFCodec(_KEY, DEFAULT_IV).encipher(payload)
    assert default == encipher(payload, _KEY)
    assert all(a != b for a, b in zip(default[:16], other[:16], strict=True))
