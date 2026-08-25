"""
Pure-Python LZO decoders matching the ones compiled into ``i76.exe``.

Two variants exist, selected by the ZFS record flags field at entry offset ``0x20``:

- Bit 1 selects the ``FUN_004babd8`` variant: M1 base ``0x800``, M2 offset
  ``((t >> 2) & 7) + (b << 3)``, and M2 length ``(t >> 5) + 1``.
- Bit 2 selects the ``FUN_004baa00`` variant: M1 base ``0x400``, M2 offset
  ``((t >> 2) & 3) + (b << 2)``, and M2 length ``(t >> 4) - 1``.

The M3, M4, literal, and inline-M1 cases are identical between the two. The decompressed size is
``flags >> 8``, which is only an allocation hint; the end-of-stream marker is authoritative. A
record whose flags have neither bit set is stored uncompressed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ('decompress_record', 'lzo1x_decompress', 'lzo1y_decompress')

log = logging.getLogger(__name__)

_LZO1X_FLAG = 2
"""Record flag bit selecting the LZO1X variant.

:meta hide-value:
"""
_LZO1Y_FLAG = 4
"""Record flag bit selecting the LZO1Y variant.

:meta hide-value:
"""
_LITERAL_TOKEN_MIN = 17
"""Tokens above this begin the stream with a plain literal copy.

:meta hide-value:
"""
_MATCH_TOKEN_MIN = 16
"""Tokens below this encode a literal run or an M1 match rather than a longer match.

:meta hide-value:
"""
_M2_TOKEN_MIN = 64
"""Lowest token value encoding an M2 match.

:meta hide-value:
"""
_M3_TOKEN_MIN = 32
"""Lowest token value encoding an M3 match.

:meta hide-value:
"""


# The branch and statement counts mirror the original routine's control flow one for one.
# Splitting the state machine up would risk changing the decoded bytes, so the limits are waived.
def _decompress(  # noqa: C901, PLR0912, PLR0915
        src: bytes, dst_len: int, m1_base: int, m2_offset_mask: int, m2_offset_shift: int,
        m2_length: Callable[[int], int]) -> bytes:
    """
    Run the shared LZO state machine over ``src``.

    Parameters
    ----------
    src : bytes
        The compressed record.
    dst_len : int
        Allocation hint for the output buffer.
    m1_base : int
        Base offset added to post-literal-run M1 back-references.
    m2_offset_mask : int
        Mask applied to the M2 back-reference offset taken from the token.
    m2_offset_shift : int
        Left shift applied to the M2 back-reference offset's high byte.
    m2_length : Callable[[int], int]
        Derives the M2 match length from the token.

    Returns
    -------
    bytes
        The decompressed record, truncated to the number of bytes actually produced.
    """
    out = bytearray(dst_len)
    op = 0
    ip = 0

    def copy_literal(count: int) -> None:
        nonlocal ip, op
        out[op:op + count] = src[ip:ip + count]
        ip += count
        op += count

    def copy_match(match: int, length: int) -> None:
        nonlocal op
        if op - match >= length:  # Non-overlapping fast path.
            out[op:op + length] = out[match:match + length]
            op += length
        else:
            for _ in range(length):
                out[op] = out[match]
                op += 1
                match += 1

    def copy_literal_run(token: int) -> None:
        # A token below 16 introduces a literal run of ``token + 3`` bytes, or a long run
        # encoded with 0x00 continuation bytes.
        nonlocal ip
        if token == 0:
            token = 15
            while src[ip] == 0:
                token += 255
                ip += 1
            token += src[ip]
            ip += 1
        copy_literal(token + 3)

    # The states mirror the labels in the original routines: 'LM' literal-or-match, 'POST'
    # post-literal-run, 'M' match, and 'DONE' match-done.
    t = src[ip]
    ip += 1
    if t > _LITERAL_TOKEN_MIN:
        copy_literal(t - 17)
        t = src[ip]
        ip += 1
        state = 'POST'
    elif t < _MATCH_TOKEN_MIN:
        copy_literal_run(t)
        t = src[ip]
        ip += 1
        state = 'POST'
    else:  # 16 and 17 fall straight through to a match.
        state = 'M'

    while True:
        if state == 'LM':
            if t < _MATCH_TOKEN_MIN:
                copy_literal_run(t)
                t = src[ip]
                ip += 1
                state = 'POST'
                continue
            state = 'M'
        if state == 'POST':
            if t < _MATCH_TOKEN_MIN:  # Post-literal-run M1: three bytes against the large base.
                match = op - (1 + m1_base) - (t >> 2) - (src[ip] << 2)
                ip += 1
                copy_match(match, 3)
                state = 'DONE'
            else:
                state = 'M'
        if state == 'M':
            if t < _MATCH_TOKEN_MIN:  # Inline M1: two bytes against base 1.
                match = op - 1 - (t >> 2) - (src[ip] << 2)
                ip += 1
                copy_match(match, 2)
            elif t >= _M2_TOKEN_MIN:  # M2.
                length = m2_length(t)
                match = op - 1 - ((t >> 2) & m2_offset_mask) - (src[ip] << m2_offset_shift)
                ip += 1
                copy_match(match, length)
            elif t >= _M3_TOKEN_MIN:  # M3.
                length = t & 31
                if length == 0:
                    length = 31
                    while src[ip] == 0:
                        length += 255
                        ip += 1
                    length += src[ip]
                    ip += 1
                length += 2
                value = src[ip] | (src[ip + 1] << 8)
                ip += 2
                copy_match(op - 1 - (value >> 2), length)
            else:  # Tokens 16 to 31 are M4.
                length = t & 7
                if length == 0:
                    length = 7
                    while src[ip] == 0:
                        length += 255
                        ip += 1
                    length += src[ip]
                    ip += 1
                length += 2
                value = src[ip] | (src[ip + 1] << 8)
                ip += 2
                offset = ((t & 8) << 11) | (value >> 2)
                if offset == 0:
                    break  # End-of-stream marker.
                copy_match(op - 0x4000 - offset, length)
            state = 'DONE'
        # The remaining state is 'DONE'.
        trailing = src[ip - 2] & 3
        if trailing:
            copy_literal(trailing)
            t = src[ip]
            ip += 1
            state = 'M'  # A short trailing run is followed by an inline match.
        else:
            t = src[ip]
            ip += 1
            state = 'LM'

    return bytes(out[:op])


def lzo1x_decompress(src: bytes, dst_len: int) -> bytes:
    """
    Decompress a record encoded with the LZO1X variant.

    Parameters
    ----------
    src : bytes
        The compressed record.
    dst_len : int
        Allocation hint for the output buffer.

    Returns
    -------
    bytes
        The decompressed record.
    """
    return _decompress(src, dst_len, 0x800, 7, 3, lambda t: (t >> 5) + 1)


def lzo1y_decompress(src: bytes, dst_len: int) -> bytes:
    """
    Decompress a record encoded with the LZO1Y variant.

    Parameters
    ----------
    src : bytes
        The compressed record.
    dst_len : int
        Allocation hint for the output buffer.

    Returns
    -------
    bytes
        The decompressed record.
    """
    return _decompress(src, dst_len, 0x400, 3, 2, lambda t: (t >> 4) - 1)


def decompress_record(data: bytes, flags: int) -> bytes:
    """
    Decompress one ZFS record according to its flags field.

    Parameters
    ----------
    data : bytes
        The record's stored bytes.
    flags : int
        The record's flags field. Bit 1 selects LZO1X and bit 2 selects LZO1Y; when neither is
        set the record is stored uncompressed.

    Returns
    -------
    bytes
        The decompressed record, or ``data`` unchanged when the record is stored raw.
    """
    if flags & _LZO1X_FLAG:
        return lzo1x_decompress(data, flags >> 8)
    if flags & _LZO1Y_FLAG:
        return lzo1y_decompress(data, flags >> 8)
    return bytes(data)
