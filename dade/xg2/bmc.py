r"""
The ``BMC`` skeletal animation container in the Extreme-G XG2 ``mfs`` archive.

Every ``BMC`` blob in the ROM is named after a skeleton file: ``man2sk.asf`` thirteen times,
``ivask.bsf`` three times, and ``albeanosk.bs`` once. ``.asf`` is Acclaim's own Skeleton File
format, and Iva and Albeano are two of the game's riders, who also appear as ``bulk/data/iva.cmp``
and ``bulk/data/albeano.cmp`` in the Windows executable. These are motion clips, not sounds.

The layout is the magic ``BMC\\x80``, a twelve-byte NUL-padded name, the frame count twice, a
constant ``0x7800``, and a channel count that is always 67. That is the degrees of freedom of a
human skeleton, a root with six and the joints with one to three each. The payload is then one
length-prefixed curve per channel, each with one value per frame:

* ``[u16 length][s16 low][s16 high][frames x u8]``, eight-bit, rescaled from *low* to *high*;
* ``[u16 length][frames x s16]``, stored outright, when eight bits will not do.

Which one a record is follows from its length, and records are padded to an even boundary. The
final record records a length of zero and runs to the end of the payload, where the padding is
dropped.

Verified against the ROM. All seventeen clips parse to exactly 67 channels and consume every byte.
That is the decisive check. A wrong record size desynchronises the rest of the clip.
"""
from __future__ import annotations

from typing import NamedTuple
import struct

from dade.common.exceptions import SelfCheckFailed

__all__ = ('BMC_HEADER_SIZE', 'BMC_MAGIC', 'CHANNEL_HEADER_SIZE', 'BmcClip', 'parse_bmc')

BMC_MAGIC = b'BMC\x80'
"""Magic introducing a ``BMC`` clip.

:meta hide-value:
"""
BMC_HEADER_SIZE = 0x18
"""Size of the header preceding the channels.

:meta hide-value:
"""
CHANNEL_HEADER_SIZE = 6
"""Bytes an eight-bit channel spends on its length and its two bounds.

:meta hide-value:
"""

_QUANTISED_STEPS = 255.0
_NAME_SIZE = 12
_LENGTH_SIZE = 2


class BmcClip(NamedTuple):
    """A parsed ``BMC`` motion clip."""

    name: str
    """Skeleton the clip animates, as stored in the header."""
    frames: int
    """Number of frames, with one value per channel per frame."""
    channels: list[list[float]]
    """One curve per degree of freedom, each *frames* values long."""


def _channel(payload: bytes, at: int, size: int, frames: int) -> tuple[list[float], bool]:
    """
    Read one channel's curve.

    Returns
    -------
    tuple[list[float], bool]
        The values, and whether the record was well formed.
    """
    quantised = at + CHANNEL_HEADER_SIZE + frames <= at + size
    if quantised:
        if at + CHANNEL_HEADER_SIZE + frames > len(payload):  # pragma: no cover
            return [], False
        low, high = struct.unpack_from('>2h', payload, at + _LENGTH_SIZE)
        body = payload[at + CHANNEL_HEADER_SIZE:at + CHANNEL_HEADER_SIZE + frames]
        span = (high - low) / _QUANTISED_STEPS
        return [low + value * span for value in body], True
    if at + _LENGTH_SIZE + frames * 2 > len(payload):
        return [], False
    return [float(v) for v in struct.unpack_from(f'>{frames}h', payload, at + _LENGTH_SIZE)], True


def parse_bmc(blob: bytes) -> BmcClip | None:
    """
    Parse a ``BMC`` motion clip.

    Parameters
    ----------
    blob : bytes
        A decoded archive entry.

    Returns
    -------
    BmcClip | None
        The parsed clip, or :py:obj:`None` when *blob* is not one or its channels do not add up.
    """
    if blob[:4] != BMC_MAGIC:
        return None
    name = blob[4:4 + _NAME_SIZE].split(b'\x00')[0].decode('ascii', 'replace')
    frames, _repeat, _constant, _channels = struct.unpack_from('>4H', blob, 0x10)
    payload = blob[BMC_HEADER_SIZE:]
    if not frames:
        return BmcClip(name, 0, [])
    channels: list[list[float]] = []
    at = 0
    while at + _LENGTH_SIZE <= len(payload):
        length = struct.unpack_from('>H', payload, at)[0]
        size = (len(payload) - at) if length == 0 else length
        if size < CHANNEL_HEADER_SIZE or at + size > len(payload):
            return None
        values, ok = _channel(payload, at, size, frames)
        if not ok:
            return None
        channels.append(values)
        at += size
    return BmcClip(name, frames, channels)


_DEMO_FRAMES = 4
_DEMO_CHANNELS = 2
_DEMO_LOW = -100
_DEMO_HIGH = 100


def demo() -> None:
    """
    Check both channel encodings round-trip through the parser.

    Raises
    ------
    SelfCheckFailed
        If a clip built here does not read back the way it was written.
    """
    header = BMC_MAGIC + b'walk.asf'.ljust(_NAME_SIZE, b'\x00')
    header += struct.pack('>4H', _DEMO_FRAMES, _DEMO_FRAMES, 0x7800, _DEMO_CHANNELS)
    # An eight-bit channel spanning 0 to 255 maps its bytes straight onto that range.
    first = struct.pack('>H2h', CHANNEL_HEADER_SIZE + _DEMO_FRAMES, 0, 255)
    first += bytes((0, 85, 170, 255))
    # The last channel records a zero length and runs to the end.
    second = struct.pack('>H2h', 0, _DEMO_LOW, _DEMO_HIGH) + bytes((0, 128, 255, 0))
    clip = parse_bmc(header + first + second)
    if clip is None:
        msg = 'A well-formed clip did not parse.'
        raise SelfCheckFailed(msg)
    if clip.name != 'walk.asf':
        msg = f'Clip name is {clip.name!r}, expected walk.asf.'
        raise SelfCheckFailed(msg)
    if clip.frames != _DEMO_FRAMES:
        msg = f'Clip has {clip.frames} frames, expected {_DEMO_FRAMES}.'
        raise SelfCheckFailed(msg)
    if len(clip.channels) != _DEMO_CHANNELS:
        msg = f'Clip has {len(clip.channels)} channels, expected {_DEMO_CHANNELS}.'
        raise SelfCheckFailed(msg)
    if [round(v) for v in clip.channels[0]] != [0, 85, 170, 255]:
        msg = f'Eight-bit channel decoded as {clip.channels[0]}, expected 0, 85, 170, 255.'
        raise SelfCheckFailed(msg)
    if round(clip.channels[1][0]) != _DEMO_LOW:
        msg = f'Scaled channel starts at {clip.channels[1][0]}, expected {_DEMO_LOW}.'
        raise SelfCheckFailed(msg)
    if round(clip.channels[1][2]) != _DEMO_HIGH:
        msg = f'Scaled channel peaks at {clip.channels[1][2]}, expected {_DEMO_HIGH}.'
        raise SelfCheckFailed(msg)
    if parse_bmc(b'shaw' + b'\x00' * 32) is not None:
        msg = 'A file with the wrong magic parsed as a clip.'
        raise SelfCheckFailed(msg)
    print('bmc: both channel encodings decode.')  # ruff: ignore[print]


if __name__ == '__main__':
    demo()
