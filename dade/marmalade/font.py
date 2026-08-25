"""
``CIwGxFont`` decoder.

A Marmalade bitmap font stores its glyph atlas as a 4-bit paletted image (2 pixels per byte)
followed by a 16-entry ARGB4444 palette. The atlas width is twice the pitch (one nibble per pixel).
The palette is located by looking for the 16 entries whose alpha nibbles range from 0 (entry 0,
transparent) to 0xf.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from PIL import Image

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

__all__ = ('decode_font',)

log = logging.getLogger(__name__)

_HEADER_SCAN = range(0x10, 0x40)
_MAX_DIM = 2048
_MAX_PITCH = 4096
_NIBBLE = 0xF
_OPAQUE_ALPHA = 0xF
_PALETTE_ENTRIES = 16


def _find_header(body: bytes) -> tuple[int, int, int, int] | None:
    """
    Locate the glyph-atlas header.

    Parameters
    ----------
    body : bytes
        Raw serialised ``CIwGxFont`` body.

    Returns
    -------
    tuple[int, int, int, int] or None
        ``(header_off, width, height, pitch)``, or ``None`` if no header was found.
    """
    for off in _HEADER_SCAN:
        if off + 9 > len(body):
            break
        w = struct.unpack_from('<H', body, off + 3)[0]
        h = struct.unpack_from('<H', body, off + 5)[0]
        pitch = struct.unpack_from('<H', body, off + 7)[0]
        if (0 < w <= _MAX_DIM and 0 < h <= _MAX_DIM and 0 < pitch <= _MAX_PITCH and pitch * 2 == w
                and pitch * h <= len(body)):
            return off, w, h, pitch
    return None


def _read_palette(body: bytes, pal_off: int) -> list[tuple[int, int, int, int]]:
    """
    Read a 16-entry ARGB4444 palette as RGBA tuples (nibbles scaled to 0-255).

    Parameters
    ----------
    body : bytes
        Raw serialised ``CIwGxFont`` body.
    pal_off : int
        Offset of the palette within *body*.

    Returns
    -------
    list[tuple[int, int, int, int]]
        Sixteen RGBA colours.
    """
    pal = []
    for i in range(_PALETTE_ENTRIES):
        v = struct.unpack_from('<H', body, pal_off + i * 2)[0]
        pal.append((((v >> 8) & _NIBBLE) * 17, ((v >> 4) & _NIBBLE) * 17, (v & _NIBBLE) * 17,
                    ((v >> 12) & _NIBBLE) * 17))
    return pal


def decode_font(body: bytes) -> PILImage | None:
    """
    Decode a ``CIwGxFont`` body to its glyph-atlas image.

    Parameters
    ----------
    body : bytes
        Raw serialised ``CIwGxFont`` body.

    Returns
    -------
    PIL.Image.Image | None
        The RGBA glyph atlas, or ``None`` if the layout could not be resolved.
    """
    header = _find_header(body)
    if header is None:
        log.debug('No valid font header found in %d-byte body.', len(body))
        return None
    off, w, h, pitch = header
    tex = off + 13
    pal_off = tex + pitch * h
    for cand in (pal_off, pal_off + 2, pal_off + 4):
        if cand + 32 > len(body):
            continue
        alphas = [(struct.unpack_from('<H', body, cand + i * 2)[0] >> 12) & _NIBBLE
                  for i in range(_PALETTE_ENTRIES)]
        if alphas[0] == 0 and max(alphas) == _OPAQUE_ALPHA:
            pal_off = cand
            break
    log.debug('Decoding font glyph atlas: %dx%d, pitch %d, palette at offset %d.', w, h, pitch,
              pal_off)
    pal = _read_palette(body, pal_off)
    img = Image.new('RGBA', (w, h))
    px = img.load()
    if px is None:  # pragma: no cover - Pillow always provides an access object
        return img
    for y in range(h):
        row = tex + y * pitch
        for xb in range(pitch):
            b = body[row + xb]
            x = xb * 2
            px[x, y] = pal[b & _NIBBLE]
            if x + 1 < w:  # pragma: no branch - the header guarantees ``w == pitch * 2`` (even).
                px[x + 1, y] = pal[b >> 4]
    return img
