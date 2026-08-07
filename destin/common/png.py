"""
PNG writers for truecolour and truecolour-with-alpha images.

Both writers delegate to :py:mod:`PIL`, which the package already depends on. A PNG is defined by
its decoded pixels rather than its exact byte stream, so re-encoding through Pillow preserves every
image while keeping this module a thin wrapper. ``format='PNG'`` is passed explicitly so the output
is a PNG regardless of the destination's file extension.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('write_rgb', 'write_rgba')

log = logging.getLogger(__name__)


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
    Image.frombytes('RGBA', (width, height), pixels).save(path, format='PNG')
    log.debug('Wrote `%s` (%dx%d).', path, width, height)
