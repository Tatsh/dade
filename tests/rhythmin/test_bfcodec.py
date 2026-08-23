"""Tests for :py:mod:`destin.rhythmin.bfcodec`."""
from __future__ import annotations

import hashlib

import pytest

from destin.rhythmin.bfcodec import (
    BLOWFISH_INIT_WORDS,
    DEFAULT_IV,
    KEY_PLAINTEXT,
    BFCodec,
    Blowfish,
    decipher,
    default_key,
    encipher,
)

# Schneier's published Blowfish known-answer vectors, as key, plaintext, and ciphertext.
_VECTORS = (
    ('0000000000000000', '0000000000000000', '4EF997456198DD78'),
    ('FFFFFFFFFFFFFFFF', 'FFFFFFFFFFFFFFFF', '51866FD5B85ECB8A'),
    ('0123456789ABCDEF', '1111111111111111', '61F9C3802281B096'),
    ('FEDCBA9876543210', '0123456789ABCDEF', '0ACEAB0FC6A0A28D'),
)


def _standard_f(cipher: Blowfish, x: int) -> int:
    """Compute the textbook Blowfish F, for the deviation test."""
    boxes = cipher._s  # noqa: SLF001
    a, b, c, d = (x >> 24) & 0xFF, (x >> 16) & 0xFF, (x >> 8) & 0xFF, x & 0xFF
    return ((((boxes[0][a] + boxes[1][b]) & 0xFFFFFFFF) ^ boxes[2][c]) + boxes[3][d]) & 0xFFFFFFFF


def test_init_words_are_the_canonical_table() -> None:
    assert len(BLOWFISH_INIT_WORDS) == 18 + 4 * 256
    assert BLOWFISH_INIT_WORDS[0] == 0x243F6A88
    assert BLOWFISH_INIT_WORDS[18] == 0xD1310BA6


def test_default_key_is_the_digest_of_the_plaintext() -> None:
    assert default_key() == hashlib.md5(KEY_PLAINTEXT, usedforsecurity=False).digest()


@pytest.mark.parametrize(('key', 'plaintext', 'ciphertext'), _VECTORS)
def test_standard_f_reproduces_the_published_vectors(monkeypatch: pytest.MonkeyPatch, key: str,
                                                     plaintext: str, ciphertext: str) -> None:
    # The init boxes are the canonical ones, so swapping only F back to the textbook version must
    # turn this into standard Blowfish. That pins the single deviation precisely.
    monkeypatch.setattr(Blowfish, '_f', _standard_f)
    cipher = Blowfish(bytes.fromhex(key))
    block = bytes.fromhex(plaintext)
    left, right = cipher.encrypt_block(int.from_bytes(block[:4], 'big'),
                                       int.from_bytes(block[4:], 'big'))
    assert (left.to_bytes(4, 'big') + right.to_bytes(4, 'big')).hex().upper() == ciphertext


@pytest.mark.parametrize(('key', 'plaintext', 'ciphertext'), _VECTORS)
def test_the_game_f_is_not_standard_blowfish(key: str, plaintext: str, ciphertext: str) -> None:
    cipher = Blowfish(bytes.fromhex(key))
    block = bytes.fromhex(plaintext)
    left, right = cipher.encrypt_block(int.from_bytes(block[:4], 'big'),
                                       int.from_bytes(block[4:], 'big'))
    assert (left.to_bytes(4, 'big') + right.to_bytes(4, 'big')).hex().upper() != ciphertext


@pytest.mark.parametrize('length', [0, 1, 7, 8, 9, 16, 255, 4096])
def test_round_trip(length: int) -> None:
    plaintext = bytes((index * 7 + length) & 0xFF for index in range(length))
    ciphertext = encipher(plaintext)
    assert len(ciphertext) == ((length + 7) & ~7) + 8
    assert decipher(ciphertext) == plaintext


def test_block_encrypt_and_decrypt_are_inverse() -> None:
    cipher = Blowfish(b'a key of any length')
    assert cipher.decrypt_block(*cipher.encrypt_block(0x01234567, 0x89ABCDEF)) == (0x01234567,
                                                                                   0x89ABCDEF)


def test_a_wrong_key_yields_rubbish_rather_than_an_error() -> None:
    # The length trailer is stored in the clear, so it cannot detect a wrong key.
    recovered = decipher(encipher(b'hello world', b'right key'), b'wrong key')
    assert len(recovered) == len(b'hello world')
    assert recovered != b'hello world'


def test_decipher_rejects_a_truncated_payload() -> None:
    with pytest.raises(ValueError, match='Too short for the 8-byte length trailer'):
        decipher(b'short')


def test_decipher_rejects_a_corrupted_trailer() -> None:
    with pytest.raises(ValueError, match='Bad length trailer'):
        decipher(encipher(b'hello world')[:-1])


def test_blowfish_rejects_an_empty_key() -> None:
    with pytest.raises(ValueError, match='must not be empty'):
        Blowfish(b'')


def test_blowfish_rejects_a_short_init_table() -> None:
    with pytest.raises(ValueError, match='must hold 1042 words'):
        Blowfish(b'key', (1, 2, 3))


def test_codec_rejects_a_short_iv() -> None:
    with pytest.raises(ValueError, match='must be 8 bytes'):
        BFCodec(iv=b'short')


def test_codec_accepts_an_explicit_iv() -> None:
    payload = b'chained differently'
    assert BFCodec(iv=DEFAULT_IV).encipher(payload) != BFCodec(iv=bytes((1, 2, 3, 4, 5, 6, 7,
                                                                         8))).encipher(payload)
