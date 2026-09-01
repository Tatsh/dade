"""
The ``RA->`` and ``RC->`` block wrappers Remedy's ``rl`` library puts around stored data.

``RA->`` marks an LZSS-compressed block and ``RC->`` an encrypted one. Either may wrap the other,
so :py:func:`unwrap` peels layers until neither magic matches. Every member of the shipped archives
carries exactly one ``RA->`` layer.
"""
from __future__ import annotations

import struct

from dade.common.lz import decompress_lzss0

from .crypto import decrypt

__all__ = ('COMPRESSED_MAGIC', 'ENCRYPTED_MAGIC', 'RING_FILL', 'decompress', 'decrypt_block',
           'is_compressed', 'is_encrypted', 'unwrap')

COMPRESSED_MAGIC = b'RA->'
"""Magic introducing an LZSS-compressed block, from ``R_File::CMPHEADER``.

:meta hide-value:
"""
ENCRYPTED_MAGIC = b'RC->'
"""Magic introducing an encrypted block, from ``R_File::CRYPTHEADER``.

:meta hide-value:
"""
RING_FILL = 0x20
"""Byte Max Payne primes the LZSS ring buffer with.

:meta hide-value:
"""

_COMPRESSED_HEADER_SIZE = 12
_ENCRYPTED_HEADER_SIZE = 16


def is_compressed(data: bytes) -> bool:
    """
    Report whether *data* begins with a ``RA->`` block.

    Parameters
    ----------
    data : bytes
        Candidate block.

    Returns
    -------
    bool
        :py:obj:`True` when the magic matches.
    """
    return data[:4] == COMPRESSED_MAGIC


def is_encrypted(data: bytes) -> bool:
    """
    Report whether *data* begins with a ``RC->`` block.

    Parameters
    ----------
    data : bytes
        Candidate block.

    Returns
    -------
    bool
        :py:obj:`True` when the magic matches.
    """
    return data[:4] == ENCRYPTED_MAGIC


def decompress(data: bytes) -> bytes:
    """
    Decompress a ``RA->`` block.

    Parameters
    ----------
    data : bytes
        A block starting with :py:data:`COMPRESSED_MAGIC`, followed by the decompressed size and
        the packed size as unsigned 32-bit integers.

    Returns
    -------
    bytes
        The decompressed payload.

    Raises
    ------
    ValueError
        If *data* does not start with :py:data:`COMPRESSED_MAGIC`.
    """
    if not is_compressed(data):
        msg = f'Not a compressed block: {data[:4]!r}.'
        raise ValueError(msg)
    raw_size, _ = struct.unpack_from('<II', data, 4)
    return decompress_lzss0(data, _COMPRESSED_HEADER_SIZE, raw_size, fill=RING_FILL)[0]


def decrypt_block(data: bytes) -> bytes:
    """
    Decrypt a ``RC->`` block.

    Parameters
    ----------
    data : bytes
        A block starting with :py:data:`ENCRYPTED_MAGIC`, followed by the plaintext size, a
        reserved dword, and the signed seed, all 32 bits wide.

    Returns
    -------
    bytes
        The plaintext.

    Raises
    ------
    ValueError
        If *data* does not start with :py:data:`ENCRYPTED_MAGIC`.
    """
    if not is_encrypted(data):
        msg = f'Not an encrypted block: {data[:4]!r}.'
        raise ValueError(msg)
    size, _, seed = struct.unpack_from('<IIi', data, 4)
    return decrypt(data[_ENCRYPTED_HEADER_SIZE:_ENCRYPTED_HEADER_SIZE + size], seed)


def unwrap(data: bytes) -> tuple[bytes, tuple[str, ...]]:
    """
    Remove every ``RA->`` and ``RC->`` layer from a block.

    Parameters
    ----------
    data : bytes
        Possibly wrapped block.

    Returns
    -------
    tuple[bytes, tuple[str, ...]]
        The unwrapped payload and the layers removed, outermost first, each ``'lzss'`` or
        ``'crypt'``.
    """
    layers: list[str] = []
    while len(data) >= _COMPRESSED_HEADER_SIZE:
        # An encrypted block's header is the longer of the two, so a buffer that is long enough to
        # be a compressed one and starts with `RC->` is still too short to take apart.
        if is_encrypted(data):
            if len(data) < _ENCRYPTED_HEADER_SIZE:
                break
            data = decrypt_block(data)
            layers.append('crypt')
        elif is_compressed(data):
            data = decompress(data)
            layers.append('lzss')
        else:
            break
    return data, tuple(layers)
