"""
ROM header, boot segment, and master table handling for both Extreme-G games.

Both games compress their main code segment and place it at a fixed RAM address, and both index
their content through tables in the loader region. The details differ: Extreme-G 1 stores a bare
LZSS header, while Extreme-G XG2 wraps the same payload in a single-entry ``XG2Arch``.

Alongside the raw segment, the boot helpers can produce an *extended* ROM image with the
decompressed code written back at the offset it runs from. Disassemblers that understand N64 ROMs
can then see the main code segment directly.
"""
from __future__ import annotations

import logging
import struct

from destin.common.lz import decompress_lzss0

from .archive import decode_entry, parse_archive
from .offsets import (
    GAME_CODE_OFFSET,
    XG1_BOOT_HEADER,
    XG1_BOOT_ROM_OFFSET,
    XG1_GLOBAL_TEXTURE_BANK_POINTER,
    XG1_LEVEL_MAX,
    XG1_LEVEL_MIN,
    XG1_LEVEL_TABLE,
    XG1_LEVEL_TEXTURE_BANK_TABLE,
    XG1_LOAD_ADDRESS_BOOT,
    XG1_LOAD_ADDRESS_CODE,
    XG2_BOOT_ARCHIVE,
    XG2_BOOT_LOAD_RAM,
    XG2_BOOT_ROM_OFFSET,
    XG2_ENTRY_RAM,
    XG2_LEVEL_MAX,
    XG2_LEVEL_MIN,
    XG2_LEVEL_TABLE,
    XG2_LEVEL_TABLE_END,
    XG2_MFS_ARCHIVE,
    XG2_RESOURCE_TABLE,
    XG2_SEQUENCE_ARCHIVE,
)

__all__ = ('BootImage', 'BootSanityError', 'game_code', 'read_u32', 'xg1_boot', 'xg1_level_bases',
           'xg1_texture_banks', 'xg2_boot', 'xg2_level_bases', 'xg2_resource_archives')

log = logging.getLogger(__name__)

_BOOT_SIGNATURE = b'\x3c\x1d\x80\x3f'
_MAX_LEVELS = 48
_ARCHIVE_TAGS = (b'LZSS', b'LHUF', b'HUFF', b'COPY')
_MAX_TEXTURE_BANK = 0x800000
_MIN_ARCHIVE_ADDRESS = 0x1000
_MAX_ARCHIVE_ENTRIES = 4096


class BootSanityError(ValueError):
    """Raised when a decompressed boot segment does not begin with the expected instruction."""
    def __init__(self, length: int, head: bytes) -> None:
        super().__init__(f'Boot sanity check failed: length 0x{length:X}, head {head.hex()}.')


class BootImage:
    """
    A decompressed boot and main code segment, with the images derived from it.

    Parameters
    ----------
    code : bytes
        The decompressed segment.
    rom : bytes
        The whole ROM image.
    rom_offset : int
        ROM offset the initial program loader is mapped from.
    gap : int
        Bytes of loader that precede the code segment in RAM.
    place : int
        ROM offset the decompressed segment is written back to in the extended image.
    """
    def __init__(self, code: bytes, rom: bytes, rom_offset: int, gap: int, place: int) -> None:
        self.code = code
        self._rom = rom
        self._rom_offset = rom_offset
        self._gap = gap
        self._place = place

    def ram_image(self) -> bytes:
        """
        Build the RAM image: the loader followed by the decompressed segment.

        Returns
        -------
        bytes
            The image as it appears in memory from the loader's entry point.
        """
        return self._rom[self._rom_offset:self._rom_offset + self._gap] + self.code

    def extended_rom(self) -> bytes:
        """
        Build a ROM image with the decompressed segment written back in place.

        Returns
        -------
        bytes
            The extended image, grown with zeroes if the segment runs past the original end.
        """
        out = bytearray(self._rom)
        end = self._place + len(self.code)
        if end > len(out):
            out.extend(b'\x00' * (end - len(out)))
        out[self._place:end] = self.code
        return bytes(out)


def read_u32(data: bytes, offset: int) -> int:
    """
    Read one big-endian unsigned 32-bit value.

    Parameters
    ----------
    data : bytes
        Buffer to read from.
    offset : int
        Offset of the value.

    Returns
    -------
    int
        The value.
    """
    return int(struct.unpack_from('>I', data, offset)[0])


def game_code(rom: bytes) -> bytes:
    """
    Read the four-character game code from an N64 ROM header.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    bytes
        The game code.
    """
    return bytes(rom[GAME_CODE_OFFSET:GAME_CODE_OFFSET + 4])


def xg1_boot(rom: bytes) -> BootImage:
    """
    Decompress the Extreme-G 1 boot and main code segment.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    BootImage
        The decompressed segment and the images derived from it.

    Raises
    ------
    BootSanityError
        If the segment does not begin with the expected instruction.
    ValueError
        If the LZSS magic is missing from the boot header.
    """
    if rom[XG1_BOOT_HEADER + 0x0C:XG1_BOOT_HEADER + 0x10] != b'LZSS':
        msg = f'Boot LZSS magic not found at 0x{XG1_BOOT_HEADER + 0x0C:X}.'
        raise ValueError(msg)
    stream = read_u32(rom, XG1_BOOT_HEADER + 8)
    size = read_u32(rom, XG1_BOOT_HEADER + 0x10)
    code = decompress_lzss0(rom, XG1_BOOT_HEADER + stream, size)[0]
    if len(code) != size or code[:4] != _BOOT_SIGNATURE:
        raise BootSanityError(len(code), code[:4])
    return BootImage(code, rom, XG1_BOOT_ROM_OFFSET, XG1_LOAD_ADDRESS_CODE - XG1_LOAD_ADDRESS_BOOT,
                     XG1_BOOT_HEADER)


def xg2_boot(rom: bytes) -> BootImage:
    """
    Decompress the Extreme-G XG2 boot and main code segment.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    BootImage
        The decompressed segment and the images derived from it.

    Raises
    ------
    BootSanityError
        If the segment does not begin with the expected instruction.
    ValueError
        If the boot container does not hold exactly one LZSS entry.
    """
    entries = parse_archive(rom, XG2_BOOT_ARCHIVE)
    if len(entries) != 1 or entries[0]['codec'] != 'LZSS':
        msg = f'Unexpected boot archive at 0x{XG2_BOOT_ARCHIVE:X}.'
        raise ValueError(msg)
    code = decode_entry(rom, entries[0])
    if len(code) != entries[0]['decompressed_size'] or code[:4] != _BOOT_SIGNATURE:
        raise BootSanityError(len(code), code[:4])
    gap = XG2_BOOT_LOAD_RAM - XG2_ENTRY_RAM
    return BootImage(code, rom, XG2_BOOT_ROM_OFFSET, gap, gap + XG2_BOOT_ROM_OFFSET)


def xg1_level_bases(rom: bytes) -> list[int]:
    """
    Read the Extreme-G 1 level container table.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    list[int]
        Distinct container offsets in ascending order. The table ends at the first entry outside
        the plausible range.
    """
    bases = []
    for i in range(_MAX_LEVELS):
        value = read_u32(rom, XG1_LEVEL_TABLE + i * 4)
        if not XG1_LEVEL_MIN <= value < XG1_LEVEL_MAX:
            break
        bases.append(value)
    return sorted(set(bases))


def xg1_texture_banks(rom: bytes) -> dict[int, str]:
    """
    Collect the Extreme-G 1 texture bank offsets.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    dict[int, str]
        Each bank's ROM offset mapped to a name for its output directory.
    """
    banks = {read_u32(rom, XG1_GLOBAL_TEXTURE_BANK_POINTER): 'global'}
    for i in range(_MAX_LEVELS):
        value = read_u32(rom, XG1_LEVEL_TEXTURE_BANK_TABLE + i * 4)
        if not XG1_LEVEL_MIN <= value < _MAX_TEXTURE_BANK:
            break
        banks.setdefault(value, f'bank_{value:07X}')
    return banks


def xg2_level_bases(rom: bytes) -> list[int]:
    """
    Read the Extreme-G XG2 level container table.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    list[int]
        Distinct container offsets in ascending order.
    """
    offsets = set()
    for offset in range(XG2_LEVEL_TABLE, XG2_LEVEL_TABLE_END, 4):
        value = read_u32(rom, offset)
        if XG2_LEVEL_MIN <= value < XG2_LEVEL_MAX:
            offsets.add(value)
    return sorted(offsets)


def xg2_resource_archives(rom: bytes) -> list[int]:
    """
    Enumerate the model archives referenced by the master resource table.

    These containers hold the bikes, riders, and shared scenery, which is most of the game's
    textured geometry; the ``mfs`` archive is only a small slice. The dedicated ``mfs`` and
    sequence containers are excluded, as they have their own extraction paths.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    list[int]
        Distinct container offsets in ascending order.
    """
    addresses = set()
    for offset in range(XG2_RESOURCE_TABLE, XG2_LEVEL_TABLE, 8):
        address = read_u32(rom, offset)
        if not _MIN_ARCHIVE_ADDRESS <= address < len(rom) - 0x10:
            continue
        count = read_u32(rom, address)
        if (1 <= count <= _MAX_ARCHIVE_ENTRIES
                and rom[address + 0xC:address + 0x10] in _ARCHIVE_TAGS
                and address not in {XG2_MFS_ARCHIVE, XG2_SEQUENCE_ARCHIVE}):
            addresses.add(address)
    return sorted(addresses)
