"""
The tune-package cipher.

Every entry of a ``.rb`` tune package is enciphered with the ``BFCodec`` Blowfish variant in
:py:mod:`dade.common.bfcodec`, the same one *pop'n rhythmin* and *jubeat plus* use. Only the key
differs.

There are two keys. Neither passphrase appears in the executable: each is stored as a byte array
with every byte reduced by its own index, so adding the index back recovers the passphrase, and its
MD5 is the sixteen-byte Blowfish key. The two recovered passphrases are
``Konami ReflecBeat For iOS.`` and ``Konami ReflecBeatplus.``.

A package does not record which key it was built with. ``MusicData +dataWithPath:ID:`` tries the
first, and falls back to the second when the ``info`` entry does not parse as a property list;
:py:func:`dade.rbplus.package.open_package` does the same.
"""
from __future__ import annotations

import functools
import hashlib

__all__ = ('DECODE_TYPE_COUNT', 'OBFUSCATED_KEYS', 'chart_key', 'chart_keys', 'deobfuscate',
           'key_for_passphrase', 'passphrase')

OBFUSCATED_KEYS = (
    bytes((0x4B, 0x6E, 0x6C, 0x5E, 0x69, 0x64, 0x1A, 0x4B, 0x5D, 0x5D, 0x62, 0x5A, 0x57, 0x35, 0x57,
           0x52, 0x64, 0x0F, 0x34, 0x5C, 0x5E, 0x0B, 0x53, 0x38, 0x3B, 0x15)),
    bytes((0x4B, 0x6E, 0x6C, 0x5E, 0x69, 0x64, 0x1A, 0x4B, 0x5D, 0x5D, 0x62, 0x5A, 0x57, 0x35, 0x57,
           0x52, 0x64, 0x5F, 0x5A, 0x62, 0x5F, 0x19)),
)
"""The two obfuscated key arrays, transcribed from the executable at ``0x2fcf50`` and ``0x2fcf6a``.

:meta hide-value:
"""

DECODE_TYPE_COUNT = len(OBFUSCATED_KEYS)
"""How many decode types exist. The loader rejects any index at or above this.

:meta hide-value:
"""


def deobfuscate(obfuscated: bytes) -> bytes:
    """
    Recover a passphrase from its obfuscated form.

    Each byte carries its own index subtracted, so adding the index back undoes it. The arithmetic
    wraps at a byte, as it does in the executable.

    Parameters
    ----------
    obfuscated : bytes
        The stored byte array.

    Returns
    -------
    bytes
        The passphrase.
    """
    return bytes((byte + index) & 0xFF for index, byte in enumerate(obfuscated))


def key_for_passphrase(passphrase: bytes) -> bytes:
    """
    Derive a Blowfish key from a passphrase.

    Parameters
    ----------
    passphrase : bytes
        The recovered passphrase.

    Returns
    -------
    bytes
        The sixteen-byte key.
    """
    return hashlib.md5(passphrase, usedforsecurity=False).digest()


@functools.cache
def passphrase(decode_type: int) -> bytes:
    """
    Recover the passphrase for one decode type.

    Parameters
    ----------
    decode_type : int
        The decode type, ``0`` or ``1``. Anything else raises :py:class:`IndexError`.

    Returns
    -------
    bytes
        The passphrase.
    """
    return deobfuscate(OBFUSCATED_KEYS[decode_type])


@functools.cache
def chart_key(decode_type: int) -> bytes:
    """
    Derive the Blowfish key for one decode type.

    Parameters
    ----------
    decode_type : int
        The decode type, ``0`` or ``1``. Anything else raises :py:class:`IndexError`.

    Returns
    -------
    bytes
        The sixteen-byte key.
    """
    return key_for_passphrase(passphrase(decode_type))


@functools.cache
def chart_keys() -> tuple[bytes, ...]:
    """
    List every key, in the order the loader tries them.

    Returns
    -------
    tuple[bytes, ...]
        The keys.
    """
    return tuple(chart_key(index) for index in range(DECODE_TYPE_COUNT))
