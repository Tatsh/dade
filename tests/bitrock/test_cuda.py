from __future__ import annotations

from hashlib import sha256

from destin.bitrock.crypto import Twofish, cbc_encrypt, derive_key
from destin.bitrock.typing import PayloadInfo
import pytest

cp = pytest.importorskip('cupy')


def _has_cuda_device() -> bool:
    try:
        return bool(cp.cuda.runtime.getDeviceCount() > 0)
    except cp.cuda.runtime.CUDARuntimeError:
        return False


pytestmark = pytest.mark.skipif(not _has_cuda_device(), reason='no CUDA device available')

_ZERO_IV = bytes(16)


def _synthetic_payload(password: bytes, times: int) -> PayloadInfo:
    password_key = bytes(range(32))
    iv = bytes(range(16))
    derived = Twofish(derive_key(password, password_key, iv, times))
    payload_key = bytes((i * 3) & 0xFF for i in range(32))
    payload_ivs = bytes((i * 5) & 0xFF for i in range(64))
    encrypted_key = cbc_encrypt(derived, _ZERO_IV, bytes(32) + payload_key)
    buffer = bytes(32) + payload_ivs
    for _ in range(0, times, 64):
        buffer = cbc_encrypt(Twofish(payload_key), _ZERO_IV, buffer)
    return PayloadInfo(times=times,
                       iv=iv,
                       password_key=password_key,
                       encrypted_key=encrypted_key,
                       payload_ivs_hash=sha256(payload_ivs).digest(),
                       encrypted_payload_ivs=buffer)


def test_cuda_finds_correct_password() -> None:
    from destin.bitrock.password_cracker.cuda import crack_cuda
    info = _synthetic_payload(b'ab', 2)
    assert crack_cuda(info, [b'no', b'ab', b'zz']) == b'ab'


def test_cuda_returns_none_when_exhausted() -> None:
    from destin.bitrock.password_cracker.cuda import crack_cuda
    info = _synthetic_payload(b'ab', 2)
    assert crack_cuda(info, [b'no', b'zz']) is None


@pytest.mark.parametrize('password', [b'a', b'secret', b'0123456789abcdef', b'p@ss'])
def test_cuda_matches_cpu_oracle(password: bytes) -> None:
    from destin.bitrock.crypto import verify_password
    from destin.bitrock.password_cracker.cuda import crack_cuda
    info = _synthetic_payload(password, 128)
    assert verify_password(password, info) is not None
    assert crack_cuda(info, [password]) == password


def test_cuda_rejects_oversized_candidate() -> None:
    from destin.bitrock.password_cracker.cuda import crack_cuda
    info = _synthetic_payload(b'ab', 2)
    with pytest.raises(ValueError, match='maximum'):
        crack_cuda(info, [b'x' * 65])
