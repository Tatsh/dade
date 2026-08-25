"""
The ``KDEI`` framing *DDR S+* wraps the shared ``BFCodec`` cipher in.

The block cipher is :py:mod:`dade.common.bfcodec`, which *pop'n rhythmin* and *jubeat plus*
share: Blowfish with one deviation in its F function, which combines the S-box lookups as
``(S0[a] + S1[b]) ^ (S2[c] + S3[d])``. Only the framing and the key differ here.

Where the other two games append a length trailer, *DDR S+* puts a header in front::

    'KDEI'  |  uint32be real_size  |  uint32be padded_size  |  ciphertext[padded_size]

``padded_size`` is ``real_size`` rounded up to the eight-byte block. The whole ciphertext is
deciphered in CBC mode from the fixed initialisation vector and then truncated back to
``real_size``. Both sizes sit outside the ciphertext, so they catch a truncated file but say
nothing about whether the key was right; a wrong key yields plaintext-shaped rubbish that only the
caller's own parse rejects.

Everything here was read out of ``DDRSPlusUS/ARM-32-cpu0x9``, a 32-bit ARM Mach-O:
``C_CRYPT::cipher_init`` at 0x0008e97c loads the key and the vector, ``decipher_get_size`` at
0x0008e924 validates the header, and ``C_CRYPT::decipher`` at 0x0008e9f4 hands the payload to
``blowfish_cbc_decrypt``. The key is stored whole rather than derived, which makes it obfuscated
rather than hidden.
"""
from __future__ import annotations

import struct

from dade.common.bfcodec import DEFAULT_IV, Blowfish
from dade.common.exceptions import InvalidFormatError

__all__ = ('DEFAULT_IV', 'GEN_KEY', 'KDEI_MAGIC', 'Blowfish', 'decipher', 'encipher')

KDEI_MAGIC = b'KDEI'
"""Magic marking an enciphered section, checked by ``C_CRYPT::decipher_get_size``.

:meta hide-value:
"""
GEN_KEY = bytes.fromhex('C2549A5CF2E5123B9FE6DC09802A51CB')
"""The 16-byte key, read from 0x000c47c0 in the app binary.

``blowfish_cbc_init`` passes it through ``strlen``, which stops at the NUL byte that follows it, so
all sixteen bytes are used.

:meta hide-value:
"""

_BLOCK_SIZE = 8
_HEADER_SIZE = 12
_MASK32 = 0xFFFFFFFF


def _cbc_decrypt(cipher: Blowfish, data: bytes, iv: bytes) -> bytes:
    """
    Decipher a whole buffer in CBC mode.

    Parameters
    ----------
    cipher : dade.common.bfcodec.Blowfish
        The keyed block cipher.
    data : bytes
        The ciphertext, a whole number of blocks.
    iv : bytes
        The eight-byte initialisation vector.

    Returns
    -------
    bytes
        The plaintext, as long as the ciphertext.
    """
    chain_left, chain_right = struct.unpack('>II', iv)
    out = bytearray(len(data))
    for offset in range(0, len(data), _BLOCK_SIZE):
        cipher_left, cipher_right = struct.unpack_from('>II', data, offset)
        left, right = cipher.decrypt_block(cipher_left, cipher_right)
        struct.pack_into('>II', out, offset, (left ^ chain_left) & _MASK32,
                         (right ^ chain_right) & _MASK32)
        chain_left, chain_right = cipher_left, cipher_right
    return bytes(out)


def _cbc_encrypt(cipher: Blowfish, data: bytes, iv: bytes) -> bytes:
    """
    Encipher a whole buffer in CBC mode, the exact inverse of :py:func:`_cbc_decrypt`.

    Parameters
    ----------
    cipher : dade.common.bfcodec.Blowfish
        The keyed block cipher.
    data : bytes
        The plaintext, a whole number of blocks.
    iv : bytes
        The eight-byte initialisation vector.

    Returns
    -------
    bytes
        The ciphertext, as long as the plaintext.
    """
    chain_left, chain_right = struct.unpack('>II', iv)
    out = bytearray(len(data))
    for offset in range(0, len(data), _BLOCK_SIZE):
        plain_left, plain_right = struct.unpack_from('>II', data, offset)
        chain_left, chain_right = cipher.encrypt_block(plain_left ^ chain_left,
                                                       plain_right ^ chain_right)
        struct.pack_into('>II', out, offset, chain_left, chain_right)
    return bytes(out)


def decipher(data: bytes, key: bytes = GEN_KEY, iv: bytes = DEFAULT_IV) -> bytes:
    """
    Decipher one ``KDEI`` section.

    Parameters
    ----------
    data : bytes
        The section, magic and size header included.
    key : bytes
        The cipher key.
    iv : bytes
        The eight-byte initialisation vector.

    Returns
    -------
    bytes
        The plaintext, truncated to the size the header records.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        If the section is too short, lacks the magic, or its two sizes disagree with each other or
        with the payload. These are the checks ``C_CRYPT::decipher_get_size`` makes.
    """
    if len(data) < _HEADER_SIZE:
        msg = f'Too short for a {_HEADER_SIZE}-byte KDEI header: {len(data)} bytes.'
        raise InvalidFormatError(msg)
    if data[:4] != KDEI_MAGIC:
        msg = f'Not a KDEI section, the magic is {data[:4]!r}.'
        raise InvalidFormatError(msg)
    real_size, padded_size = struct.unpack_from('>II', data, 4)
    body = data[_HEADER_SIZE:]
    if padded_size != len(body):
        msg = f'The header claims {padded_size} ciphertext bytes but {len(body)} are present.'
        raise InvalidFormatError(msg)
    if padded_size != (real_size + _BLOCK_SIZE - 1) & ~(_BLOCK_SIZE - 1):
        msg = f'Padded size {padded_size} is not real size {real_size} rounded to a block.'
        raise InvalidFormatError(msg)
    return _cbc_decrypt(Blowfish(key), body, iv)[:real_size]


def encipher(data: bytes, key: bytes = GEN_KEY, iv: bytes = DEFAULT_IV) -> bytes:
    """
    Encipher a payload into a ``KDEI`` section, the exact inverse of :py:func:`decipher`.

    Parameters
    ----------
    data : bytes
        The plaintext, of any length.
    key : bytes
        The cipher key.
    iv : bytes
        The eight-byte initialisation vector.

    Returns
    -------
    bytes
        The section, magic and size header included.
    """
    padded = data.ljust((len(data) + _BLOCK_SIZE - 1) & ~(_BLOCK_SIZE - 1), b'\0')
    return (KDEI_MAGIC + struct.pack('>II', len(data), len(padded)) +
            _cbc_encrypt(Blowfish(key), padded, iv))
