"""Data converters: terrain ``.bin`` and replay ``.ctl`` to JSON."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import logging
import struct

from ._base import ConversionError, UnsupportedFormatError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('bin_to_json', 'ctl_to_json')

log = logging.getLogger(__name__)

_HEIGHTFIELD_SIZE = 526338
_HEIGHTFIELD_DIM = 513
_TILE_FLAGS_SIZE = 32768
_TILE_FLAGS_DIM = 128
_TILE_FLAG_WATER = 0x2000
_CTL_RECORD = struct.Struct('<4I')


def _write_json(source: Path, dest_dir: Path, obj: dict[str, Any]) -> Path:
    destination = dest_dir / f'{source.stem}.json'
    destination.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return destination


def bin_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert an Incoming terrain ``.bin`` file to JSON.

    Two sub-formats are recognised by size: a 513x513 signed 16-bit heightfield and a 128x128
    unsigned 16-bit tile-flags grid. Any other ``.bin`` is treated as not yet decoded.

    Parameters
    ----------
    source : Path
        The source ``.bin`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.

    Raises
    ------
    UnsupportedFormatError
        If the file is neither known terrain sub-format.
    """
    size = source.stat().st_size
    if size not in {_HEIGHTFIELD_SIZE, _TILE_FLAGS_SIZE}:
        msg = f'`{source.name}` is {size} bytes; not a known terrain sub-format.'
        raise UnsupportedFormatError(msg)
    data = source.read_bytes()
    if size == _HEIGHTFIELD_SIZE:
        heights = list(struct.unpack(f'<{_HEIGHTFIELD_DIM * _HEIGHTFIELD_DIM}h', data))
        obj: dict[str, Any] = {
            'heights': heights,
            'height': _HEIGHTFIELD_DIM,
            'index': 'x * 513 + z',
            'type': 'heightfield',
            'width': _HEIGHTFIELD_DIM,
        }
    else:
        flags = list(struct.unpack(f'<{_TILE_FLAGS_DIM * _TILE_FLAGS_DIM}H', data))
        obj = {
            'flags': flags,
            'height': _TILE_FLAGS_DIM,
            'index': 'tx * 128 + tz',
            'type': 'tile_flags',
            'water_bit': _TILE_FLAG_WATER,
            'width': _TILE_FLAGS_DIM,
        }
    return _write_json(source, dest_dir, obj)


def ctl_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert an Incoming ``.ctl`` demo/replay recording to JSON.

    The first 16-byte record is the seed/header; the remainder are one input record per simulation
    frame.

    Parameters
    ----------
    source : Path
        The source ``.ctl`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.

    Raises
    ------
    ConversionError
        If the file is not a whole number of 16-byte records.
    """
    data = source.read_bytes()
    if len(data) < _CTL_RECORD.size or len(data) % _CTL_RECORD.size:
        msg = f'`{source.name}` is {len(data)} bytes; not a whole number of 16-byte records.'
        raise ConversionError(msg)
    records = [{
        'axis_x': axis_x,
        'axis_y': axis_y,
        'flags': flags,
        'mode': mode,
    } for mode, flags, axis_x, axis_y in _CTL_RECORD.iter_unpack(data)]
    obj = {'frame_count': len(records) - 1, 'frames': records[1:], 'header': records[0]}
    return _write_json(source, dest_dir, obj)
