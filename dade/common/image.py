"""Shared scalar pixel and palette primitives for the games' texture decoders."""
from __future__ import annotations

__all__ = ('double_ps2_alpha', 'expand5', 'expand6', 'ps2_clut_swizzle_index')


def double_ps2_alpha(alpha: int) -> int:
    """
    Scale a PS2 ``0..128`` alpha value to the full ``0..255`` range.

    Parameters
    ----------
    alpha : int
        The stored alpha value, where ``128`` means fully opaque.

    Returns
    -------
    int
        The doubled alpha, clamped to ``255``.
    """
    return min(255, alpha * 2)


def expand5(value: int) -> int:
    """
    Expand a 5-bit colour channel to 8 bits by replicating its top bits.

    Parameters
    ----------
    value : int
        The 5-bit channel value.

    Returns
    -------
    int
        The 8-bit channel value.
    """
    return (value << 3) | (value >> 2)


def expand6(value: int) -> int:
    """
    Expand a 6-bit colour channel to 8 bits by replicating its top bits.

    Parameters
    ----------
    value : int
        The 6-bit channel value.

    Returns
    -------
    int
        The 8-bit channel value.
    """
    return (value << 2) | (value >> 4)


def ps2_clut_swizzle_index(index: int) -> int:
    """
    Map a linear index to its PS2 8bpp CLUT storage slot.

    A PS2 8bpp CLUT stores palettes with index bits ``0x08`` and ``0x10`` swapped, so the linear
    index and the storage slot differ within each block of 32 entries.

    Parameters
    ----------
    index : int
        The linear palette index.

    Returns
    -------
    int
        The permuted storage index.
    """
    return (index & 0xE7) | ((index & 0x08) << 1) | ((index & 0x10) >> 1)
