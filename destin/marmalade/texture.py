"""
``CIwTexture`` decoder.

A serialised texture carries a small header followed by ``pitch * height`` bytes of raw texel data.
The bytes-per-pixel is ``pitch // width`` (3 = RGB888, 4 = RGBA8888, 2 = RGB565, 1 = greyscale). The
header layout varies slightly between assets, so the width/height/pitch triple is located by
scanning a small window and validating that ``pitch`` is a whole multiple of ``width`` and that the
texel block fits exactly at the tail of the body.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from PIL import Image

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

__all__ = ('decode_texture',)

log = logging.getLogger(__name__)

_HEADER_SCAN = range(4, 40)
_MAX_DIM = 8192
_MAX_TEXOFF = 40
_MIN_TEXOFF = 12
_HEADER_TAIL = 9
_BPP_RGBA = 4
_BPP_RGB = 3
_BPP_RGB565 = 2


def decode_texture(body: bytes) -> PILImage | None:
    """
    Decode a ``CIwTexture`` body to a Pillow image.

    Parameters
    ----------
    body : bytes
        Raw serialised ``CIwTexture`` body (as returned by :func:`destin.marmalade.resgroup.parse`).

    Returns
    -------
    PIL.Image.Image or None
        The decoded image, or ``None`` if no valid texel layout was found.
    """
    n = len(body)
    for off in _HEADER_SCAN:
        if off + _HEADER_TAIL > n:
            break
        w = struct.unpack_from('<H', body, off + 3)[0]
        h = struct.unpack_from('<H', body, off + 5)[0]
        pitch = struct.unpack_from('<H', body, off + 7)[0]
        if not (0 < w <= _MAX_DIM and 0 < h <= _MAX_DIM and pitch > 0) or pitch % w:
            continue
        bpp = pitch // w
        if bpp not in {1, _BPP_RGB565, _BPP_RGB, _BPP_RGBA}:
            continue
        texsize = pitch * h
        texoff = n - texsize
        if not (_MIN_TEXOFF <= texoff <= _MAX_TEXOFF and texsize > 0):
            continue
        log.debug('Decoding texture at header offset %d: %dx%d, pitch %d, %d bytes/pixel.', off, w,
                  h, pitch, bpp)
        tex = body[texoff:texoff + texsize]
        if bpp == _BPP_RGBA:
            return Image.frombytes('RGBA', (w, h), tex, 'raw', 'RGBA', pitch, 1)
        if bpp == _BPP_RGB:
            return Image.frombytes('RGB', (w, h), tex, 'raw', 'RGB', pitch, 1)
        if bpp == _BPP_RGB565:
            return Image.frombytes('RGB', (w, h), tex, 'raw', 'BGR;16', pitch, 1)
        return Image.frombytes('L', (w, h), tex, 'raw', 'L', pitch, 1)
    log.debug('No valid texture layout found in %d-byte body.', n)
    return None
