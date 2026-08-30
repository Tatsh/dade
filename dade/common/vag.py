"""Sony PS-ADPCM (VAG) decoding shared by the PlayStation 2 game submodules."""
from __future__ import annotations

import array

__all__ = ('VAG_FRAME_SIZE', 'decode_vag_adpcm')

VAG_FRAME_SIZE = 16
"""Size in bytes of one PS-ADPCM frame.

:meta hide-value:
"""

_VAG_COEFFICIENTS = ((0, 0), (60, 0), (115, -52), (98, -55), (122, -60))
_VAG_END = 1
_VAG_END_MUTE = 7
_PCM_MIN = -32768
_PCM_MAX = 32767
_NIBBLE_SIGN = 8  # A 4-bit ADPCM sample of 8..15 is negative.
_NIBBLE_SPAN = 16


def decode_vag_adpcm(data: bytes, start: int = 0, max_bytes: int | None = None) -> array.array[int]:
    """
    Decode PS2 VAG-ADPCM into 16-bit mono PCM.

    Parameters
    ----------
    data : bytes
        The buffer containing VAG frames.
    start : int
        Byte offset of the first frame.
    max_bytes : int | None
        Stop after this many bytes (in addition to the end flag); ``None`` reads to the buffer end.

    Returns
    -------
    array.array[int]
        Signed 16-bit PCM samples.
    """
    hist1 = hist2 = 0
    out = array.array('h')
    end = len(data) if max_bytes is None else min(len(data), start + max_bytes)
    frame = start
    while frame + VAG_FRAME_SIZE <= end:
        predictor_shift = data[frame]
        shift = predictor_shift & 0xF
        predictor = predictor_shift >> 4
        if predictor >= len(_VAG_COEFFICIENTS):
            predictor = 0
        flag = data[frame + 1]
        if flag == _VAG_END_MUTE:
            break
        c0, c1 = _VAG_COEFFICIENTS[predictor]
        for nibble_byte in range(14):
            packed = data[frame + 2 + nibble_byte]
            for nibble in (packed & 0xF, packed >> 4):
                t = nibble - _NIBBLE_SPAN if nibble >= _NIBBLE_SIGN else nibble
                s = ((t << 12) >> shift) + ((hist1 * c0 + hist2 * c1) >> 6)
                s = _PCM_MIN if s < _PCM_MIN else min(s, _PCM_MAX)
                out.append(s)
                hist2 = hist1
                hist1 = s
        frame += VAG_FRAME_SIZE
        if flag == _VAG_END:
            break
    return out
