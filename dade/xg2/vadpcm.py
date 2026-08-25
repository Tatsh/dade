"""
Nintendo 64 VADPCM decoding, as used by both Extreme-G games.

Each nine-byte frame carries a control byte followed by thirty-two 4-bit residuals, decoding to
sixteen samples in two vectors of eight. The control byte's high nibble is a scaling shift and its
low nibble selects one of the codebook's predictors, each of which is ``order`` vectors of eight
coefficients stored contiguously.

Per vector the previous eight samples are run through the predictor, the scaled residual is
accumulated in Q11, and each residual is propagated forward through the last predictor vector
before the accumulator is shifted back down and clamped.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('FRAME_SIZE', 'SAMPLES_PER_FRAME', 'decode_vadpcm', 'find_table_base', 'read_codebook')

FRAME_SIZE = 9
"""Size of one encoded frame in bytes.

:meta hide-value:
"""
SAMPLES_PER_FRAME = 16
"""Number of samples one frame decodes to.

:meta hide-value:
"""
_MAX_SHIFT = 12
_SEARCH_LIMIT = 0x8000
_SEARCH_STEP = 0x10
_MIN_SAMPLE = -32768
_MAX_SAMPLE = 32767
_NIBBLE_SIGN = 7


def _clamp16(value: int) -> int:
    return _MIN_SAMPLE if value < _MIN_SAMPLE else min(value, _MAX_SAMPLE)


def decode_vadpcm(data: bytes, coefficients: Sequence[int], order: int, predictors: int) -> \
        list[int]:
    """
    Decode a VADPCM stream to 16-bit PCM.

    Parameters
    ----------
    data : bytes
        The encoded frames. A trailing partial frame is ignored.
    coefficients : collections.abc.Sequence[int]
        The codebook, laid out as ``predictors`` groups of ``order`` vectors of eight.
    order : int
        Predictor order.
    predictors : int
        Number of predictors in the codebook. An out-of-range selector falls back to the first.

    Returns
    -------
    list[int]
        Signed 16-bit samples.
    """
    def vector(predictor: int, index: int) -> Sequence[int]:
        base = (predictor * order + index) * 8
        return coefficients[base:base + 8]

    out: list[int] = []
    state = [0] * 8
    pos = 0
    while pos + FRAME_SIZE <= len(data):
        control = data[pos]
        scaling = control >> 4
        predictor = control & 0xF
        pos += 1
        if predictor >= predictors:
            predictor = 0
        for _ in range(2):
            accumulator = [0] * 8
            for k in range(order):
                sample = state[8 - order + k]
                previous = vector(predictor, k)
                for i in range(8):
                    accumulator[i] += sample * previous[i]
            residuals: list[int] = []
            for b in range(4):
                byte = data[pos + b]
                high, low = byte >> 4, byte & 0xF
                residuals.extend((high - 16 if high > _NIBBLE_SIGN else high,
                                  low - 16 if low > _NIBBLE_SIGN else low))
            pos += 4
            feedback = vector(predictor, order - 1)
            for k in range(8):
                residual = residuals[k] << scaling
                accumulator[k] += residual << 11
                for i in range(6 - k + 1):
                    accumulator[k + 1 + i] += residual * feedback[i]
            state = [_clamp16(accumulator[i] >> 11) for i in range(8)]
            out += state
    return out


def find_table_base(rom: bytes,
                    control: int,
                    sounds: Sequence[tuple[int, int]],
                    predictors: int = 4) -> int | None:
    """
    Locate the sample table embedded after a control bank's structures.

    The table is shared by every sound in the bank, so the correct base is the one at which all of
    them frame validly over their full length. A false base inside the structures fails on at
    least one sound.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    control : int
        Offset of the control bank.
    sounds : collections.abc.Sequence[tuple[int, int]]
        The offset and length of every sound, relative to the table base.
    predictors : int
        Number of predictors the codebook declares, used to reject impossible selectors.

    Returns
    -------
    int | None
        The table base, or ``None`` when no candidate validates.
    """
    def valid(base: int, offset: int, length: int) -> bool:
        end = base + offset + length
        if end > len(rom):
            return False
        data = rom[base + offset:end]
        for pos in range(0, len(data) - FRAME_SIZE, FRAME_SIZE):
            if (data[pos] >> 4) > _MAX_SHIFT or (data[pos] & 0xF) >= predictors:
                return False
        return len(data) > FRAME_SIZE

    for base in range(control, control + _SEARCH_LIMIT, _SEARCH_STEP):
        if all(valid(base, offset, length) for offset, length in sounds):
            return base
    return None


def read_codebook(rom: bytes, base: int, order: int, predictors: int) -> list[int]:
    """
    Read a VADPCM codebook.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    base : int
        Offset of the codebook header; the coefficients follow eight bytes later.
    order : int
        Predictor order.
    predictors : int
        Number of predictors.

    Returns
    -------
    list[int]
        The coefficients, as signed 16-bit values.
    """
    count = order * predictors * 8
    return [struct.unpack_from('>h', rom, base + 8 + k * 2)[0] for k in range(count)]
