"""
Shared pytest configuration for the ``destin.ddrsplus`` suite.

Every fixture builds its sample file from scratch, so the suite needs no copy of the game.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.ddrsplus.bfcodec import encipher
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

MUSIC_ID = 259
"""Music id the sample container carries."""
NAME_JAPANESE = 'All My Love'
"""Japanese title the sample container carries."""
NAME_ENGLISH = 'All My Love'
"""English title the sample container carries."""
ARTIST = 'kors k feat.ЯIRE'
"""Artist the sample container carries, chosen so it exercises multi-byte text."""
LEVELS = (2, 5, 8, 10, 2, 5)
"""Foot ratings the sample container carries: four standard, then two Shake."""
MAX_COMBOS = (74, 155, 207, 284)
"""Max combo per difficulty slot in the sample standard table."""
BANNER_WIDTH = 256
"""Width of the sample banner texture."""
BANNER_HEIGHT = 64
"""Height of the sample banner texture."""

_STRING_FIELD = 72
_NO_OVERRIDE = 0xFF
_DIRECTORY_PAIRS = 8
_TICKS_PER_MEASURE = 4096
_PVR_TAG = 0x21525650
_PVR_HEADER = 52


def _string_field(text: str) -> bytes:
    """
    Build one 73-byte text field.

    Parameters
    ----------
    text : str
        The text to store.

    Returns
    -------
    bytes
        The length byte followed by 72 bytes of NUL-padded UTF-8.
    """
    encoded = text.encode()
    return bytes([len(text)]) + encoded + bytes(_STRING_FIELD - len(encoded))


@pytest.fixture
def make_metadata() -> Callable[..., bytes]:
    """
    Build a section 5 payload.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``music_id``, ``levels``, and ``overrides`` values.
    """
    def build(*,
              levels: Sequence[int] = LEVELS,
              music_id: int = MUSIC_ID,
              overrides: Sequence[Sequence[int]] = ()) -> bytes:
        rows = tuple(overrides) or ((_NO_OVERRIDE,) * 5,) * len(levels)
        return (struct.pack('>H', music_id) + _string_field(NAME_JAPANESE) +
                _string_field(NAME_ENGLISH) + _string_field(ARTIST) + b'\0' +
                b''.join(bytes([level, *row]) for level, row in zip(levels, rows, strict=True)))

    return build


@pytest.fixture
def make_chart_table() -> Callable[..., bytes]:
    """
    Build a section 6 or 7 payload.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``combos`` and header values.
    """
    def build(*,
              combos: Sequence[int] = MAX_COMBOS,
              max_bpm: int = 159,
              measures: int = 65,
              min_bpm: int = 158,
              music_time: int = 98) -> bytes:
        return struct.pack('<4H', music_time, measures, max_bpm, min_bpm) + b''.join(
            struct.pack('<H', combo) + bytes((index, 1, 0, 2, 1))
            for index, combo in enumerate(combos))

    return build


@pytest.fixture
def make_ssq() -> Callable[..., bytes]:
    """
    Build an SSQ file holding a tempo map and one chart per parameter given.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``parameters``, ``steps``, ``ticks``, and tempo values.
    """
    def build(
        *,
        beats: Sequence[int] = (0, 262144),
        frames_per_second: int = 150,
        parameters: Sequence[int] = (0x0114,),
        steps: Sequence[int] = (1, 2, 0, 4),
        ticks: Sequence[int] = (0, 1024, 2048, 3072),
        times: Sequence[int] = (0, 14583)
    ) -> bytes:
        tempo_body = (struct.pack('<I', len(beats)) + struct.pack(f'<{len(beats)}i', *beats) +
                      struct.pack(f'<{len(times)}i', *times))
        out = struct.pack('<IHH', 8 + len(tempo_body), 1, frames_per_second) + tempo_body
        freezes = sum(1 for step in steps if step == 0)
        for parameter in parameters:
            body = (struct.pack('<I', len(ticks)) + struct.pack(f'<{len(ticks)}I', *ticks) +
                    bytes(steps) + bytes(len(steps) % 2) + b'\x01\x01' * freezes)
            body += bytes(-len(body) % 4)
            out += struct.pack('<IHH', 8 + len(body), 3, parameter) + body
        return out + bytes(4)

    return build


@pytest.fixture
def make_pvr() -> Callable[..., bytes]:
    """
    Build an uncompressed RGBA4444 PowerVR texture.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``width``, ``height``, and ``fill`` values.
    """
    def build(*,
              fill: int = 0xD4FF,
              height: int = BANNER_HEIGHT,
              width: int = BANNER_WIDTH) -> bytes:
        return struct.pack('<13I', _PVR_HEADER, height, width, 0, 0x8010, width * height * 2, 16,
                           0xF000, 0x0F00, 0x00F0, 0x000F, _PVR_TAG,
                           1) + struct.pack('<H', fill) * (width * height)

    return build


@pytest.fixture
def make_gen(make_chart_table: Callable[..., bytes], make_metadata: Callable[..., bytes],
             make_pvr: Callable[..., bytes], make_ssq: Callable[...,
                                                                bytes]) -> Callable[..., bytes]:
    """
    Build a whole ``.gen`` container.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking a keyword ``sections`` mapping to override any slot's payload, and a
        keyword ``enciphered`` iterable naming which slots to encipher.
    """
    def build(*,
              enciphered: Sequence[int] = (0, 1, 3, 4),
              sections: dict[int, bytes] | None = None) -> bytes:
        payloads = {
            0: b'\xff\xfb\x90\x64' + bytes(60),
            1: b'\xff\xfb\x90\x44' + bytes(28),
            2: make_pvr(),
            3: make_ssq(parameters=(0x0414, 0x0114)),
            4: make_ssq(parameters=(0x0114,)),
            5: make_metadata(),
            6: make_chart_table(),
            7: make_chart_table(combos=(0, 74, 155, 0))
        }
        payloads.update(sections or {})
        stored = {
            index: encipher(payload) if index in enciphered else payload
            for index, payload in payloads.items()
        }
        directory = bytearray(_DIRECTORY_PAIRS * 8)
        offset = len(directory)
        for index in sorted(stored):
            struct.pack_into('<II', directory, index * 8, offset, len(stored[index]))
            offset += len(stored[index])
        return bytes(directory) + b''.join(stored[index] for index in sorted(stored))

    return build


@pytest.fixture
def fake_ffmpeg(tmp_path: Path) -> Path:
    """
    Stand in for ``ffmpeg`` when decoding audio, writing signed 16-bit mono PCM to standard output.

    The stream is a tenth of a second at 44100 Hz: silence for the first half, then a loud tone,
    so :py:func:`~destin.ddrsplus.gap.first_audible` lands near its midpoint.

    Returns
    -------
    pathlib.Path
        The executable script.
    """
    path = tmp_path / 'ffmpeg-pcm'
    path.write_text('#!/usr/bin/env python3\n'
                    'import struct\n'
                    'import sys\n'
                    'quiet = struct.pack("<2205h", *([0] * 2205))\n'
                    'loud = struct.pack("<2205h", *([15000, -15000] * 1102 + [15000]))\n'
                    'sys.stdout.buffer.write(quiet + loud)\n')
    path.chmod(0o755)
    return path
