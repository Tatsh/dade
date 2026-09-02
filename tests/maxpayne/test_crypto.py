from __future__ import annotations

from typing import TYPE_CHECKING

from dade.maxpayne.crypto import decrypt, next_seed

if TYPE_CHECKING:
    from collections.abc import Callable


def test_next_seed_matches_wichmann_hill() -> None:
    state = 4242
    for _ in range(64):
        expected = 171 * state - 30269 * (state // 177)
        state = next_seed(state)
        assert state == expected


def test_next_seed_wraps_like_the_original() -> None:
    assert next_seed(1239061428) == -13999155


def test_decrypt_round_trips(encrypt_ras: Callable[[bytes, int], bytes]) -> None:
    payload = bytes(range(256)) * 3
    assert decrypt(encrypt_ras(payload, 0x46AA8D54), 0x46AA8D54) == payload


def test_decrypt_promotes_a_zero_seed(encrypt_ras: Callable[[bytes, int], bytes]) -> None:
    payload = b'the sudden silence'
    assert decrypt(encrypt_ras(payload, 0), 0) == payload
    assert decrypt(encrypt_ras(payload, 1), 0) == payload


def test_decrypt_is_position_dependent(encrypt_ras: Callable[[bytes, int], bytes]) -> None:
    cipher = encrypt_ras(b'\x00' * 16, 99)
    assert len(set(cipher)) > 1


def test_decrypt_empty() -> None:
    assert decrypt(b'', 7) == b''
