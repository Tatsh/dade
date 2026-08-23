"""Fixtures for the :py:mod:`destin.xg2` tests."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from destin.xg2.albank import BANK_MAGIC
from destin.xg2.bmc import BMC_HEADER_SIZE, BMC_MAGIC
from destin.xg2.extract_xg2 import SHAW_MAGIC
from destin.xg2.offsets import (
    XG1_BOOT_HEADER,
    XG1_DIRECTORY_POINTER,
    XG1_GLOBAL_TEXTURE_BANK_POINTER,
    XG1_LEVEL_TABLE,
    XG1_LEVEL_TEXTURE_BANK_TABLE,
    XG1_MFS_COUNT,
    XG1_MFS_TABLE,
    XG2_BOOT_ARCHIVE,
    XG2_LEVEL_TABLE,
    XG2_MFS_ARCHIVE,
    XG2_RESOURCE_TABLE,
    XG2_SEQUENCE_ARCHIVE,
    XG2_SOUNDBANKS,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from destin.xg2.typing import SampleMeta, Sf2Preset, Sf2Zone

BOOT_SIGNATURE = b'\x3c\x1d\x80\x3f'
"""First instruction of a decompressed boot segment, which both games are checked against.

:meta hide-value:
"""
XG1_LEVEL_BASES = (0x30000, 0x40000)
"""Level container offsets placed in the synthetic Extreme-G 1 ROM.

:meta hide-value:
"""
XG1_ROM_SIZE = 0x7A3000
"""Size of the synthetic Extreme-G 1 ROM, which must hold the ``mfs`` directory.

:meta hide-value:
"""
XG1_SEQUENCE_BASE = 0x500000
"""Offset of the ``S1`` sound bank in the synthetic Extreme-G 1 ROM.

:meta hide-value:
"""
XG1_TEXTURE_BANK = 0x300000
"""Offset of the global texture bank in the synthetic Extreme-G 1 ROM.

:meta hide-value:
"""
XG2_LEVEL_BASES = (0x7DD8E0, 0x7DD900)
"""Level container offsets placed in the synthetic Extreme-G XG2 ROM.

:meta hide-value:
"""
XG2_MODEL_ARCHIVE = 0x700000
"""Offset of the model archive the resource table points at in the synthetic XG2 ROM.

:meta hide-value:
"""
XG2_ROM_SIZE = 0xA60000
"""Size of the synthetic Extreme-G XG2 ROM, which must hold the ``mfs`` container.

:meta hide-value:
"""
_MFS_FIRST = 0x100
_MFS_RECORD_SIZE = 0x10


@pytest.fixture
def make_archive() -> Callable[[Sequence[tuple[bytes, bytes]], str], bytes]:
    """
    Build an ``XG2Arch`` container.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[bytes, bytes]], str], bytes]
        A callable taking codec tag and payload pairs plus a byte-order character.
    """
    def build(entries: Sequence[tuple[bytes, bytes]], endian: str = '>') -> bytes:
        count = len(entries)
        header = bytearray(struct.pack(f'{endian}II', count, 0) + b'\x00' * (count * 16))
        offset = 8 + count * 16
        body = bytearray()
        for i, (tag, payload) in enumerate(entries):
            struct.pack_into(f'{endian}I', header, 8 + i * 16, offset)
            header[8 + i * 16 + 4:8 + i * 16 + 8] = tag if endian == '>' else tag[::-1]
            struct.pack_into(f'{endian}II', header, 8 + i * 16 + 8, len(payload), len(payload))
            body += payload
            offset += len(payload)
        return bytes(header) + bytes(body)

    return build


@pytest.fixture
def make_sub_archive() -> Callable[[Sequence[bytes], str], bytes]:
    """
    Build a sub-archive of contiguous blobs.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[bytes], str], bytes]
        A callable taking the sub-blobs plus a byte-order character.
    """
    def build(subs: Sequence[bytes], endian: str = '>') -> bytes:
        table = bytearray(struct.pack(f'{endian}II', 0, 0))
        offset = 8 + len(subs) * 12
        body = bytearray()
        for sub in subs:
            table += struct.pack(f'{endian}III', 0, offset, len(sub))
            offset += len(sub)
            body += sub
        return bytes(table) + bytes(body)

    return build


@pytest.fixture
def midi_file() -> bytes:
    """
    Build a one-track standard MIDI file exercising notes, drums, and meta events.

    Returns
    -------
    bytes
        The MIDI file.
    """
    track = bytearray()
    track += bytes([0x00, 0x90, 43, 100])
    track += bytes([0x60, 0x80, 43, 0])
    track += bytes([0x00, 0x90 | 9, 36, 90])
    track += bytes([0x30, 0x80 | 9, 36, 0])
    track += bytes([0x00, 0xC0, 5])
    track += bytes([0x00, 0xFF, 0x51, 3, 0x07, 0xA1, 0x20])
    track += bytes([0x00, 0xFF, 0x2F, 0])
    return (b'MThd' + struct.pack('>IHHH', 6, 1, 1, 384) + b'MTrk' + struct.pack('>I', len(track)) +
            bytes(track))


@pytest.fixture
def alcseq_blob() -> bytes:
    """
    Build a one-track ``ALCSeq`` sequence.

    Returns
    -------
    bytes
        The sequence blob.
    """
    header = bytearray(0x44)
    struct.pack_into('>I', header, 0, 0x44)
    struct.pack_into('>I', header, 0x40, 384)
    track = bytearray()
    track += bytes([0x00, 0x90, 60, 100, 0x40])
    track += bytes([0x10, 0xB0, 7, 120])
    track += bytes([0x00, 0xFF, 0x51, 0x07, 0xA1, 0x20])
    track += bytes([0x00, 0xC0, 3])
    track += bytes([0x00, 0xFF, 0x2F])
    return bytes(header) + bytes(track)


@pytest.fixture
def palette_bytes() -> bytes:
    """
    Build a 256-entry RGBA5551 palette.

    Returns
    -------
    bytes
        The palette, 512 bytes long.
    """
    return b''.join(struct.pack('>H', (i << 8) | i | 1) for i in range(256))


@pytest.fixture
def sf2_zone() -> Sf2Zone:
    """
    Build one SoundFont instrument zone.

    Returns
    -------
    destin.xg2.typing.Sf2Zone
        The zone.
    """
    return {
        'sample': 0,
        'key_min': 0,
        'key_max': 127,
        'velocity_min': 0,
        'velocity_max': 127,
        'root': 60,
        'detune': 3,
        'pan': 70,
        'volume': 100,
        'attack': 5000,
        'decay': 20000,
        'release': 100000,
        'loop': True
    }


@pytest.fixture
def sf2_sample() -> SampleMeta:
    """
    Build one SoundFont sample.

    Returns
    -------
    destin.xg2.typing.SampleMeta
        The sample.
    """
    return {'pcm': [1, -2, 3, -4, 5], 'loop_start': 1, 'loop_end': 4}


@pytest.fixture
def sf2_preset() -> Sf2Preset:
    """
    Build one SoundFont preset.

    Returns
    -------
    destin.xg2.typing.Sf2Preset
        The preset.
    """
    return {'bank': 0, 'program': 7, 'name': 'prog007', 'instrument': 0}


@pytest.fixture
def make_albank() -> Callable[[int], bytes]:
    """
    Build an ``ALBankFile`` control bank with one melodic instrument and one sound.

    The structures occupy the first 0x180 bytes, an unframeable filler follows so the sample table
    search cannot settle on them, and the VADPCM frames sit at 0x300.

    Returns
    -------
    collections.abc.Callable[[int], bytes]
        A callable taking the sample rate and returning the bank, which is position independent.
    """
    def build(sample_rate: int = 22050, *, percussion: bool = False) -> bytes:
        blob = bytearray(0x320)
        blob[0:2] = BANK_MAGIC
        struct.pack_into('>I', blob, 4, 0x10)
        struct.pack_into('>H', blob, 0x10, 2)
        struct.pack_into('>I', blob, 0x14, sample_rate)
        struct.pack_into('>I', blob, 0x18, 0x140 if percussion else 0)
        struct.pack_into('>I', blob, 0x1C, 0x40)
        struct.pack_into('>h', blob, 0x4E, 1)
        struct.pack_into('>I', blob, 0x50, 0x80)
        struct.pack_into('>3I', blob, 0x80, 0x100, 0x110, 0xA0)
        blob[0x8C], blob[0x8D] = 64, 127
        struct.pack_into('>2I', blob, 0xA0, 0x180, 27)
        struct.pack_into('>I', blob, 0xAC, 0x120)
        struct.pack_into('>I', blob, 0xB0, 0xC0)
        struct.pack_into('>2I', blob, 0xC0, 2, 1)
        struct.pack_into('>3i', blob, 0x100, 1000, 2000, 3000)
        blob[0x110:0x116] = bytes([0, 127, 36, 96, 60, 0])
        struct.pack_into('>2I', blob, 0x120, 0, 16)
        struct.pack_into('>h', blob, 0x14E, 1)
        struct.pack_into('>I', blob, 0x150, 0x80)
        blob[0x180:0x300] = b'\xff' * 0x180
        return bytes(blob)

    return build


@pytest.fixture
def bmc_blob() -> bytes:
    """
    Build a ``BMC`` sound effect.

    Returns
    -------
    bytes
        The container.
    """
    return (BMC_MAGIC + b'engine\x00\x00\x00\x00\x00\x00' + b'\x00' * (BMC_HEADER_SIZE - 16) +
            bytes([1, 2, 3, 0xFE]))


@pytest.fixture
def make_shaw() -> Callable[[int, int], bytes]:
    """
    Build a ``shaw`` resource directory whose first record is the only usable one.

    Returns
    -------
    collections.abc.Callable[[int, int], bytes]
        A callable taking the declared record count and the container size.
    """
    def build(count: int = 5, size: int = 0x60) -> bytes:
        blob = bytearray(size)
        blob[0:4] = SHAW_MAGIC
        struct.pack_into('>I', blob, 8, count)
        struct.pack_into('>4x4I', blob, 0x0C, size - 0x20, 0, 0x10, 0)
        return bytes(blob)

    return build


@pytest.fixture
def make_dl_model() -> Callable[[Sequence[tuple[int, int]]], bytes]:
    """
    Wrap F3DEX commands in a flat model with a palette at 0x200 and pixels at 0x400.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[int, int]]], bytes]
        A callable taking the command words and returning the model.
    """
    def build(commands: Sequence[tuple[int, int]], size: int = 0x800) -> bytes:
        blob = bytearray(size)
        struct.pack_into('>I', blob, 0, 0x05000040)  # A segment-5 pointer table header.
        for index, (w0, w1) in enumerate(commands):
            struct.pack_into('>2I', blob, 0x40 + index * 8, w0, w1)
        blob[0x200:0x400] = b'\x00\x03' * 256
        blob[0x400:0x440] = bytes(range(0x40))
        return bytes(blob)

    return build


@pytest.fixture
def n64_model(make_dl_model: Callable[..., bytes]) -> bytes:
    """
    Build a flat N64 model holding one eight by eight ``CI8`` texture.

    Returns
    -------
    bytes
        The model blob.
    """
    return make_dl_model(
        ((0xFD000000, 0x05000200), (0xF0000000, 255 << 14), (0xF5000000 | (1 << 19) | (1 << 9), 0),
         (0xFD000000, 0x05000400), (0xF2000000, (0x1C << 12) | 0x1C)))


@pytest.fixture
def make_xg1_rom(make_lzss: Callable[[bytes], bytes], make_albank: Callable[..., bytes],
                 alcseq_blob: bytes) -> Callable[..., bytes]:
    """
    Build a synthetic Extreme-G 1 ROM covering every extraction path.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable returning the ROM image.
    """
    def build(*,
              mfs: Sequence[bytes] = (b'alpha', b'beta'),
              audio: bool = True,
              banks: int = 1) -> bytes:
        rom = bytearray(XG1_ROM_SIZE)
        struct.pack_into('>2I', rom, XG1_DIRECTORY_POINTER, 0x2000, 0x100)
        struct.pack_into('>I', rom, XG1_GLOBAL_TEXTURE_BANK_POINTER, XG1_TEXTURE_BANK)
        for i, base in enumerate(XG1_LEVEL_BASES):
            struct.pack_into('>I', rom, XG1_LEVEL_TABLE + i * 4, base)
        struct.pack_into('>I', rom, XG1_LEVEL_TEXTURE_BANK_TABLE, XG1_TEXTURE_BANK + 0x10000)
        code = make_lzss(BOOT_SIGNATURE + b'\x00' * 0x1C)
        struct.pack_into('>I', rom, XG1_BOOT_HEADER + 8, 0x20)
        rom[XG1_BOOT_HEADER + 0x0C:XG1_BOOT_HEADER + 0x10] = b'LZSS'
        struct.pack_into('>I', rom, XG1_BOOT_HEADER + 0x10, 0x20)
        rom[XG1_BOOT_HEADER + 0x20:XG1_BOOT_HEADER + 0x20 + len(code)] = code
        for index, base in enumerate(XG1_LEVEL_BASES):
            # Only the first container declares an object table.
            struct.pack_into('>2I', rom, base, 0x400, 2 if index == 0 else 0)
            struct.pack_into('>2I', rom, base + 0x0C, 0x100, 1)
            struct.pack_into('>2I', rom, base + 0x14, 0x200, 0x10)
            struct.pack_into('>2I', rom, base + 0x34, 0x300, 0x100001)
        struct.pack_into('>I', rom, XG1_TEXTURE_BANK, 0x40)
        struct.pack_into('>I', rom, XG1_TEXTURE_BANK + 0x10000, 0x40)
        if audio:
            rom[XG1_SEQUENCE_BASE:XG1_SEQUENCE_BASE + 4] = b'S1\x00\x01'
            struct.pack_into('>2I', rom, XG1_SEQUENCE_BASE + 4, 0x40, len(alcseq_blob))
            start = XG1_SEQUENCE_BASE + 0x40
            rom[start:start + len(alcseq_blob)] = alcseq_blob
            # A bank with no entries at all, and one whose first entry is out of range.
            rom[XG1_SEQUENCE_BASE + 0x10000:XG1_SEQUENCE_BASE + 0x10004] = b'S1\x00\x00'
            rom[XG1_SEQUENCE_BASE + 0x20000:XG1_SEQUENCE_BASE + 0x20004] = b'S1\x00\x01'
            for index in range(banks):
                bank = make_albank()
                control = 0x600000 + index * 0x10000
                rom[control:control + len(bank)] = bank
            rom[0x650000:0x650002] = BANK_MAGIC  # A magic that does not front a real bank.
        streams = [make_lzss(payload) for payload in mfs]
        table_end = XG1_MFS_TABLE + len(streams) * _MFS_RECORD_SIZE
        base = table_end - _MFS_FIRST
        struct.pack_into('>3I', rom, XG1_MFS_COUNT, len(streams), 0, _MFS_FIRST)
        start = _MFS_FIRST
        for i, (payload, stream) in enumerate(zip(mfs, streams, strict=True)):
            offset = XG1_MFS_TABLE + i * _MFS_RECORD_SIZE
            rom[offset:offset + 4] = b'LZSS'
            end = start + len(stream)
            struct.pack_into('>3I', rom, offset + 4, len(payload), len(stream), end)
            rom[base + start:base + start + len(stream)] = stream
            start = end
        return bytes(rom)

    return build


@pytest.fixture
def make_xg2_rom(make_archive: Callable[..., bytes], make_albank: Callable[..., bytes],
                 make_lzss: Callable[[bytes], bytes], alcseq_blob: bytes, bmc_blob: bytes,
                 make_shaw: Callable[..., bytes], n64_model: bytes) -> Callable[..., bytes]:
    """
    Build a synthetic Extreme-G XG2 ROM covering every extraction path.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable returning the ROM image.
    """
    def build(*, levels: Sequence[int] = XG2_LEVEL_BASES, lhuf: bool = False) -> bytes:
        rom = bytearray(XG2_ROM_SIZE)
        struct.pack_into('>I', rom, XG2_RESOURCE_TABLE, XG2_MODEL_ARCHIVE)
        struct.pack_into('>I', rom, XG2_RESOURCE_TABLE + 8, XG2_MFS_ARCHIVE)
        struct.pack_into('>I', rom, XG2_RESOURCE_TABLE + 0x10, 0x20)
        struct.pack_into('>I', rom, XG2_RESOURCE_TABLE + 0x18, XG2_ROM_SIZE - 0x20)
        struct.pack_into('>I', rom, XG2_RESOURCE_TABLE + 0x20, XG2_MODEL_ARCHIVE + 0x10000)
        # A header that passes the plausibility gate but whose records run past the image.
        struct.pack_into('>I', rom, XG2_ROM_SIZE - 0x20, 4096)
        rom[XG2_ROM_SIZE - 0x14:XG2_ROM_SIZE - 0x10] = b'LZSS'
        for i, base in enumerate(levels):
            struct.pack_into('>I', rom, XG2_LEVEL_TABLE + i * 4, base)
        boot = bytearray(make_archive([(b'LZSS', make_lzss(BOOT_SIGNATURE + b'\x00' * 0x1C))]))
        struct.pack_into('>I', boot, 0x10, 0x20)  # The entry decompresses to 0x20 bytes.
        rom[XG2_BOOT_ARCHIVE:XG2_BOOT_ARCHIVE + len(boot)] = boot
        models = make_archive([(b'COPY', n64_model),
                               (b'COPY', b'\x05\x00\x00\x00' + b'\x00' * 0x3C)])
        rom[XG2_MODEL_ARCHIVE:XG2_MODEL_ARCHIVE + len(models)] = models
        single = make_archive([(b'COPY', b'\x05\x00\x00\x00' + b'\x00' * 0x3C)])
        rom[XG2_MODEL_ARCHIVE + 0x10000:XG2_MODEL_ARCHIVE + 0x10000 + len(single)] = single
        for control in XG2_SOUNDBANKS:
            bank = make_albank()
            rom[control:control + len(bank)] = bank
        sequences = make_archive([(b'COPY', alcseq_blob)])
        rom[XG2_SEQUENCE_ARCHIVE:XG2_SEQUENCE_ARCHIVE + len(sequences)] = sequences
        entries = [(b'COPY', bmc_blob), (b'COPY', make_shaw()), (b'COPY', b'\x01\x02\x03\x04junk'),
                   (b'COPY', BMC_MAGIC + b'***' + b'\x00' * (BMC_HEADER_SIZE - 7)),
                   (b'COPY', make_shaw(1, 0x40))]
        if lhuf:
            entries.append((b'LHUF', b'unreadable'))
        mfs = make_archive(entries)
        rom[XG2_MFS_ARCHIVE:XG2_MFS_ARCHIVE + len(mfs)] = mfs
        return bytes(rom)

    return build
