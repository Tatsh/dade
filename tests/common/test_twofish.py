from __future__ import annotations

import pytest

from destin.common.twofish import Twofish, cbc_decrypt, cbc_encrypt

# Official Twofish known-answer test vectors (key, plaintext is all zero, ciphertext).
_KAT = [
    ('00000000000000000000000000000000', '9F589F5CF6122C32B6BFEC2F2AE8C35A'),
    ('0123456789ABCDEFFEDCBA98765432100011223344556677', 'CFD1D2E5A9BE9CDF501F13B892BD2248'),
    ('0123456789ABCDEFFEDCBA987654321000112233445566778899AABBCCDDEEFF',
     '37527BE0052334B89F0CFCCAE87CFA20'),
]
_ZERO_IV = bytes(16)


@pytest.mark.parametrize(('key_hex', 'ciphertext_hex'), _KAT)
def test_twofish_known_answer(key_hex: str, ciphertext_hex: str) -> None:
    cipher = Twofish(bytes.fromhex(key_hex))
    assert cipher.encrypt(bytes(16)).hex().upper() == ciphertext_hex
    assert cipher.decrypt(bytes.fromhex(ciphertext_hex)) == bytes(16)


@pytest.mark.parametrize('key_length', [16, 24, 32])
def test_twofish_block_roundtrip(key_length: int) -> None:
    cipher = Twofish(bytes(range(key_length)))
    block = bytes(range(16, 32))
    assert cipher.decrypt(cipher.encrypt(block)) == block


@pytest.mark.parametrize('length', [16, 64, 256])
def test_cbc_roundtrip(length: int) -> None:
    cipher = Twofish(bytes(range(32)))
    iv = bytes(range(100, 116))
    data = bytes((i * 7) & 0xFF for i in range(length))
    assert cbc_decrypt(cipher, iv, cbc_encrypt(cipher, iv, data)) == data


def test_twofish_rejects_bad_key_length() -> None:
    with pytest.raises(ValueError, match='16, 24, or 32'):
        Twofish(bytes(20))


def test_twofish_rejects_bad_block() -> None:
    with pytest.raises(ValueError, match='block must be 16 bytes'):
        Twofish(bytes(16)).encrypt(bytes(15))


def test_cbc_rejects_unaligned() -> None:
    with pytest.raises(ValueError, match='multiple of 16'):
        cbc_encrypt(Twofish(bytes(16)), _ZERO_IV, bytes(17))
