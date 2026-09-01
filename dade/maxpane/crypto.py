"""
The seeded stream cipher guarding Max Payne's RAS archives and their wrapped blocks.

Transcribed from ``R_File::decryptWithSeed`` in ``rl.dll``. Each byte is rotated left by its index
modulo five, exclusive-ORed with a value derived from that index, then offset by the low byte of a
Wichmann-Hill generator stepped once per byte. The generator is written the way the original
compiler emitted it, because archive seeds are large enough that ``171 * seed`` overflows a signed
32-bit integer and the wrapped result is part of the key schedule.
"""
from __future__ import annotations

__all__ = ('decrypt', 'next_seed')

_MASK32 = 0xFFFFFFFF
_SIGN_BIT = 0x80000000
_WRAP = 0x100000000
_MAGIC = 0xB92143FB - _WRAP
"""Signed multiplier the compiler substituted for division by 177.

:meta hide-value:
"""
_MODULUS = 30269
"""Wichmann-Hill modulus, equal to ``171 * 177 + 2``.

:meta hide-value:
"""
_DIVISOR_SHIFT = 7
"""Right shift paired with :py:data:`_MAGIC` to complete the division.

:meta hide-value:
"""


def _signed(value: int) -> int:
    value &= _MASK32
    return value - _WRAP if value >= _SIGN_BIT else value


def next_seed(seed: int) -> int:
    """
    Advance the cipher's Wichmann-Hill generator by one step.

    Parameters
    ----------
    seed : int
        Current generator state.

    Returns
    -------
    int
        The next state, as a signed 32-bit integer.
    """
    state = _signed(seed)
    quotient = _signed((_MAGIC * state) >> 32)
    quotient = _signed(quotient + state)
    quotient = _signed(quotient >> _DIVISOR_SHIFT)
    quotient = _signed(quotient + ((quotient & _MASK32) >> 31))
    quotient = _signed(quotient * _MODULUS)
    scaled = _signed(_signed(state * 8) - state)
    scaled = _signed(state + _signed(scaled * 8))
    scaled = _signed(scaled + _signed(scaled * 2))
    return _signed(scaled - quotient)


def decrypt(data: bytes, seed: int) -> bytes:
    """
    Decrypt a block with the given seed.

    Parameters
    ----------
    data : bytes
        Ciphertext. The keystream always restarts at index zero, so callers must pass whole
        blocks rather than slices of one.
    seed : int
        Signed cipher seed. Zero is promoted to one.

    Returns
    -------
    bytes
        The plaintext, the same length as *data*.
    """
    if seed == 0:
        seed = 1
    out = bytearray(len(data))
    for index, byte in enumerate(data):
        rotation = index % 5
        rotated = ((byte << rotation) | (byte >> (8 - rotation))) & 0xFF if rotation else byte
        seed = next_seed(seed)
        out[index] = (((((index & 0xFF) + 3) & 0xFF) * 6 & 0xFF) ^ rotated) + (seed & 0xFF) & 0xFF
    return bytes(out)
