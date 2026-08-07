"""
InstallBuilder password key derivation and page decryption.

The InstallBuilder password scheme (SHA-256 plus iterated Twofish-CBC) is implemented by
:py:func:`derive_key` / :py:func:`verify_password`, and :py:func:`decrypt_page` decrypts a single
encrypted cookfs page. The underlying :py:class:`~destin.common.twofish.Twofish` cipher and its CBC
helpers live in :py:mod:`destin.common.twofish` and are re-exported here for convenience.

References
----------
- Reference decryptor for the InstallBuilder password scheme: `extract-installbuilder.tcl
  <https://gist.github.com/zhangyoufu/b85496abe9d9301e2d422858330a471a>`_.
"""
from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING
import binascii
import lzma
import struct

from destin.common.compress import inflate
from destin.common.twofish import Twofish, cbc_decrypt, cbc_encrypt
from typing_extensions import assert_never

from .exceptions import DecryptionError
from .typing import PayloadInfo

if TYPE_CHECKING:
    from .typing import PageCompression

__all__ = ('Twofish', 'cbc_decrypt', 'cbc_encrypt', 'decrypt_page', 'derive_key',
           'parse_payload_info', 'verify_password')

_PAYLOAD_INFO_HEADER = struct.Struct('>I16s32s64s32s')
"""``installbuilder.payloadinfo`` header: times, IV, password key, encrypted key, and IV hash."""

_BLOCK_SIZE = 16
_ZERO_IV = bytes(_BLOCK_SIZE)
"""The all-zero IV used by InstallBuilder's two-argument (no-IV) Twofish-CBC calls."""
_PAYLOAD_IV_STEP = 64
"""Iteration step InstallBuilder uses when repeatedly decrypting the payload IV pool."""
_ENCRYPTED_PAGE_HEADER = struct.Struct('>IB')
"""Encrypted page prefix: big-endian CRC32 checksum then a one-byte IV-pool index."""
_DECRYPTED_PREFIX = 32
"""Bytes of random prefix prepended to the plaintext before the length-prefixed payload."""
_LENGTH_PREFIX = 4
"""Length field before the compressed stream, stripped along with the random prefix."""
_LZHAM_HEADER = 8
"""LZHAM stream prefix: a 4-byte big-endian uncompressed size then a 4-byte adler32."""
_LZHAM_DICT_SIZE_LOG2 = 26
"""Dictionary size (log2) that InstallBuilder's tcllzham uses when decompressing."""


def derive_key(password: bytes, password_key: bytes, iv: bytes, times: int) -> bytes:
    """
    Derive the payload key from a password (InstallBuilder scheme).

    The hash of the password is repeatedly Twofish-CBC-encrypted, with the IV carried over from
    each iteration to the next, then hashed again.

    Parameters
    ----------
    password : bytes
        The user-supplied password.
    password_key : bytes
        32-byte Twofish key from the payload header.
    iv : bytes
        16-byte initialisation vector from the payload header.
    times : int
        Number of iterations.

    Returns
    -------
    bytes
        The 32-byte derived key.
    """
    cipher = Twofish(password_key)
    digest = sha256(password).digest()
    current_iv = iv
    for _ in range(times):
        digest = cbc_encrypt(cipher, current_iv, digest)
        current_iv = digest[-_BLOCK_SIZE:]
    return sha256(digest).digest()


def parse_payload_info(data: bytes) -> PayloadInfo:
    """
    Parse the raw ``installbuilder.payloadinfo`` metadata into a
    :py:class:`~destin.bitrock.typing.PayloadInfo`.

    Parameters
    ----------
    data : bytes
        The raw metadata value.

    Returns
    -------
    PayloadInfo
        The parsed header.
    """  # noqa: D205
    times, iv, password_key, encrypted_key, ivs_hash = _PAYLOAD_INFO_HEADER.unpack_from(data)
    return PayloadInfo(times=times,
                       iv=iv,
                       password_key=password_key,
                       encrypted_key=encrypted_key,
                       payload_ivs_hash=ivs_hash,
                       encrypted_payload_ivs=data[_PAYLOAD_INFO_HEADER.size:])


def verify_password(password: bytes, info: PayloadInfo) -> tuple[bytes, bytes] | None:
    """
    Check a password against a payload header and recover the payload key and IV pool.

    Parameters
    ----------
    password : bytes
        The password to test.
    info : PayloadInfo
        The parsed payload header.

    Returns
    -------
    tuple[bytes, bytes] | None
        ``(payload_key, payload_ivs)`` when the password is correct, otherwise ``None``. The
        payload key decrypts the archive pages and ``payload_ivs`` is the pool of per-page IVs.
    """
    derived = Twofish(derive_key(password, info.password_key, info.iv, info.times))
    payload_key = cbc_decrypt(derived, _ZERO_IV, info.encrypted_key)[32:64]
    buffer = info.encrypted_payload_ivs
    cipher = Twofish(payload_key)
    for _ in range(0, info.times, _PAYLOAD_IV_STEP):
        buffer = cbc_decrypt(cipher, _ZERO_IV, buffer)
    payload_ivs = buffer[32:]
    if sha256(payload_ivs).digest() != info.payload_ivs_hash:
        return None
    return payload_key, payload_ivs


def _decompress_payload(data: bytes, algorithm: PageCompression) -> bytes:
    """
    Decompress a decrypted payload stream.

    Parameters
    ----------
    data : bytes
        The compressed stream.
    algorithm : PageCompression
        The compression algorithm.

    Returns
    -------
    bytes
        The decompressed bytes.

    Raises
    ------
    DecryptionError
        If ``algorithm`` is ``'lzham'`` and the optional ``pylzham`` package is not installed.
    """
    match algorithm:
        case 'zip':
            return inflate(data, mode='raw')
        case 'lzma':
            # A standard ``.lzma`` (alone) stream. A stateful decompressor is used so the trailing
            # block padding left by the CBC layer is ignored rather than treated as a short read.
            return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(data)
        case 'lzham':
            try:
                import lzham  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as e:
                msg = ('LZHAM-compressed installers require the optional "pylzham" package; '
                       'install it with `pip install pylzham`.')
                raise DecryptionError(msg) from e
            uncompressed_size = int.from_bytes(data[:_LENGTH_PREFIX], 'big')
            return bytes(
                lzham.decompress(data[_LZHAM_HEADER:],
                                 uncompressed_size,
                                 filters={'dict_size_log2': _LZHAM_DICT_SIZE_LOG2}))
        case _:  # pragma: no cover
            assert_never(algorithm)


def decrypt_page(body: bytes,
                 payload_key: bytes,
                 payload_ivs: bytes,
                 algorithm: PageCompression = 'zip') -> bytes:
    """
    Decrypt and decompress one encrypted cookfs page.

    The page body (the stored page with its leading compression-id byte already removed) is
    ``[CRC32][iv index][ciphertext]``. The ciphertext is Twofish-CBC-decrypted with an IV chosen
    from the pool, its CRC32 is checked, and the compressed stream after a fixed prefix is
    decompressed.

    Parameters
    ----------
    body : bytes
        The page body, without the cookfs compression-id byte.
    payload_key : bytes
        The 32-byte payload key from :py:func:`verify_password`.
    payload_ivs : bytes
        The IV pool from :py:func:`verify_password`.
    algorithm : PageCompression
        The compression the installer applied before encryption.

    Returns
    -------
    bytes
        The decompressed page contents.

    Raises
    ------
    DecryptionError
        If the CRC32 does not match (wrong password or corrupt data), or if ``algorithm`` is
        ``'lzham'`` and the optional ``pylzham`` package is not installed.
    """
    checksum, iv_index = _ENCRYPTED_PAGE_HEADER.unpack_from(body)
    ciphertext = body[_ENCRYPTED_PAGE_HEADER.size:]
    iv = payload_ivs[iv_index * _BLOCK_SIZE:(iv_index + 1) * _BLOCK_SIZE]
    plaintext = cbc_decrypt(Twofish(payload_key), iv, ciphertext)
    if binascii.crc32(plaintext) != checksum:
        msg = 'Encrypted page CRC mismatch (wrong password or corrupt data).'
        raise DecryptionError(msg)
    return _decompress_payload(plaintext[_DECRYPTED_PREFIX + _LENGTH_PREFIX:], algorithm)
