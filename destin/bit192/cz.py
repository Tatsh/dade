"""
``.cz`` decryption.

A ``.cz`` file is an ordinary Marmalade Derbh (DTRZ) archive wrapped in two layered repeating-key
XOR ciphers that bit192labs added on top of the SDK::

    plain[i] = cz[i] ^ KEY1[i % len(KEY1)] ^ KEY2[i % len(KEY2)]

The two keys are hard-coded constants lifted from the game binary (``FUN_4a06bd68``; key tables at
``0x4a18c3e0`` and ``0x4a18c3c8``). They are exposed here as :data:`KEY1` / :data:`KEY2` and used as
the defaults, but :func:`decrypt` accepts arbitrary keys so the same XOR scheme can be reused.

Decrypting a ``.cz`` yields the ``DTRZ`` bytes that :func:`marmalade.derbh.unpack` reads.
"""
from __future__ import annotations

__all__ = ('KEY1', 'KEY2', 'decrypt', 'looks_like_cz')

KEY1 = bytes((0xE9, 0xBD, 0xA8, 0x08, 0xE3, 0x9B, 0x59, 0x0C, 0xBC, 0xEF, 0xEF, 0x3C, 0xC2, 0x23,
              0xEA, 0x01, 0xFA, 0x59, 0x5B, 0xAA, 0x00, 0x00))
"""First XOR key (22 bytes), from the Tone Sphere binary at ``0x4a18c3e0``."""
KEY2 = bytes((0xAC, 0x3E, 0x11, 0x19, 0x20, 0x00, 0x10, 0x6A, 0x6D, 0x24, 0x5B, 0x4F, 0x99, 0x14,
              0xA3, 0x4E, 0x00, 0x00))
"""Second XOR key (18 bytes), from the Tone Sphere binary at ``0x4a18c3c8``."""

_DTRZ = b'DTRZ'


def decrypt(data: bytes, key1: bytes = KEY1, key2: bytes = KEY2) -> bytes:
    """
    Decrypt ``.cz`` bytes to the underlying ``DTRZ`` archive.

    The cipher is its own inverse (XOR), so this also re-encrypts.

    Parameters
    ----------
    data : bytes
        Encrypted ``.cz`` contents.
    key1 : bytes
        First repeating XOR key. Defaults to :data:`KEY1`.
    key2 : bytes
        Second repeating XOR key. Defaults to :data:`KEY2`.

    Returns
    -------
    bytes
        Decrypted contents (a ``DTRZ`` archive for valid Tone Sphere input).

    Raises
    ------
    ValueError
        If either key is empty.
    """
    n1, n2 = len(key1), len(key2)
    if not n1 or not n2:
        msg = 'XOR keys must be non-empty.'
        raise ValueError(msg)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ key1[i % n1] ^ key2[i % n2]
    return bytes(out)


def looks_like_cz(data: bytes, key1: bytes = KEY1, key2: bytes = KEY2) -> bool:
    """
    Return ``True`` if *data* decrypts to a ``DTRZ`` archive with the given keys.

    Parameters
    ----------
    data : bytes
        Candidate ``.cz`` contents.
    key1 : bytes
        First repeating XOR key. Defaults to :data:`KEY1`.
    key2 : bytes
        Second repeating XOR key. Defaults to :data:`KEY2`.

    Returns
    -------
    bool
        Whether the first four decrypted bytes are the ``DTRZ`` magic.
    """
    return decrypt(data[:4], key1, key2) == _DTRZ
