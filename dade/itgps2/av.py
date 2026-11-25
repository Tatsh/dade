"""
Reader for the ``.av`` streams of the music and the movies of In The Groove on the PS2.

A stream opens with seven 32-bit words (whether it has video, the channel count, the length in
sample frames, the sample rate, the width, the height, and the number of seek points in use) and a
table of 1024 seek points, each a sample frame and a file offset. The table is the same size
whatever number is in use, and the engine reads the first 8220 bytes as the header. The packets
follow, each a 16-byte header and a payload whose size the header opens with. A packet whose
second word is nought is signed 16-bit interleaved PCM, and any other packet is MPEG-1 video. The
audio is padded to a multiple of 16 bytes, and the length in the header is where it ends.
"""
from __future__ import annotations

from typing import NamedTuple
import struct

from dade.common.exceptions import InvalidFormatError

__all__ = ('AVHeader', 'AVStream', 'read_av')

_HEADER = struct.Struct('<7I')
_PACKET = struct.Struct('<4I')
_PACKETS = _HEADER.size + 1024 * 8


class AVHeader(NamedTuple):
    """The header of an ``.av`` stream."""

    has_video: bool
    """Whether the stream includes video packets."""
    channels: int
    """The number of audio channels."""
    frames: int
    """The length of the audio in sample frames."""
    sample_rate: int
    """The audio sample rate in hertz."""
    width: int
    """The width of the video in pixels. Nought without video."""
    height: int
    """The height of the video in pixels. Nought without video."""


class AVStream(NamedTuple):
    """An ``.av`` stream separated into its audio and its video."""

    header: AVHeader
    """The header of the stream."""
    audio: bytes
    """Signed 16-bit little-endian interleaved PCM."""
    video: bytes
    """An MPEG-1 video elementary stream. Empty without video."""


def read_av(data: bytes) -> AVStream:
    """
    Separate an ``.av`` stream into its audio and its video.

    Parameters
    ----------
    data : bytes
        The stream.

    Returns
    -------
    AVStream
        The header, the PCM, and the MPEG-1 video.

    Raises
    ------
    InvalidFormatError
        If the header or a packet runs past the end of the stream.
    """
    if len(data) < _HEADER.size:
        msg = 'The AV header is truncated.'
        raise InvalidFormatError(msg)
    has_video, channels, frames, rate, width, height, _ = _HEADER.unpack_from(data)
    header = AVHeader(bool(has_video), channels, frames, rate, width, height)
    audio = bytearray()
    video = bytearray()
    position = _PACKETS
    while position + _PACKET.size <= len(data):
        size, kind, _, _ = _PACKET.unpack_from(data, position)
        if size == 0:
            break
        position += _PACKET.size
        if position + size > len(data):
            msg = f'An AV packet at {position - _PACKET.size:#x} runs past the end of the stream.'
            raise InvalidFormatError(msg)
        (video if kind else audio).extend(data[position:position + size])
        position += size
    return AVStream(header, bytes(audio[:frames * channels * 2]), bytes(video))
