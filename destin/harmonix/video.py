"""Extract metadata from PS2 IPU video files (``.ipu``)."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from destin.common.json import write_json

from .typing import InvalidFormatError

if TYPE_CHECKING:
    from pathlib import Path

    from .typing import IPUMeta

__all__ = ('EXTENSIONS', 'convert', 'ipu_to_json')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.ipu'})
"""File extensions handled by :py:func:`convert`.

:meta hide-value:
"""

_IPU_MIN_SIZE = 16  # 'ipum' magic plus the dimension and frame-count fields.


def ipu_to_json(data: bytes) -> IPUMeta:
    """
    Decode a PS2 IPU video header to metadata.

    The payload is a raw IPU IDEC MPEG2-intra bitstream (frames delimited by ``0x000001B0``, with
    no MPEG sequence/slice headers), so a full transcode would need IPU/MPEG2 emulation.

    Parameters
    ----------
    data : bytes
        The ``.ipu`` file contents.

    Returns
    -------
    IPUMeta
        Metadata (dimensions, frame count).

    Raises
    ------
    InvalidFormatError
        If the data is not an ``ipum`` file.
    """
    if data[:4] != b'ipum' or len(data) < _IPU_MIN_SIZE:
        msg = 'Not a PS2 IPU (`ipum`) file.'
        raise InvalidFormatError(msg)
    return {
        'magic': 'ipum',
        'width': struct.unpack_from('<H', data, 8)[0],
        'height': struct.unpack_from('<H', data, 10)[0],
        'frame_count': struct.unpack_from('<I', data, 12)[0]
    }


def convert(path: Path) -> Path | None:
    """
    Write an IPU metadata sidecar (``<name>.ipu.json``); the raw ``.ipu`` is kept.

    Parameters
    ----------
    path : pathlib.Path
        The ``.ipu`` file.

    Returns
    -------
    pathlib.Path | None
        The written JSON path, or ``None`` if the file is not an ``ipum`` file.
    """
    try:
        meta = ipu_to_json(path.read_bytes())
    except InvalidFormatError:
        return None
    out = path.with_name(f'{path.name}.json')
    write_json(out, meta, ensure_ascii=False, trailing_newline=False)
    log.debug('IPU `%s`: %dx%d, %d frames -> `%s`.', path.name, meta['width'], meta['height'],
              meta['frame_count'], out.name)
    return out
