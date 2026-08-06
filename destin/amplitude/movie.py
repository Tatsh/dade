"""
Extract metadata from FreQuency ``MOVS`` movies (``.mmv``).

``.mmv`` is a ``MOVS`` container in two forms: an **animated texture** (a ``MOVT`` track of ``RLE8``
8bpp run-length frames -- the UI ``*_gif`` animations) and a **soundbank movie** (a ``SNDH`` chunk
streaming the hardware-synth banks, returned by the levels' ``get_soundbank_movie``).
This module identifies the form and its parameters; decoding the RLE8 frames to an animation, or the
``SNDH`` audio, is left for a dedicated pass.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging
import struct

from .typing import InvalidFormatError

if TYPE_CHECKING:
    from pathlib import Path

    from .typing import MMVMeta

__all__ = ('EXTENSIONS', 'convert', 'mmv_to_json')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.mmv'})
"""File extensions handled by :py:func:`convert`."""

_MMV_MIN_SIZE = 24  # MOVS header: magic plus five u32 fields.
_MMV_CHUNK_FIELDS = 8  # Bytes read from a sub-chunk past its tag (dimensions or bank count).


def mmv_to_json(data: bytes) -> MMVMeta:
    """
    Decode a ``MOVS`` movie header to metadata.

    The header is ``u32 'MOVS', u32 0, u32 version, u32 0, u32 trackCount, u32 tickRate``. An
    animated texture then carries a ``MOVT`` track whose ``RLE8`` chunk gives ``u16 width, u16
    height``; a soundbank movie carries a ``SNDH`` chunk whose first field is the bank count.

    Parameters
    ----------
    data : bytes
        The ``.mmv`` file contents.

    Returns
    -------
    MMVMeta
        Movie metadata (form, version, dimensions or bank count).

    Raises
    ------
    InvalidFormatError
        If the data is not a ``MOVS`` movie.
    """
    if data[:4] != b'MOVS' or len(data) < _MMV_MIN_SIZE:
        msg = 'Not a `MOVS` movie.'
        raise InvalidFormatError(msg)
    version, track_count, tick_rate = (struct.unpack_from(
        '<I', data, 8)[0], struct.unpack_from('<I', data, 16)[0], struct.unpack_from(
            '<I', data, 20)[0])
    meta: MMVMeta = {
        'magic': 'MOVS',
        'version': version,
        'track_count': track_count,
        'tick_rate': tick_rate,
        'size': len(data),
        'type': 'unknown'
    }
    rle = data.find(b'RLE8')
    sndh = data.find(b'SNDH')
    if b'MOVT' in data and 0 <= rle <= len(data) - _MMV_CHUNK_FIELDS:
        meta['type'] = 'animated_texture'
        meta['codec'] = 'RLE8'
        meta['width'], meta['height'] = struct.unpack_from('<HH', data, rle + 4)
    elif 0 <= sndh <= len(data) - _MMV_CHUNK_FIELDS:
        meta['type'] = 'soundbank_movie'
        meta['bank_count'] = struct.unpack_from('<I', data, sndh + 4)[0]
    return meta


def convert(path: Path) -> Path | None:
    """
    Write a ``MOVS`` metadata sidecar (``<name>.mmv.json``); the raw ``.mmv`` is kept.

    Parameters
    ----------
    path : pathlib.Path
        The ``.mmv`` file.

    Returns
    -------
    pathlib.Path | None
        The written JSON path, or ``None`` if the file is not a ``MOVS`` movie.
    """
    try:
        meta = mmv_to_json(path.read_bytes())
    except InvalidFormatError:
        return None
    out = path.with_name(f'{path.name}.json')
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    log.debug('Movie `%s`: %s -> `%s`.', path.name, meta['type'], out.name)
    return out
