"""
Font selection for the image renderers.

Several of the games handled here carry Japanese titles, so a renderer that draws one asks
fontconfig for the best installed font with Japanese coverage. Pillow's built-in font is the last
resort; it has no such coverage, so titles degrade to boxes rather than failing the render.
"""
from __future__ import annotations

from shutil import which
import functools
import logging
import subprocess as sp

from PIL import ImageFont

__all__ = ('japanese_font_path', 'load_font')

log = logging.getLogger(__name__)

_FC_MATCH = 'fc-match'


@functools.cache
def japanese_font_path() -> str | None:
    """
    Ask fontconfig for the best installed font with Japanese coverage.

    Returns
    -------
    str | None
        The font file's path, or ``None`` when fontconfig is absent or names nothing.
    """
    if (fc_match := which(_FC_MATCH)) is None:
        log.debug('`%s` is not on PATH; falling back to the built-in font.', _FC_MATCH)
        return None
    try:
        # The exit code is handled here: any failure means falling back rather than aborting.
        matched = sp.run((fc_match, '-f', '%{file}', ':lang=ja'),
                         capture_output=True,
                         check=False,
                         text=True)
    except OSError:
        log.debug('Could not run `%s`; falling back to the built-in font.', _FC_MATCH)
        return None
    return matched.stdout.strip() or None


@functools.cache
def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Load a font of the given size, preferring one that can draw Japanese.

    Parameters
    ----------
    size : int
        The size in points.

    Returns
    -------
    PIL.ImageFont.FreeTypeFont | PIL.ImageFont.ImageFont
        The loaded font, which is Pillow's built-in one when no suitable font is installed.
    """
    if (path := japanese_font_path()) is not None:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            log.debug('Could not load `%s`; falling back to the built-in font.', path)
    return ImageFont.load_default(size)
