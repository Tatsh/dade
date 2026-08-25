"""
Assembler for a mission's 360-degree horizon panorama.

A mission's ``WRLD`` chunk references an ``.hzd`` file, which is a text list of horizon strip names
of the form ``NH_<set>_NN.MAP``. The strips live in the ``nhoriz<set>m.pak`` bundle and are laid
out left to right to form one panorama whose horizontal axis is azimuth and whose vertical axis is
height.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

from .typing import RgbImage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .typing import IndexedImage

__all__ = ('assemble_panorama', 'bundle_stem', 'horizon_set', 'parse_hzd')

log = logging.getLogger(__name__)

_MAP_SUFFIX = b'.map'
"""Suffix marking a printable run in an ``.hzd`` as a strip name.

:meta hide-value:
"""
_PRINTABLE_START = 0x20
"""Lowest byte value treated as printable ASCII.

:meta hide-value:
"""
_PRINTABLE_END = 0x7F
"""One past the highest byte value treated as printable ASCII.

:meta hide-value:
"""


def parse_hzd(data: bytes) -> tuple[str, ...]:
    """
    Read the horizon strip names out of an ``.hzd``.

    Parameters
    ----------
    data : bytes
        Contents of the ``.hzd`` file.

    Returns
    -------
    tuple[str, ...]
        Every strip name, in panorama order.
    """
    names: list[str] = []
    current = bytearray()
    for byte in data:
        if _PRINTABLE_START <= byte < _PRINTABLE_END:
            current.append(byte)
        else:
            if current.lower().endswith(_MAP_SUFFIX):
                names.append(current.decode('latin1'))
            current = bytearray()
    if current.lower().endswith(_MAP_SUFFIX):
        names.append(current.decode('latin1'))
    return tuple(names)


def horizon_set(name: str) -> int:
    """
    Take the horizon set number out of a strip name.

    A name without a numeric set field raises :py:class:`ValueError`.

    Parameters
    ----------
    name : str
        A strip name of the form ``NH_<set>_NN.MAP``.

    Returns
    -------
    int
        The set number.
    """
    return int(name.split('_')[1])


def bundle_stem(set_number: int) -> str:
    """
    Give the bundle stem holding a horizon set's strips.

    Parameters
    ----------
    set_number : int
        The horizon set number.

    Returns
    -------
    str
        The stem shared by the ``.pak`` bundle and its ``.pix`` index.
    """
    return f'nhoriz{set_number}m'


def assemble_panorama(strips: Sequence[IndexedImage], palette: bytes) -> RgbImage:
    """
    Lay horizon strips out left to right into one truecolour panorama.

    The panorama's height is that of the first strip.

    Parameters
    ----------
    strips : collections.abc.Sequence[IndexedImage]
        The decoded strips, in panorama order.
    palette : bytes
        A 768-byte palette of 256 RGB triples.

    Returns
    -------
    RgbImage
        The assembled panorama.

    Raises
    ------
    ValueError
        If ``strips`` is empty.
    """
    if not strips:
        msg = 'No horizon strips to assemble.'
        raise ValueError(msg)
    height = strips[0].height
    total_width = sum(strip.width for strip in strips)
    rgb = bytearray(total_width * height * 3)
    x_offset = 0
    for strip in strips:
        for y in range(height):
            for x in range(strip.width):
                index = strip.pixels[y * strip.width + x]
                position = (y * total_width + (x_offset + x)) * 3
                rgb[position] = palette[index * 3]
                rgb[position + 1] = palette[index * 3 + 1]
                rgb[position + 2] = palette[index * 3 + 2]
        x_offset += strip.width
    log.debug('Assembled %d strips into a %dx%d panorama.', len(strips), total_width, height)
    return RgbImage(total_width, height, bytes(rgb))
