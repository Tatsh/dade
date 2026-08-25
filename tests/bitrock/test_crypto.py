from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING
import lzma
import struct
import sys
import zlib

import pytest

from dade.bitrock.crypto import (
    Twofish,
    cbc_decrypt,
    cbc_encrypt,
    decrypt_page,
    derive_key,
    verify_password,
)
from dade.bitrock.exceptions import DecryptionError
from dade.bitrock.typing import PayloadInfo

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture

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


def test_cbc_rejects_unaligned() -> None:
    cipher = Twofish(bytes(16))
    with pytest.raises(ValueError, match='multiple of 16'):
        cbc_encrypt(cipher, _ZERO_IV, bytes(17))


def test_twofish_rejects_bad_key_length() -> None:
    with pytest.raises(ValueError, match='16, 24, or 32'):
        Twofish(bytes(20))


def test_derive_key_is_deterministic() -> None:
    args = (b'secret', bytes(range(32)), bytes(range(16)), 4)
    assert derive_key(*args) == derive_key(*args)


def _synthetic_payload(password: bytes, times: int) -> tuple[PayloadInfo, bytes, bytes]:
    """Build a self-consistent header so the real verify path can be exercised cheaply."""
    password_key = bytes(range(32))
    iv = bytes(range(16))
    derived = Twofish(derive_key(password, password_key, iv, times))
    payload_key = bytes((i * 3) & 0xFF for i in range(32))
    payload_ivs = bytes((i * 5) & 0xFF for i in range(64))
    encrypted_key = cbc_encrypt(derived, _ZERO_IV, bytes(32) + payload_key)
    buffer = bytes(32) + payload_ivs
    for _ in range(0, times, 64):
        buffer = cbc_encrypt(Twofish(payload_key), _ZERO_IV, buffer)
    info = PayloadInfo(times=times,
                       iv=iv,
                       password_key=password_key,
                       encrypted_key=encrypted_key,
                       payload_ivs_hash=sha256(payload_ivs).digest(),
                       encrypted_payload_ivs=buffer)
    return info, payload_key, payload_ivs


def test_verify_password_accepts_correct() -> None:
    info, payload_key, payload_ivs = _synthetic_payload(b'correct horse', 2)
    assert verify_password(b'correct horse', info) == (payload_key, payload_ivs)


def test_verify_password_rejects_wrong() -> None:
    info, _, _ = _synthetic_payload(b'correct horse', 2)
    assert verify_password(b'wrong', info) is None


def test_twofish_encrypt_rejects_bad_block() -> None:
    with pytest.raises(ValueError, match='block must be 16 bytes'):
        Twofish(bytes(16)).encrypt(bytes(15))


def test_twofish_decrypt_rejects_bad_block() -> None:
    with pytest.raises(ValueError, match='block must be 16 bytes'):
        Twofish(bytes(16)).decrypt(bytes(17))


def test_cbc_decrypt_rejects_unaligned() -> None:
    with pytest.raises(ValueError, match='multiple of 16'):
        cbc_decrypt(Twofish(bytes(16)), _ZERO_IV, bytes(15))


_KEY = bytes(range(32))
_IVS = bytes(range(256)) * 16


def test_decrypt_page_zip(build_encrypted_page: Callable[..., bytes],
                          zlib_raw: Callable[[bytes], bytes]) -> None:
    body = build_encrypted_page(zlib_raw(b'zip content'), _KEY, _IVS, 3)
    assert decrypt_page(body, _KEY, _IVS, 'zip') == b'zip content'


def test_decrypt_page_lzma(build_encrypted_page: Callable[..., bytes]) -> None:
    payload = b'lzma content here'
    body = build_encrypted_page(lzma.compress(payload, format=lzma.FORMAT_ALONE), _KEY, _IVS)
    assert decrypt_page(body, _KEY, _IVS, 'lzma') == payload


def test_decrypt_page_lzham(build_encrypted_page: Callable[..., bytes]) -> None:
    lzham = pytest.importorskip('lzham')
    payload = b'lzham content here' * 4
    stream = lzham.compress(payload, filters={'dict_size_log2': 26})
    framed = struct.pack('>II', len(payload), zlib.adler32(payload)) + stream
    body = build_encrypted_page(framed, _KEY, _IVS)
    assert decrypt_page(body, _KEY, _IVS, 'lzham') == payload


def test_decrypt_page_crc_mismatch(build_encrypted_page: Callable[..., bytes],
                                   zlib_raw: Callable[[bytes], bytes]) -> None:
    body = bytearray(build_encrypted_page(zlib_raw(b'x'), _KEY, _IVS))
    body[0] ^= 0xFF  # Corrupt the stored CRC32.
    with pytest.raises(DecryptionError, match='CRC mismatch'):
        decrypt_page(bytes(body), _KEY, _IVS, 'zip')


def test_decrypt_page_lzham_missing(build_encrypted_page: Callable[..., bytes],
                                    zlib_raw: Callable[[bytes], bytes],
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, 'lzham', None)
    body = build_encrypted_page(zlib_raw(b'x'), _KEY, _IVS)
    with pytest.raises(DecryptionError, match='pylzham'):
        decrypt_page(body, _KEY, _IVS, 'lzham')


def test_decrypt_page_lzham_with_stub_module(build_encrypted_page: Callable[..., bytes],
                                             monkeypatch: pytest.MonkeyPatch,
                                             mocker: MockerFixture) -> None:
    payload = b'lzham content here' * 4
    stub = mocker.MagicMock()
    stub.decompress.return_value = payload
    monkeypatch.setitem(sys.modules, 'lzham', stub)
    framed = struct.pack('>II', len(payload), zlib.adler32(payload)) + b'compressed-stream'
    body = build_encrypted_page(framed, _KEY, _IVS)
    assert decrypt_page(body, _KEY, _IVS, 'lzham') == payload
    stub.decompress.assert_called_once()
    assert stub.decompress.call_args.args[1] == len(payload)
