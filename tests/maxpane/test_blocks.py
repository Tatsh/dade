from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.maxpane.blocks import (
    RING_FILL,
    decompress,
    decrypt_block,
    is_compressed,
    is_encrypted,
    unwrap,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _compressed(payload: bytes, make_lzss: Callable[[bytes], bytes]) -> bytes:
    stream = make_lzss(payload)
    return b'RA->' + struct.pack('<II', len(payload), len(stream)) + stream


def _encrypted(payload: bytes, seed: int, encrypt_ras: Callable[[bytes, int], bytes]) -> bytes:
    return b'RC->' + struct.pack('<IIi', len(payload), 0, seed) + encrypt_ras(payload, seed)


def test_is_compressed() -> None:
    assert is_compressed(b'RA->1234')
    assert not is_compressed(b'RC->1234')


def test_is_encrypted() -> None:
    assert is_encrypted(b'RC->1234')
    assert not is_encrypted(b'RA->1234')


def test_decompress(make_lzss: Callable[[bytes], bytes]) -> None:
    payload = b'Nothing to lose. ' * 9
    assert decompress(_compressed(payload, make_lzss)) == payload


def test_decompress_rejects_a_foreign_block() -> None:
    with pytest.raises(ValueError, match='Not a compressed block'):
        decompress(b'RC->' + bytes(16))


def test_decompress_primes_the_ring_with_spaces() -> None:
    # A match reaching back before any literal reads the primed ring, which is the only place the
    # fill byte is observable.
    stream = bytes((0xFE, 0x00, 0x00))
    block = b'RA->' + struct.pack('<II', 3, len(stream)) + stream
    assert set(decompress(block)) == {RING_FILL}


def test_decrypt_block(encrypt_ras: Callable[[bytes, int], bytes]) -> None:
    payload = b'a poem about a lightbulb'
    assert decrypt_block(_encrypted(payload, 0x2A, encrypt_ras)) == payload


def test_decrypt_block_rejects_a_foreign_block() -> None:
    with pytest.raises(ValueError, match='Not an encrypted block'):
        decrypt_block(b'RA->' + bytes(16))


def test_unwrap_peels_compression(make_lzss: Callable[[bytes], bytes]) -> None:
    payload = b'a bullet time' * 4
    data, layers = unwrap(_compressed(payload, make_lzss))
    assert data == payload
    assert layers == ('lzss',)


def test_unwrap_peels_encryption(encrypt_ras: Callable[[bytes, int], bytes]) -> None:
    payload = b'the flesh of fallen angels' * 2
    data, layers = unwrap(_encrypted(payload, 0x5150, encrypt_ras))
    assert data == payload
    assert layers == ('crypt',)


def test_unwrap_peels_both(make_lzss: Callable[[bytes], bytes],
                           encrypt_ras: Callable[[bytes, int], bytes]) -> None:
    payload = b'a graphic novel' * 8
    nested = _compressed(payload, make_lzss)
    data, layers = unwrap(_encrypted(nested, 0x99, encrypt_ras))
    assert data == payload
    assert layers == ('crypt', 'lzss')


def test_unwrap_leaves_plain_data_alone() -> None:
    assert unwrap(b'no wrapper here at all') == (b'no wrapper here at all', ())
