"""
Dreamcast sound converters: Manatee ``.OSB`` banks to WAV and ``.MLT`` containers to JSON.

Both are part of Sega's Manatee / ``libsg_sd`` AICA pipeline. An ``.OSB`` is a speech/SFX bank of
SOSP voice records (4-bit Yamaha/AICA ADPCM); an ``.MLT`` (``SMLT``) is a multi-unit container whose
unit table is decoded to JSON.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging
import struct
import wave

from ._base import ConversionError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('mlt_to_json', 'osb_to_wav')

log = logging.getLogger(__name__)

_OSB_MAGIC = b'SOSB'
_SOSP_MAGIC = b'SOSP'
_MLT_MAGIC = b'SMLT'
_OSB_HEADER = struct.Struct('<4sIII')
_SOSP = struct.Struct('<4sHHHH')
_U32 = struct.Struct('<I')
_MLT_HEADER = struct.Struct('<4sII')
_MLT_UNIT = struct.Struct('<4sIIIIIII')
_MLT_UNIT_TABLE_OFFSET = 0x20
_BASE_RATE = 44100
_PITCH_OFFSET = 0x10
_OCTAVE_SIGN_THRESHOLD = 8
_OCTAVE_MODULUS = 16
_SCALE_LUT = (0x0e6, 0x0e6, 0x0e6, 0x0e6, 0x133, 0x199, 0x200, 0x266) * 2


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _decode_adpcm(data: bytes, start: int, samples: int) -> bytes:
    out = bytearray()
    current = 0
    step = 0x7f
    for i in range(samples):
        byte = data[start + (i >> 1)]
        nibble = (byte >> 4) if (i & 1) else (byte & 0xf)
        delta = ((2 * (nibble & 7) + 1) * step) >> 3
        if nibble & 8:
            delta = -delta
        current = _clamp(current + delta, -32768, 32767)
        step = _clamp((step * _SCALE_LUT[nibble]) >> 8, 0x7f, 0x6000)
        out += struct.pack('<h', current)
    return bytes(out)


def _sample_rate(pitch: int) -> int:
    octave = (pitch >> 11) & 0xf
    if octave >= _OCTAVE_SIGN_THRESHOLD:
        octave -= _OCTAVE_MODULUS
    fns = pitch & 0x7ff
    return round(_BASE_RATE * (2.0 ** octave) * (1.0 + fns / 1024.0))


def _iter_osb_records(data: bytes) -> Iterator[tuple[int, int, int]]:
    magic, _, _, count = _OSB_HEADER.unpack_from(data, 0)
    if magic != _OSB_MAGIC:
        msg = 'Not an OSB sound bank (missing SOSB magic).'
        raise ConversionError(msg)
    for i in range(count):
        record = _U32.unpack_from(data, 0x10 + i * _U32.size)[0]
        sosp_magic, play_control, sa_lo, _, lea = _SOSP.unpack_from(data, record)
        if sosp_magic != _SOSP_MAGIC:
            continue
        start = ((play_control & 0x1f) << 16) | sa_lo
        pitch = struct.unpack_from('<H', data, record + _PITCH_OFFSET)[0]
        yield (start, lea, _sample_rate(pitch))


def osb_to_wav(source: Path, dest_dir: Path) -> tuple[Path, ...]:
    """
    Convert a Dreamcast ``.OSB`` Manatee sound bank to one WAV per voice record.

    The WAVs are written to a directory named after the bank stem inside *dest_dir*. Each record is
    4-bit AICA ADPCM, decoded to signed 16-bit mono PCM.

    Parameters
    ----------
    source : Path
        The source ``.OSB`` file.
    dest_dir : Path
        The directory the per-bank WAV directory is created in.

    Returns
    -------
    tuple[Path, ...]
        The written WAV paths.
    """
    data = source.read_bytes()
    bank_dir = dest_dir / source.stem
    bank_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for index, (start, samples, rate) in enumerate(_iter_osb_records(data)):
        if start + ((samples + 1) >> 1) > len(data):
            log.warning('OSB record %d in `%s` runs past the end of the file; skipping.', index,
                        source.name)
            continue
        destination = bank_dir / f'{source.stem}_{index:03d}.wav'
        with wave.open(str(destination), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(_decode_adpcm(data, start, samples))
        written.append(destination)
    return tuple(written)


def mlt_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert a Dreamcast ``.MLT`` (``SMLT``) multi-unit sound container to JSON.

    Parameters
    ----------
    source : Path
        The source ``.MLT`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.

    Raises
    ------
    ConversionError
        If the file is not an SMLT container.
    """
    data = source.read_bytes()
    magic, version, count = _MLT_HEADER.unpack_from(data, 0)
    if magic != _MLT_MAGIC:
        msg = 'Not an MLT container (missing SMLT magic).'
        raise ConversionError(msg)
    units = []
    for i in range(count):
        (kind, bank, aica_addr, aica_size, file_off, file_size, _, _) = _MLT_UNIT.unpack_from(
            data, _MLT_UNIT_TABLE_OFFSET + i * _MLT_UNIT.size)
        units.append({
            'aica_addr': aica_addr,
            'aica_size': aica_size,
            'bank': bank,
            'file_offset': file_off,
            'file_size': file_size,
            'type': kind.decode('ascii', errors='replace'),
        })
    obj = {'unit_count': count, 'units': units, 'version': version}
    destination = dest_dir / f'{source.stem}.json'
    destination.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return destination
