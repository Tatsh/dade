"""
Minimal PNG writer for truecolour images.

The games' own assets are palette-indexed, so the only encoder needed is an 8-bit RGB one. Writing
it directly against :py:mod:`zlib` keeps the output byte-identical to the original tools and avoids
pulling an imaging library into what is otherwise a pure parsing package. Games that already depend
on an imaging library use that instead; this writer exists for the ones that do not.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct
import zlib

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('encode_rgb', 'write_rgb')

log = logging.getLogger(__name__)

_SIGNATURE = b'\x89PNG\r\n\x1a\n'
"""The eight-byte PNG file signature.

:meta hide-value:
"""
_COMPRESSION_LEVEL = 9
"""Deflate level used for the image data.

:meta hide-value:
"""


def _chunk(tag: bytes, payload: bytes) -> bytes:
    """
    Frame one PNG chunk.

    Parameters
    ----------
    tag : bytes
        The four-byte chunk type.
    payload : bytes
        The chunk's data.

    Returns
    -------
    bytes
        The length-prefixed, CRC-suffixed chunk.
    """
    body = tag + payload
    return struct.pack('>I', len(payload)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)


def encode_rgb(width: int, height: int, rgb: bytes) -> bytes:
    """
    Encode an 8-bit RGB image as a PNG.

    Parameters
    ----------
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    rgb : bytes
        Row-major RGB triples, three bytes per pixel.

    Returns
    -------
    bytes
        The complete PNG file.
    """
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # Filter type 0 (None) for every scanline.
        raw.extend(rgb[y * width * 3:(y + 1) * width * 3])
    return (_SIGNATURE + _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            _chunk(b'IDAT', zlib.compress(bytes(raw), _COMPRESSION_LEVEL)) + _chunk(b'IEND', b''))


def write_rgb(path: Path, width: int, height: int, rgb: bytes) -> None:
    """
    Write an 8-bit RGB image to ``path`` as a PNG.

    Parameters
    ----------
    path : pathlib.Path
        Destination file.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    rgb : bytes
        Row-major RGB triples, three bytes per pixel.
    """
    path.write_bytes(encode_rgb(width, height, rgb))
    log.debug('Wrote `%s` (%dx%d).', path, width, height)
