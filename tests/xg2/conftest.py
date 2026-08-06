"""Fixtures for the :py:mod:`destin.xg2` tests."""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from destin.xg2.typing import SampleMeta, Sf2Preset, Sf2Zone


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
