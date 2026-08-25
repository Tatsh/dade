"""
``IwHashString`` - Marmalade's string hash.

Marmalade hashes resource and section names with a case-insensitive djb2 variant (seed ``0x1505``,
multiplier ``0x21``). The original strings are usually *not* stored in serialised assets - only
these hashes - so matching a known name means hashing it and comparing.
"""
from __future__ import annotations

__all__ = ('iw_hash_string',)

_ASCII_CASE_BIT = 0x20
_ASCII_UPPER_A = 0x41
_ASCII_UPPER_Z = 0x5A
_MASK = 0xFFFFFFFF
_MULT = 0x21
_SEED = 0x1505


def iw_hash_string(value: str) -> int:
    """
    Compute the Marmalade ``IwHashString`` of *value*.

    The hash lower-cases ASCII ``A``-``Z`` first, so it is case-insensitive.

    Parameters
    ----------
    value : str
        Name to hash (e.g. ``'CIwModel'``, ``'ResGroupResources'``).

    Returns
    -------
    int
        32-bit unsigned hash.
    """
    h = _SEED
    for byte in value.encode():
        c = byte + _ASCII_CASE_BIT if _ASCII_UPPER_A <= byte <= _ASCII_UPPER_Z else byte
        h = (c + h * _MULT) & _MASK
    return h
