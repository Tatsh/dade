"""
pop'n rhythmin (Konami) toolkit.

``rhythmin`` reads the data files of the iOS rhythm game *pop'n rhythmin*:

- :mod:`destin.rhythmin.bfcodec` - the ``BFCodec`` cipher every encrypted file uses, which is
  Blowfish with one deviation in its F function.
- :mod:`destin.rhythmin.chara` - the downloaded ``chara_%03d.chr`` character data.
- :mod:`destin.rhythmin.aep` - the ``.idx`` AEP animation indexes.
- :mod:`destin.rhythmin.treasure_map` - the sugoroku ``map_%03d.map`` boards.
- :mod:`destin.rhythmin.sheet` - the note charts inside ``.orb`` and ``.acv`` song packages.
- :mod:`destin.rhythmin.dialogue` - the sugoroku dialogue pools inside an app binary.
"""
from __future__ import annotations

from .aep import AepIndex, FrameEntry, SpriteRecord, index_to_json, read_aep_index
from .bfcodec import BFCodec, Blowfish, decipher, default_key, encipher
from .chara import decrypt_chara, parse_chara, read_chara
from .dialogue import DialoguePool, empty_pools, extract_pools, render_binary, render_c_header
from .sheet import (
    ArcadeUnit,
    ChartStrip,
    Sheet,
    StandardChart,
    StandardRecord,
    arcade_strip,
    arcade_to_json,
    detect_format,
    parse_arcade,
    parse_standard,
    read_sheet,
    standard_strip,
    standard_to_json,
)
from .treasure_map import Square, TreasureMap, map_to_json, parse_treasure_map, read_treasure_map

__all__ = ('AepIndex', 'ArcadeUnit', 'BFCodec', 'Blowfish', 'ChartStrip', 'DialoguePool',
           'FrameEntry', 'Sheet', 'SpriteRecord', 'Square', 'StandardChart', 'StandardRecord',
           'TreasureMap', 'arcade_strip', 'arcade_to_json', 'decipher', 'decrypt_chara',
           'default_key', 'detect_format', 'empty_pools', 'encipher', 'extract_pools',
           'index_to_json', 'map_to_json', 'parse_arcade', 'parse_chara', 'parse_standard',
           'parse_treasure_map', 'read_aep_index', 'read_chara', 'read_sheet', 'read_treasure_map',
           'render_binary', 'render_c_header', 'standard_strip', 'standard_to_json')
