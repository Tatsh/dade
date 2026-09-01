"""
Okumura LZSS decompressor, binary ``_0`` variant, as used by both Extreme-G games and Max Payne.

The ring buffer is 4096 bytes, the write cursor starts at ``0xFEE``, and control bytes are consumed
least-significant bit first. A set control bit introduces one literal byte; a clear bit introduces a
two-byte match where the offset is ``b0 | ((b1 & 0xF0) << 4)`` and the length is
``(b1 & 0x0F) + 3``. The stream carries no end marker: decoding stops once the caller's expected
output size is reached.

The Extreme-G PC port stores the identical byte stream, so this decoder serves both platforms
unchanged. Max Payne's ``RA->`` records use the same encoding but prime the ring buffer with spaces
rather than NULs, which only matters for matches that reach back before the first literal.
"""
from __future__ import annotations

__all__ = ('RING_SIZE', 'RING_START', 'decompress_lzss0')

RING_SIZE = 0x1000
"""Size of the LZSS ring buffer in bytes.

:meta hide-value:
"""
RING_START = 0xFEE
"""Initial ring buffer write cursor.

:meta hide-value:
"""
_RING_MASK = RING_SIZE - 1


def decompress_lzss0(data: bytes,
                     start: int,
                     decompressed_size: int,
                     *,
                     fill: int = 0) -> tuple[bytes, int]:
    """
    Decompress an LZSS ``_0`` stream.

    Parameters
    ----------
    data : bytes
        Buffer holding the compressed stream.
    start : int
        Offset of the first control byte within *data*.
    decompressed_size : int
        Number of bytes to produce. Decoding stops as soon as this many bytes exist, so the
        output may overshoot by up to fifteen bytes inside the final match and is truncated.
    fill : int
        Byte value used to prime the ring buffer. Extreme-G uses ``0``; Max Payne uses ``0x20``.

    Returns
    -------
    tuple[bytes, int]
        The decompressed bytes and the number of input bytes consumed. An
        :py:class:`IndexError` propagates if the stream runs past the end of *data*.
    """
    out = bytearray()
    ring = bytearray([fill]) * RING_SIZE
    cursor = RING_START
    control = 0
    pos = start
    while len(out) < decompressed_size:
        if (control & 0x100) == 0:
            control = data[pos] | 0xFF00
            pos += 1
        if control & 1:
            byte = data[pos]
            pos += 1
            ring[cursor] = byte
            cursor = (cursor + 1) & _RING_MASK
            out.append(byte)
        else:
            b0, b1 = data[pos], data[pos + 1]
            pos += 2
            offset = b0 | ((b1 & 0xF0) << 4)
            for i in range((b1 & 0x0F) + 3):
                value = ring[(offset + i) & _RING_MASK]
                ring[cursor] = value
                cursor = (cursor + 1) & _RING_MASK
                out.append(value)
        control >>= 1
    return bytes(out[:decompressed_size]), pos - start
