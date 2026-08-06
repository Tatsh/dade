"""Tests for :mod:`destin.xg2.rom`."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.xg2.offsets import (
    GAME_CODE_OFFSET,
    XG1_BOOT_HEADER,
    XG1_GLOBAL_TEXTURE_BANK_POINTER,
    XG1_LEVEL_TABLE,
    XG1_LEVEL_TEXTURE_BANK_TABLE,
    XG2_BOOT_ARCHIVE,
    XG2_GAME_CODE,
    XG2_LEVEL_TABLE,
    XG2_MFS_ARCHIVE,
)
from destin.xg2.rom import (
    BootSanityError,
    game_code,
    read_u32,
    xg1_boot,
    xg1_level_bases,
    xg1_texture_banks,
    xg2_boot,
    xg2_level_bases,
    xg2_resource_archives,
)
import pytest

from .conftest import BOOT_SIGNATURE, XG1_LEVEL_BASES, XG2_LEVEL_BASES, XG2_MODEL_ARCHIVE

if TYPE_CHECKING:
    from collections.abc import Callable

_MAX_LEVELS = 48


def _xg1_boot_rom(make_lzss: Callable[[bytes], bytes],
                  payload: bytes = BOOT_SIGNATURE + b'\x00' * 0x1C,
                  size: int = 0x2000) -> bytearray:
    rom = bytearray(size)
    stream = make_lzss(payload)
    struct.pack_into('>I', rom, XG1_BOOT_HEADER + 8, 0x20)
    rom[XG1_BOOT_HEADER + 0x0C:XG1_BOOT_HEADER + 0x10] = b'LZSS'
    struct.pack_into('>I', rom, XG1_BOOT_HEADER + 0x10, len(payload))
    rom[XG1_BOOT_HEADER + 0x20:XG1_BOOT_HEADER + 0x20 + len(stream)] = stream
    return rom


def _xg2_boot_rom(make_archive: Callable[..., bytes],
                  make_lzss: Callable[[bytes], bytes],
                  payload: bytes = BOOT_SIGNATURE + b'\x00' * 0x1C,
                  tag: bytes = b'LZSS') -> bytearray:
    rom = bytearray(0x2000)
    container = bytearray(make_archive([(tag, make_lzss(payload))]))
    struct.pack_into('>I', container, 0x10, len(payload))
    rom[XG2_BOOT_ARCHIVE:XG2_BOOT_ARCHIVE + len(container)] = container
    return rom


def test_read_u32() -> None:
    assert read_u32(b'\x00\x12\x34\x56\x78', 1) == 0x12345678


def test_game_code() -> None:
    rom = bytearray(0x100)
    rom[GAME_CODE_OFFSET:GAME_CODE_OFFSET + 4] = XG2_GAME_CODE
    assert game_code(bytes(rom)) == XG2_GAME_CODE


def test_xg1_boot_decompresses_the_segment(make_lzss: Callable[[bytes], bytes]) -> None:
    boot = xg1_boot(bytes(_xg1_boot_rom(make_lzss)))
    assert boot.code[:4] == BOOT_SIGNATURE
    assert len(boot.code) == 0x20


def test_xg1_boot_rejects_a_missing_magic(make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _xg1_boot_rom(make_lzss)
    rom[XG1_BOOT_HEADER + 0x0C:XG1_BOOT_HEADER + 0x10] = b'ZZZZ'
    with pytest.raises(ValueError, match='Boot LZSS magic not found'):
        xg1_boot(bytes(rom))


def test_xg1_boot_rejects_an_unexpected_first_instruction(
        make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _xg1_boot_rom(make_lzss, b'\x00' * 0x20)
    with pytest.raises(BootSanityError, match='Boot sanity check failed'):
        xg1_boot(bytes(rom))


def test_boot_image_ram_image_prefixes_the_loader(make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _xg1_boot_rom(make_lzss)
    rom[0x1000:0x1010] = b'\xaa' * 0x10
    image = xg1_boot(bytes(rom)).ram_image()
    assert image[:0x10] == b'\xaa' * 0x10
    assert image.endswith(BOOT_SIGNATURE + b'\x00' * 0x1C)


def test_boot_image_extended_rom_places_the_segment(make_lzss: Callable[[bytes], bytes]) -> None:
    extended = xg1_boot(bytes(_xg1_boot_rom(make_lzss))).extended_rom()
    assert len(extended) == 0x2000
    assert extended[XG1_BOOT_HEADER:XG1_BOOT_HEADER + 4] == BOOT_SIGNATURE


def test_boot_image_extended_rom_grows_the_image() -> None:
    # Eight literals followed by eight maximum-length matches against the zero-filled ring, so the
    # segment expands well past the end of the image it is written back into.
    stream = bytes([0xFF]) + BOOT_SIGNATURE + b'\x00' * 4 + bytes([0x00]) + bytes([0x00, 0x0F]) * 8
    rom = bytearray(0x1500)
    struct.pack_into('>I', rom, XG1_BOOT_HEADER + 8, 0x20)
    rom[XG1_BOOT_HEADER + 0x0C:XG1_BOOT_HEADER + 0x10] = b'LZSS'
    struct.pack_into('>I', rom, XG1_BOOT_HEADER + 0x10, 152)
    rom[XG1_BOOT_HEADER + 0x20:XG1_BOOT_HEADER + 0x20 + len(stream)] = stream
    extended = xg1_boot(bytes(rom)).extended_rom()
    assert len(extended) == XG1_BOOT_HEADER + 152
    assert extended[XG1_BOOT_HEADER:XG1_BOOT_HEADER + 4] == BOOT_SIGNATURE


def test_xg2_boot_decompresses_the_segment(make_archive: Callable[..., bytes],
                                           make_lzss: Callable[[bytes], bytes]) -> None:
    boot = xg2_boot(bytes(_xg2_boot_rom(make_archive, make_lzss)))
    assert boot.code[:4] == BOOT_SIGNATURE


def test_xg2_boot_rejects_the_wrong_codec(make_archive: Callable[..., bytes],
                                          make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _xg2_boot_rom(make_archive, make_lzss, tag=b'COPY')
    with pytest.raises(ValueError, match='Unexpected boot archive'):
        xg2_boot(bytes(rom))


def test_xg2_boot_rejects_an_unexpected_first_instruction(
        make_archive: Callable[..., bytes], make_lzss: Callable[[bytes], bytes]) -> None:
    rom = _xg2_boot_rom(make_archive, make_lzss, b'\x00' * 0x20)
    with pytest.raises(BootSanityError):
        xg2_boot(bytes(rom))


def test_xg2_boot_ram_image_and_extended_rom(make_archive: Callable[..., bytes],
                                             make_lzss: Callable[[bytes], bytes]) -> None:
    boot = xg2_boot(bytes(_xg2_boot_rom(make_archive, make_lzss)))
    assert len(boot.ram_image()) == 0x620 + 0x20
    assert len(boot.extended_rom()) == 0x2000


def test_xg1_level_bases_reads_the_table(make_xg1_rom: Callable[..., bytes]) -> None:
    assert xg1_level_bases(make_xg1_rom()) == list(XG1_LEVEL_BASES)


def test_xg1_level_bases_stops_outside_the_range() -> None:
    rom = bytearray(0x10000)
    struct.pack_into('>3I', rom, XG1_LEVEL_TABLE, 0x30000, 0x30000, 0x10)
    assert xg1_level_bases(bytes(rom)) == [0x30000]


def test_xg1_level_bases_stops_at_the_table_limit() -> None:
    rom = bytearray(0x10000)
    for i in range(_MAX_LEVELS):
        struct.pack_into('>I', rom, XG1_LEVEL_TABLE + i * 4, 0x30000 + i * 0x100)
    assert len(xg1_level_bases(bytes(rom))) == _MAX_LEVELS


def test_xg1_texture_banks_stops_at_the_table_limit() -> None:
    rom = bytearray(0x10000)
    struct.pack_into('>I', rom, XG1_GLOBAL_TEXTURE_BANK_POINTER, 0x300000)
    for i in range(_MAX_LEVELS):
        struct.pack_into('>I', rom, XG1_LEVEL_TEXTURE_BANK_TABLE + i * 4, 0x400000 + i * 0x100)
    assert len(xg1_texture_banks(bytes(rom))) == _MAX_LEVELS + 1


def test_xg1_texture_banks_names_the_global_bank(make_xg1_rom: Callable[..., bytes]) -> None:
    banks = xg1_texture_banks(make_xg1_rom())
    assert banks[0x300000] == 'global'
    assert banks[0x310000] == 'bank_0310000'


def test_xg1_texture_banks_keeps_the_global_name_for_a_duplicate() -> None:
    rom = bytearray(0x10000)
    struct.pack_into('>I', rom, XG1_GLOBAL_TEXTURE_BANK_POINTER, 0x300000)
    struct.pack_into('>I', rom, XG1_LEVEL_TEXTURE_BANK_TABLE, 0x300000)
    assert xg1_texture_banks(bytes(rom)) == {0x300000: 'global'}


def test_xg2_level_bases_reads_the_table(make_xg2_rom: Callable[..., bytes]) -> None:
    assert xg2_level_bases(make_xg2_rom()) == list(XG2_LEVEL_BASES)


def test_xg2_level_bases_ignores_values_outside_the_range() -> None:
    rom = bytearray(0x10000)
    struct.pack_into('>2I', rom, XG2_LEVEL_TABLE, 0x2C000, 0xD00000)
    assert xg2_level_bases(bytes(rom)) == [0x2C000]


def test_xg2_resource_archives_excludes_the_known_containers(
        make_xg2_rom: Callable[..., bytes]) -> None:
    addresses = xg2_resource_archives(make_xg2_rom())
    assert XG2_MODEL_ARCHIVE in addresses
    assert XG2_MODEL_ARCHIVE + 0x10000 in addresses
    assert XG2_MFS_ARCHIVE not in addresses
    assert 0x20 not in addresses


def test_xg2_resource_archives_rejects_an_implausible_header(
        make_xg2_rom: Callable[..., bytes]) -> None:
    rom = bytearray(make_xg2_rom())
    struct.pack_into('>I', rom, XG2_MODEL_ARCHIVE + 0x0C, 0)  # Blank the codec tag.
    assert XG2_MODEL_ARCHIVE not in xg2_resource_archives(bytes(rom))
