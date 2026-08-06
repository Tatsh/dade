"""
Binary NetPBM (PPM) writer.

The ``P6`` form is a three-line ASCII header followed by raw row-major RGB triples, which makes it
the cheapest way to hand a decoded framebuffer to an external tool such as ImageMagick without
pulling in an imaging library.
"""
from __future__ import annotations

__all__ = ('MAX_VALUE', 'ppm')

MAX_VALUE = 255
"""Maximum channel value written in the header, fixing the format at eight bits per channel.

:meta hide-value:
"""


def ppm(pixels: bytes, width: int, height: int) -> bytes:
    """
    Wrap packed RGB pixels in a binary PPM header.

    Parameters
    ----------
    pixels : bytes
        Row-major RGB triples, three bytes per pixel.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.

    Returns
    -------
    bytes
        A complete binary PPM image.
    """
    return f'P6\n{width} {height}\n{MAX_VALUE}\n'.encode() + pixels
