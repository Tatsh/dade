"""Tests for :py:mod:`dade.ddrsplus.bfcodec`."""
from __future__ import annotations

import struct

import pytest

from dade.common.exceptions import InvalidFormatError
from dade.ddrsplus.bfcodec import GEN_KEY, KDEI_MAGIC, decipher, encipher


@pytest.mark.parametrize('payload', [b'', b'\0', b'x' * 8, b'y' * 9, bytes(range(256))])
def test_every_length_survives_a_round_trip(payload: bytes) -> None:
    assert decipher(encipher(payload)) == payload


def test_a_section_starts_with_the_magic() -> None:
    assert encipher(b'payload')[:4] == KDEI_MAGIC


def test_the_header_records_the_real_and_padded_sizes() -> None:
    real, padded = struct.unpack_from('>II', encipher(b'y' * 9), 4)
    assert (real, padded) == (9, 16)


def test_the_ciphertext_is_the_padded_length() -> None:
    assert len(encipher(b'y' * 9)) == 12 + 16


def test_a_different_key_gives_different_ciphertext() -> None:
    assert encipher(b'payload') != encipher(b'payload', bytes(16))


def test_a_wrong_key_does_not_raise_but_gives_rubbish() -> None:
    # The sizes live outside the ciphertext, so they cannot detect a wrong key.
    assert decipher(encipher(b'payload' * 4), bytes(16)) != b'payload' * 4


def test_a_short_section_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='Too short'):
        decipher(b'KDEI')


def test_a_section_without_the_magic_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='Not a KDEI section'):
        decipher(b'NOPE' + struct.pack('>II', 0, 0))


def test_a_size_disagreeing_with_the_payload_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='ciphertext bytes'):
        decipher(KDEI_MAGIC + struct.pack('>II', 8, 8) + bytes(16))


def test_a_padded_size_that_is_not_a_rounded_real_size_is_rejected() -> None:
    with pytest.raises(InvalidFormatError, match='rounded to a block'):
        decipher(KDEI_MAGIC + struct.pack('>II', 1, 16) + bytes(16))


def test_the_default_key_is_sixteen_bytes() -> None:
    assert len(GEN_KEY) == 16
