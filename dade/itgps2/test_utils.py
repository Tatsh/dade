"""
Builders for synthetic In The Groove PS2 asset bytes.

These construct minimal but valid containers in memory, and the readers are exercised without
shipping copyrighted game data.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct
import zlib

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ('av_stream', 'pck_pack')

_HEADER = 0x88


def pck_pack(files: Mapping[str, bytes],
             *,
             compressed: Sequence[str] = (),
             itg2: bool = True,
             name: str = 'default') -> bytes:
    """
    Build a ``PCKF`` pack.

    Parameters
    ----------
    files : Mapping[str, bytes]
        The path and the contents of each file.
    compressed : Sequence[str]
        The paths stored as raw deflate streams. In The Groove 2 layout only.
    itg2 : bool
        Write the In The Groove 2 layout rather than the In The Groove one.
    name : str
        The pack name.

    Returns
    -------
    bytes
        The pack.
    """
    stored = {
        path: (zlib.compress(data)[2:-4] if path in compressed else data)
        for path, data in files.items()
    }
    record = 20 if itg2 else 12
    offset = _HEADER + sum(record + len(path.encode('latin-1')) for path in files)
    directory = bytearray()
    for path, data in stored.items():
        encoded = path.encode('latin-1')
        if itg2:
            directory += struct.pack('<5I', len(data), len(files[path]), offset, len(encoded),
                                     int(path in compressed))
        else:
            directory += struct.pack('<3I', len(data), offset, len(encoded))
        directory += encoded
        offset += len(data)
    header = b'PCKF' + name.encode().ljust(0x80, b'\0') + struct.pack('<I', len(files))
    return header + bytes(directory) + b''.join(stored.values())


def av_stream(audio: bytes,
              video: bytes = b'',
              *,
              channels: int = 2,
              sample_rate: int = 48000) -> bytes:
    """
    Build an ``.av`` stream with one audio packet and, when given, one video packet.

    Parameters
    ----------
    audio : bytes
        Signed 16-bit PCM. The packet is padded to a multiple of 16 bytes.
    video : bytes
        MPEG-1 video. Empty writes no video packet.
    channels : int
        The channel count.
    sample_rate : int
        The sample rate in hertz.

    Returns
    -------
    bytes
        The stream.
    """
    frames = len(audio) // (channels * 2)
    header = struct.pack('<7I', bool(video), channels, frames, sample_rate, 320 if video else 0, 240
                         if video else 0, 1) + struct.pack('<2I', 0, 0x201C).ljust(1024 * 8, b'\0')
    padded = audio.ljust(-(-len(audio) // 16) * 16, b'\0')
    packets = b''
    if video:
        packets += struct.pack('<4I', len(video), 1, 0, 0) + video
    packets += struct.pack('<4I', len(padded), 0, 0, 0) + padded
    return header + packets + bytes(16)
