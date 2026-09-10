"""
Font selection shared by the pop'n rhythmin image renderers.

Song and board titles are Japanese, and the renderers therefore query fontconfig for the best
installed font with Japanese coverage. Pillow's built-in font is the last resort. It has no such
coverage, and titles therefore degrade to boxes rather than failing the render.

The selection itself is :py:mod:`dade.common.fonts`, shared with the other games that draw
Japanese titles.
"""
from __future__ import annotations

from dade.common.fonts import japanese_font_path, load_font

__all__ = ('japanese_font_path', 'load_font')
