"""
ROM offsets for the supported Extreme-G builds.

These are facts about specific ROM revisions rather than user-tunable settings, so they live here
instead of on the command line. Each game is identified by the four-character code at ROM offset
``0x3B``: ``NEGE`` for Extreme-G and ``NG2E`` for Extreme-G XG2, both USA releases.
"""
from __future__ import annotations

__all__ = ('GAME_CODE_OFFSET', 'XG1_BOOT_HEADER', 'XG1_BOOT_ROM_OFFSET', 'XG1_DIRECTORY_POINTER',
           'XG1_GAME_CODE', 'XG1_GLOBAL_TEXTURE_BANK_POINTER', 'XG1_LEVEL_MAX', 'XG1_LEVEL_MIN',
           'XG1_LEVEL_TABLE', 'XG1_LEVEL_TEXTURE_BANK_TABLE', 'XG1_LOAD_ADDRESS_BOOT',
           'XG1_LOAD_ADDRESS_CODE', 'XG1_MFS_COUNT', 'XG1_MFS_TABLE', 'XG2_BOOT_ARCHIVE',
           'XG2_BOOT_LOAD_RAM', 'XG2_BOOT_ROM_OFFSET', 'XG2_ENTRY_RAM', 'XG2_GAME_CODE',
           'XG2_LEVEL_MAX', 'XG2_LEVEL_MIN', 'XG2_LEVEL_TABLE', 'XG2_LEVEL_TABLE_END',
           'XG2_MELODIC_BANK', 'XG2_MFS_ARCHIVE', 'XG2_RESOURCE_TABLE', 'XG2_SEQUENCE_ARCHIVE',
           'XG2_SOUNDBANKS')

GAME_CODE_OFFSET = 0x3B
"""Offset of the four-character game code in an N64 ROM header.

:meta hide-value:
"""

XG1_GAME_CODE = b'NEGE'
"""Game code of Extreme-G (USA).

:meta hide-value:
"""
XG1_BOOT_HEADER = 0x14A0
"""Header of the LZSS-compressed boot and main code segment.

:meta hide-value:
"""
XG1_BOOT_ROM_OFFSET = 0x1000
"""ROM offset the initial program loader is mapped from.

:meta hide-value:
"""
XG1_LOAD_ADDRESS_BOOT = 0x8004B400
"""RAM address the initial program loader runs at.

:meta hide-value:
"""
XG1_LOAD_ADDRESS_CODE = 0x8004B8A0
"""RAM address the decompressed main code segment is placed at.

:meta hide-value:
"""
XG1_MFS_COUNT = 0x7A2DF0
"""Header of the ``mfs`` directory: entry count, padding, then the first file offset.

:meta hide-value:
"""
XG1_MFS_TABLE = 0x7A2DFC
"""First 16-byte record of the ``mfs`` directory.

:meta hide-value:
"""
XG1_LEVEL_TABLE = 0x1408
"""Table of ROM offsets, one per level container.

:meta hide-value:
"""
XG1_LEVEL_MIN = 0x2F000
"""Lowest ROM offset accepted as a level container.

:meta hide-value:
"""
XG1_LEVEL_MAX = 0x700000
"""Exclusive upper bound on ROM offsets accepted as a level container.

:meta hide-value:
"""
XG1_DIRECTORY_POINTER = 0x1248
"""Pointer to the master directory: ROM address followed by size.

:meta hide-value:
"""
XG1_GLOBAL_TEXTURE_BANK_POINTER = 0x1280
"""Pointer to the ROM address of the global texture bank.

:meta hide-value:
"""
XG1_LEVEL_TEXTURE_BANK_TABLE = 0x1450
"""Table of ROM addresses, one texture bank per region.

:meta hide-value:
"""

XG2_GAME_CODE = b'NG2E'
"""Game code of Extreme-G XG2 (USA).

:meta hide-value:
"""
XG2_BOOT_ARCHIVE = 0x1620
"""Single-entry ``XG2Arch`` holding the LZSS boot blob.

:meta hide-value:
"""
XG2_BOOT_ROM_OFFSET = 0x1000
"""ROM offset the initial program loader is mapped from.

:meta hide-value:
"""
XG2_ENTRY_RAM = 0x8004B400
"""RAM address the ROM header's entry point maps to.

:meta hide-value:
"""
XG2_BOOT_LOAD_RAM = 0x8004BA20
"""RAM address the loader jumps to once the boot blob is decompressed.

:meta hide-value:
"""
XG2_MFS_ARCHIVE = 0xA4DF10
"""``XG2Arch`` holding the ``mfs`` archive.

:meta hide-value:
"""
XG2_SEQUENCE_ARCHIVE = 0xA2B430
"""``XG2Arch`` holding the music sequences, stored uncompressed.

:meta hide-value:
"""
XG2_RESOURCE_TABLE = 0x1250
"""Master table of ``{address, size}`` pairs indexing the model archives.

:meta hide-value:
"""
XG2_LEVEL_TABLE = 0x15C8
"""Table of ROM offsets, one per level container.

:meta hide-value:
"""
XG2_LEVEL_TABLE_END = 0x1620
"""Exclusive end of the level table, which sits in the loader region.

:meta hide-value:
"""
XG2_LEVEL_MIN = 0x2C000
"""Lowest ROM offset accepted as a level container.

:meta hide-value:
"""
XG2_LEVEL_MAX = 0xC00000
"""Exclusive upper bound on ROM offsets accepted as a level container.

:meta hide-value:
"""
XG2_SOUNDBANKS = (0x7DD9E0, 0x962D50)
"""``ALBankFile`` control banks, each paired with an embedded sample table.

:meta hide-value:
"""
XG2_MELODIC_BANK = 0x962D50
"""The control bank the music sequences play through; the other holds sound effects.

:meta hide-value:
"""
