"""
Dance Dance Revolution S+ (Konami) toolkit.

``ddrsplus`` reads the ``.gen`` song containers of the iOS rhythm game *Dance Dance Revolution S+*:

- :mod:`destin.ddrsplus.bfcodec` - the ``KDEI`` framing around the shared ``BFCodec`` cipher.
- :mod:`destin.ddrsplus.gen` - the container itself, its metadata, and its note count tables.
- :mod:`destin.ddrsplus.pvr` - the PowerVR banner textures.
- :mod:`destin.ddrsplus.gap` - the ``#OFFSET`` gap, measured from the audio.
- :mod:`destin.ddrsplus.extract` - unpacking a container into a directory of usable files.

The step charts are SSQ, which :mod:`destin.common.ssq` reads because the format belongs to the
Dance Dance Revolution series rather than to this game alone.
"""
from __future__ import annotations

from .bfcodec import GEN_KEY, KDEI_MAGIC, decipher, encipher
from .extract import ExtractedSong, extract_gen
from .gap import estimate_gap
from .gen import (
    DIFFICULTY_SLOTS,
    SECTION_EXTENSIONS,
    SHAKE_SLOTS,
    ChartTable,
    GenSection,
    SongMetadata,
    parse_chart_table,
    parse_metadata,
    read_gen,
    split_gen,
)
from .pvr import BANNER_SIZE, PVRHeader, Texture, crop, decode_pvr

__all__ = ('BANNER_SIZE', 'DIFFICULTY_SLOTS', 'GEN_KEY', 'KDEI_MAGIC', 'SECTION_EXTENSIONS',
           'SHAKE_SLOTS', 'ChartTable', 'ExtractedSong', 'GenSection', 'PVRHeader', 'SongMetadata',
           'Texture', 'crop', 'decipher', 'decode_pvr', 'encipher', 'estimate_gap', 'extract_gen',
           'parse_chart_table', 'parse_metadata', 'read_gen', 'split_gen')
