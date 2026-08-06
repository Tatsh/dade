"""EA UK "Lion" engine 32-bit name hash.

The engine identifies every asset/resource by a 32-bit, case-insensitive name hash
(stored as the ``.rpk`` ASET ``name_hash`` and as the on-disc ``asset<NNNN>_<hash>``
filename, and used in the structured-format name-hash fields). It is a classic
ELF/PJW-style multiplicative hash.

The algorithm was reverse-engineered from ``default.xex`` (``ComputeNameHash`` @
``0x825198B0``) and verified byte-exact against ground-truth ``(name, hash)`` pairs taken
from the unpacked ``.rpk`` manifests (e.g. ``Background01.xmap`` -> ``0x0FEDE6D1``). The
hash stops at the file extension (the engine passes ``'.'`` as the terminator), so it is
computed over the name *stem* only.
"""
from __future__ import annotations

import sys

__all__ = ('GROUND_TRUTH', 'name_hash')

_EXTENSION_SEPARATOR = 0x2E
"""ASCII ``'.'``, the terminator at which hashing stops.

:meta hide-value:
"""
_ASCII_UPPER_A = 0x41
"""ASCII ``'A'``, the lower bound of the upper-case fold range.

:meta hide-value:
"""
_ASCII_UPPER_Z = 0x5A
"""ASCII ``'Z'``, the upper bound of the upper-case fold range.

:meta hide-value:
"""


def name_hash(name: str, *, stop_at_extension: bool = True) -> int:
    """
    Compute the engine's 32-bit case-insensitive name hash.

    Parameters
    ----------
    name : str
        The asset name. Matching is case-insensitive (``A``-``Z`` are folded to lower case),
        exactly as the engine does.
    stop_at_extension : bool
        When :py:obj:`True` (the default and the engine's behaviour), hashing stops at the first
        ``'.'`` so the file extension is excluded.

    Returns
    -------
    int
        The 32-bit name hash.
    """
    h = 0
    for ch in name:
        c = ord(ch)
        if stop_at_extension and c == _EXTENSION_SEPARATOR:  # '.' terminator (extension).
            break
        if _ASCII_UPPER_A <= c <= _ASCII_UPPER_Z:  # 'A'-'Z' -> lower case.
            c += 0x20
        h = ((h & 0x0FFFFFFF) * 16 + c) & 0xFFFFFFFF
        top = h & 0xF0000000
        if top:
            h ^= top >> 24
        h &= ~top & 0xFFFFFFFF
    return h


#: Ground-truth ``(name, hash)`` pairs from unpacked ``.rpk`` manifests, used to verify the
#: algorithm matches the shipped data.
GROUND_TRUTH: tuple[tuple[str, int], ...] = (
    ('BtnAccept.xmap', 0x0479F5C4),
    ('Background01.xmap', 0x0FEDE6D1),
    ('Background02.xmap', 0x0FEDE6D2),
    ('xbox_a.xmap', 0x07E96E51),
    ('advance_card.xmap', 0x0FEE50C4),
    ('AdvanceRailroad.xmap', 0x0B878E44),
)

if __name__ == '__main__':
    for _name, _expected in GROUND_TRUTH:
        _got = name_hash(_name)
        if _got != _expected:
            _msg = f'{_name}: got {_got:08x} expected {_expected:08x}'
            raise SystemExit(_msg)
    sys.stdout.write(f'OK: {len(GROUND_TRUTH)} ground-truth name hashes verified\n')
