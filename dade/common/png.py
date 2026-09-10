"""
PNG writers for truecolour and truecolour-with-alpha images.

Both writers delegate to :py:mod:`PIL`, already a dependency of the package. A PNG is defined by
its decoded pixels rather than its exact byte stream, and re-encoding through Pillow therefore
preserves every image while this module stays a thin wrapper. ``format='PNG'`` is passed explicitly
so the output is a PNG regardless of the destination's file extension.
"""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING
import logging

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('encode_rgba', 'write_rgb', 'write_rgba')

log = logging.getLogger(__name__)


def encode_rgba(width: int, height: int, pixels: bytes) -> bytes:
    """
    Encode 8-bit RGBA pixel data as a PNG in memory.

    This is what a glTF needs. An embedded image is a run of bytes in the binary chunk rather
    than a file on disk.

    Parameters
    ----------
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    pixels : bytes
        Row-major RGBA quads, four bytes per pixel.

    Returns
    -------
    bytes
        The encoded PNG.
    """
    buffer = BytesIO()
    Image.frombytes('RGBA', (width, height), pixels).save(buffer, format='PNG')
    return buffer.getvalue()


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
    Image.frombytes('RGB', (width, height), rgb).save(path, format='PNG')
    log.debug('Wrote `%s` (%dx%d).', path, width, height)


def write_rgba(path: Path, width: int, height: int, pixels: bytes) -> None:
    """
    Write 8-bit RGBA pixel data to ``path`` as a PNG.

    Parameters
    ----------
    path : pathlib.Path
        Destination file, whose parent must already exist.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    pixels : bytes
        Row-major RGBA quads, four bytes per pixel.
    """
    path.write_bytes(encode_rgba(width, height, pixels))
    log.debug('Wrote `%s` (%dx%d).', path, width, height)
