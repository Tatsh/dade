"""
The ``BFCodec`` cipher pop'n rhythmin encrypts its data files with.

The cipher itself is :py:mod:`dade.common.bfcodec`, which *jubeat plus* shares; only the key
belongs to this game. Every file the game ships or downloads uses the same one: the MD5 of
:py:data:`KEY_PLAINTEXT`, which is what :py:func:`default_key` returns. The key is spelled in the
binary as ``key[i] + i``, so it is obfuscated rather than hidden. Purchased music uses the MD5 of
the device UUID instead, which is why :py:class:`BFCodec` takes an arbitrary key.
"""
from __future__ import annotations

import hashlib

from dade.common.bfcodec import (
    BLOWFISH_INIT_WORDS,
    DEFAULT_IV,
    BFCodec as CommonBFCodec,
    Blowfish,
)

__all__ = ('BLOWFISH_INIT_WORDS', 'DEFAULT_IV', 'KEY_PLAINTEXT', 'BFCodec', 'Blowfish', 'decipher',
           'default_key', 'encipher')

KEY_PLAINTEXT = b'Popn Orbit Note. xjr1300.'
"""Plaintext whose MD5 is the key every shipped and downloaded file uses.

:meta hide-value:
"""


def default_key() -> bytes:
    """
    Derive the key every shipped and downloaded file is encrypted with.

    Returns
    -------
    bytes
        The 16-byte MD5 of :py:data:`KEY_PLAINTEXT`.
    """
    return hashlib.md5(KEY_PLAINTEXT, usedforsecurity=False).digest()


class BFCodec(CommonBFCodec):
    """
    The shared codec, keyed with this game's key when none is given.

    Parameters
    ----------
    key : bytes | None
        The cipher key, defaulting to :py:func:`default_key`.
    iv : bytes
        The eight-byte initialisation vector, defaulting to
        :py:data:`dade.common.bfcodec.DEFAULT_IV`.
    """
    def __init__(self, key: bytes | None = None, iv: bytes = DEFAULT_IV) -> None:
        super().__init__(default_key() if key is None else key, iv)


def decipher(data: bytes, key: bytes | None = None) -> bytes:
    """
    Decipher one payload with a fresh codec.

    Parameters
    ----------
    data : bytes
        The ciphertext, trailer included.
    key : bytes | None
        The cipher key, defaulting to :py:func:`default_key`.

    Returns
    -------
    bytes
        The plaintext.
    """
    return BFCodec(key).decipher(data)


def encipher(data: bytes, key: bytes | None = None) -> bytes:
    """
    Encipher one payload with a fresh codec.

    Parameters
    ----------
    data : bytes
        The plaintext.
    key : bytes | None
        The cipher key, defaulting to :py:func:`default_key`.

    Returns
    -------
    bytes
        The ciphertext, trailer included.
    """
    return BFCodec(key).encipher(data)
