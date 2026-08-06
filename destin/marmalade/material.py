"""
``CIwMaterial`` decoder.

A material stores a flags word, four RGBA colour channels (ambient, emissive, specular, and a fourth
colour), and a list of referenced texture hashes. A material flagged ``same_as_default`` carries
only its flags.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging
import struct

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ('decode_material',)

log = logging.getLogger(__name__)

_COLOR_CHANNELS = ('ambient', 'emissive', 'specular', 'colour4')


def decode_material(body: bytes, texture_names: Mapping[int, str] | None = None) -> dict[str, Any]:
    """
    Decode a ``CIwMaterial`` body to a plain dictionary.

    Parameters
    ----------
    body : bytes
        Raw serialised ``CIwMaterial`` body.
    texture_names : Mapping[int, str], optional
        Map of texture name-hash to a human-friendly file name, used to resolve texture references.
        Unmapped hashes are rendered as 8-hex-digit strings.

    Returns
    -------
    dict
        ``{'same_as_default', 'flags', 'colour_*', 'textures'}`` (colours and textures are omitted
        for a default material).
    """
    names = texture_names or {}
    p = 0
    same = bool(body[p])
    p += 1
    material: dict[str, Any] = {'same_as_default': same}
    flags = struct.unpack_from('<I', body, p)[0]
    material['flags'] = f'0x{flags:x}'
    if same:
        log.debug('Material is same-as-default with flags %#x.', flags)
        return material
    p += 4
    p += 4  # two u16 fields
    for channel in _COLOR_CHANNELS:
        material[f'colour_{channel}'] = list(body[p:p + 4])
        p += 4
    count = struct.unpack_from('<I', body, p)[0]
    p += 4
    refs = []
    for _ in range(count):
        h = struct.unpack_from('<I', body, p)[0]
        p += 4
        if h:
            refs.append(names.get(h, f'{h:08x}'))
    material['textures'] = refs
    log.debug('Decoded material with flags %#x and %d texture reference(s).', flags, len(refs))
    return material
