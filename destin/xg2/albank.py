"""
The Nintendo 64 libaudio ``ALBankFile`` control bank, as shipped by both Extreme-G games.

A control bank begins with the magic ``B1`` and describes a hierarchy of instruments, sounds, key
maps, envelopes, and wave tables. The sample data itself lives in a separate table embedded after
the structures, which is located by :py:func:`~destin.xg2.vadpcm.find_table_base`.

The hierarchy maps onto SoundFont concepts directly: an ``ALInstrument`` becomes a preset, an
``ALSound`` becomes an instrument zone, an ``ALWaveTable`` becomes a sample, and ``ALKeyMap`` and
``ALEnvelope`` supply the zone's ranges and volume envelope. The bank's separate percussion
pointer is the channel-9 drum kit, which libaudio routes to without a program change.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from .vadpcm import decode_vadpcm, find_table_base, read_codebook

if TYPE_CHECKING:
    from .typing import ParsedBank, SoundZone

__all__ = ('BANK_MAGIC', 'parse_bank')

BANK_MAGIC = b'B1'
"""Magic introducing an ``ALBankFile``.

:meta hide-value:
"""
_MAX_OFFSET = 0x60000
_MAX_INSTRUMENTS = 512
_MIN_RATE = 8000
_MAX_RATE = 48000
_EXPECTED_ORDER = 2


def _u32(rom: bytes, control: int, offset: int) -> int:
    return int(struct.unpack_from('>I', rom, control + offset)[0])


def _read_key_map(rom: bytes, control: int, offset: int) -> tuple[int, int, int, int, int, int]:
    """
    Read an ``ALKeyMap``, falling back to a full-range default.

    Returns
    -------
    tuple[int, int, int, int, int, int]
        The velocity range, key range, root key, and fine tuning in cents.
    """
    if not 0 < offset < _MAX_OFFSET:
        return 0, 127, 0, 127, 60, 0
    velocity_min, velocity_max, key_min, key_max, key_base = rom[control + offset:control + offset +
                                                                 5]
    detune = struct.unpack_from('>b', rom, control + offset + 5)[0]
    return velocity_min, velocity_max, key_min, key_max, key_base, detune


def _read_envelope(rom: bytes, control: int, offset: int) -> tuple[int, int, int]:
    """
    Read an ``ALEnvelope``, falling back to zeroes.

    Returns
    -------
    tuple[int, int, int]
        The attack, decay, and release times in microseconds.
    """
    if not 0 < offset < _MAX_OFFSET:
        return 0, 0, 0
    attack, decay, release = struct.unpack_from('>3i', rom, control + offset)
    return attack, decay, release


def _read_loop(rom: bytes, control: int, offset: int) -> tuple[int, int]:
    """
    Read an ``ALADPCMloop``, falling back to zeroes.

    Returns
    -------
    tuple[int, int]
        The loop start and end in samples. They are equal when the sound does not loop.
    """
    if not 0 < offset < _MAX_OFFSET:
        return 0, 0
    start, end = struct.unpack_from('>2I', rom, control + offset)
    return start, end


def _parse_sound(rom: bytes, control: int, offset: int, raw: list[tuple[int, int, list[int], int,
                                                                        int]]) -> SoundZone | None:
    """
    Parse one ``ALSound`` into a zone, appending its sample descriptor to *raw*.

    Returns
    -------
    destin.xg2.typing.SoundZone | None
        The zone, or ``None`` when the sound is malformed.
    """
    if not 0 < offset < _MAX_OFFSET:
        return None
    wave_table = _u32(rom, control, offset + 8)
    if not 0 < wave_table < _MAX_OFFSET:
        return None
    base = _u32(rom, control, wave_table)
    length = _u32(rom, control, wave_table + 4)
    kind = rom[control + wave_table + 8]
    book = _u32(rom, control, wave_table + 0x10)
    if kind != 0 or not 0 < book < _MAX_OFFSET:
        return None
    order, predictors = _u32(rom, control, book), _u32(rom, control, book + 4)
    if order != _EXPECTED_ORDER:
        return None
    key_map = _read_key_map(rom, control, _u32(rom, control, offset + 4))
    envelope = _read_envelope(rom, control, _u32(rom, control, offset))
    loop_start, loop_end = _read_loop(rom, control, _u32(rom, control, wave_table + 0xC))
    index = len(raw)
    raw.append((base, length, read_codebook(rom, control + book, order,
                                            predictors), order, predictors))
    return {
        'sample': index,
        'key_min': key_map[2],
        'key_max': key_map[3],
        'velocity_min': key_map[0],
        'velocity_max': key_map[1],
        'key_base': key_map[4],
        'detune': key_map[5],
        'loop_start': loop_start,
        'loop_end': loop_end,
        'loop': loop_end > loop_start,
        'pan': rom[control + offset + 0xC],
        'volume': rom[control + offset + 0xD],
        'attack': envelope[0],
        'decay': envelope[1],
        'release': envelope[2]
    }


def _parse_instrument(rom: bytes, control: int, offset: int,
                      raw: list[tuple[int, int, list[int], int, int]]) -> list[SoundZone]:
    """
    Parse one ``ALInstrument`` into its list of zones.

    Returns
    -------
    list[destin.xg2.typing.SoundZone]
        The zones, skipping any that are malformed.
    """
    count = struct.unpack_from('>h', rom, control + offset + 0xE)[0]
    zones = []
    for i in range(max(0, count)):
        zone = _parse_sound(rom, control, _u32(rom, control, offset + 0x10 + i * 4), raw)
        if zone is not None:
            zones.append(zone)
    return zones


def parse_bank(rom: bytes, control: int) -> ParsedBank | None:
    """
    Parse an ``ALBankFile`` control bank and decode every sound it references.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    control : int
        Offset of the control bank.

    Returns
    -------
    destin.xg2.typing.ParsedBank | None
        The parsed bank, or ``None`` when *control* does not hold a plausible bank or its sample
        table could not be located.
    """
    if rom[control:control + 2] != BANK_MAGIC:
        return None
    bank_offset = _u32(rom, control, 4)
    sample_rate = _u32(rom, control, bank_offset + 4)
    count = struct.unpack_from('>H', rom, control + bank_offset)[0]
    if not 0 < count < _MAX_INSTRUMENTS or not _MIN_RATE <= sample_rate <= _MAX_RATE:
        return None
    raw: list[tuple[int, int, list[int], int, int]] = []
    instruments = []
    for i in range(count):
        offset = _u32(rom, control, bank_offset + 0xC + i * 4)
        instruments.append(
            _parse_instrument(rom, control, offset, raw) if 0 < offset < _MAX_OFFSET else [])
    percussion_offset = _u32(rom, control, bank_offset + 8)
    percussion = (_parse_instrument(rom, control, percussion_offset, raw)
                  if 0 < percussion_offset < _MAX_OFFSET else [])
    table = find_table_base(rom, control, [(base, length) for base, length, _, _, _ in raw])
    if table is None:
        return None
    return {
        'sample_rate':
            sample_rate,
        'instruments':
            instruments,
        'percussion':
            percussion,
        'samples': [
            decode_vadpcm(rom[table + base:table + base + length], coefficients, order, predictors)
            for base, length, coefficients, order, predictors in raw
        ]
    }
