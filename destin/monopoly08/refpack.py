"""
EA RefPack / QFS decompressor.

A generic EA container compression used across RenderWare-era titles (not specific
to Monopoly 2008). Header: ``uint16`` signature whose second byte is ``0xFB``; the
first byte carries flags (``0x80`` = a compressed-size field precedes the
uncompressed-size field, ``0x01`` = 4-byte size fields instead of 3, big-endian).
The body is a stream of 2/3/4-byte copy opcodes, literal runs and an EOF marker.
"""
from __future__ import annotations

__all__ = ('decompress', 'is_refpack')

_MIN_HEADER_LEN = 2
"""Minimum number of bytes needed to inspect the RefPack signature.

:meta hide-value:
"""
_REFPACK_SIGNATURE = 0xFB
"""Second signature byte that identifies a RefPack / QFS stream.

:meta hide-value:
"""
_OP_SHORT_COPY_MAX = 0x80
"""Exclusive upper bound of the short-copy opcode range (``0x00``-``0x7F``).

:meta hide-value:
"""
_OP_MEDIUM_COPY_MAX = 0xC0
"""Exclusive upper bound of the medium-copy opcode range (``0x80``-``0xBF``).

:meta hide-value:
"""
_OP_LONG_COPY_MAX = 0xE0
"""Exclusive upper bound of the long-copy opcode range (``0xC0``-``0xDF``).

:meta hide-value:
"""
_OP_LITERAL_RUN_MAX = 0xFC
"""Exclusive upper bound of the literal-run opcode range (``0xE0``-``0xFB``).

:meta hide-value:
"""


def is_refpack(data: bytes) -> bool:
    """
    Return whether ``data`` looks like a RefPack stream.

    Parameters
    ----------
    data : bytes
        Candidate buffer.

    Returns
    -------
    bool
        ``True`` if the RefPack signature byte is present.
    """
    return len(data) >= _MIN_HEADER_LEN and data[1] == _REFPACK_SIGNATURE


def decompress(data: bytes) -> tuple[bytes, int]:
    """
    Decompress a RefPack / QFS stream.

    Parameters
    ----------
    data : bytes
        The complete compressed stream including its header.

    Returns
    -------
    tuple[bytes, int]
        The decompressed bytes and the uncompressed size declared in the header.

    Raises
    ------
    ValueError
        If the buffer does not start with a RefPack signature.
    """
    b0, b1 = data[0], data[1]
    if b1 != _REFPACK_SIGNATURE:
        msg = f'not refpack: sig={b0:02x}{b1:02x}'
        raise ValueError(msg)
    i = 2
    szlen = 4 if b0 & 0x01 else 3
    if b0 & 0x80:  # A compressed-size field precedes the real size; skip it.
        i += szlen
    outsize = int.from_bytes(data[i:i + szlen], 'big')
    i += szlen
    out = bytearray()
    n = len(data)
    while i < n:
        op = data[i]
        i += 1
        if op < _OP_SHORT_COPY_MAX:  # 0x00-0x7F: short copy.
            ref_lo = data[i]
            i += 1
            num_plain = op & 0x03
            out += data[i:i + num_plain]
            i += num_plain
            num_copy = ((op & 0x1C) >> 2) + 3
            ref = len(out) - (((op & 0x60) << 3) + ref_lo + 1)
        elif op < _OP_MEDIUM_COPY_MAX:  # 0x80-0xBF: medium copy.
            hi, lo = data[i], data[i + 1]
            i += 2
            num_plain = (hi >> 6) & 0x03
            out += data[i:i + num_plain]
            i += num_plain
            num_copy = (op & 0x3F) + 4
            ref = len(out) - (((hi & 0x3F) << 8) + lo + 1)
        elif op < _OP_LONG_COPY_MAX:  # 0xC0-0xDF: long copy.
            b_1, b_2, b_3 = data[i], data[i + 1], data[i + 2]
            i += 3
            num_plain = op & 0x03
            out += data[i:i + num_plain]
            i += num_plain
            num_copy = ((op & 0x0C) << 6) + b_3 + 5
            ref = len(out) - (((op & 0x10) << 12) + (b_1 << 8) + b_2 + 1)
        elif op < _OP_LITERAL_RUN_MAX:  # 0xE0-0xFB: literal run.
            num_plain = ((op & 0x1F) << 2) + 4
            out += data[i:i + num_plain]
            i += num_plain
            continue
        else:  # 0xFC-0xFF: EOF (with a trailing short literal run).
            num_plain = op & 0x03
            out += data[i:i + num_plain]
            i += num_plain
            break
        for _ in range(num_copy):  # Overlapping back-reference copy.
            out.append(out[ref])
            ref += 1
    return bytes(out), outsize
