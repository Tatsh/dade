"""
SoundFont 2 writer for the decoded ``ALBankFile`` banks.

The libaudio hierarchy maps onto SF2 as follows: an ``ALInstrument`` becomes a preset backed by
one instrument, each of its ``ALSound`` entries becomes an instrument zone, and every
``ALWaveTable`` becomes a sample carrying its loop points. Key and velocity ranges, root key, fine
tuning, pan, attenuation, and the volume envelope all come straight from the bank.

Melodic instruments are written to bank 0 with the program number taken from the instrument array
index. The drum kit, when the bank has one, is written to bank 128 program 0, matching where a
General MIDI player looks for channel-10 percussion.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import math
import operator
import struct

from .albank import parse_bank

if TYPE_CHECKING:
    from .typing import ParsedBank, SampleMeta, Sf2Preset, Sf2Zone, SoundZone

__all__ = ('DRUM_BANK', 'bank_to_sf2', 'build_combined', 'build_sf2', 'make_zone', 'sample_meta')

DRUM_BANK = 128
"""MIDI bank number a General MIDI player looks for percussion in.

:meta hide-value:
"""
_GUARD_SAMPLES = 46
_NAME_LENGTH = 20
_GEN_PAN = 17
_GEN_ATTACK = 34
_GEN_DECAY = 36
_GEN_RELEASE = 38
_GEN_INSTRUMENT = 41
_GEN_KEY_RANGE = 43
_GEN_VELOCITY_RANGE = 44
_GEN_ATTENUATION = 48
_GEN_TUNE = 52
_GEN_SAMPLE_ID = 53
_GEN_SAMPLE_MODES = 54
_GEN_ROOT_KEY = 58
_CENTRE_PAN = 64
_MAX_VOLUME = 127
_MAX_KEY = 127


def _timecents(microseconds: int) -> int:
    if microseconds <= 0:
        return -12000
    return max(-12000, min(8000, round(1200 * math.log2(microseconds / 1_000_000.0))))


def _riff(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack('<I', len(body)) + body + (b'\x00' if len(body) & 1 else b'')


def _name_bytes(name: str) -> bytes:
    raw = name.encode()[:_NAME_LENGTH]
    return raw + b'\x00' * (_NAME_LENGTH - len(raw))


def _zstr_even(value: str) -> bytes:
    raw = value.encode() + b'\x00'
    return raw + b'\x00' if len(raw) & 1 else raw


def _generator(op: int, amount: int) -> bytes:
    return struct.pack('<HH', op, amount & 0xFFFF)


def _zone_generators(zone: Sf2Zone) -> bytes:
    """
    Build the generator list for one instrument zone.

    Returns
    -------
    bytes
        The generators, with ``sampleID`` last as the specification requires.
    """
    out = _generator(_GEN_KEY_RANGE, zone['key_min'] | (zone['key_max'] << 8))
    out += _generator(_GEN_VELOCITY_RANGE, zone['velocity_min'] | (zone['velocity_max'] << 8))
    out += _generator(_GEN_ROOT_KEY, zone['root'])
    if zone['detune']:
        out += _generator(_GEN_TUNE, zone['detune'])
    if zone['pan'] != _CENTRE_PAN:
        out += _generator(_GEN_PAN, int((zone['pan'] - _CENTRE_PAN) / 64.0 * 500))
    attenuation = int((_MAX_VOLUME - zone['volume']) * 0.375 * 10)
    if attenuation:
        out += _generator(_GEN_ATTENUATION, attenuation)
    out += _generator(_GEN_ATTACK, _timecents(zone['attack']))
    if zone['decay'] > 0:
        out += _generator(_GEN_DECAY, _timecents(zone['decay']))
    out += _generator(_GEN_RELEASE, _timecents(zone['release']) if zone['release'] > 0 else 1000)
    if zone['loop']:
        out += _generator(_GEN_SAMPLE_MODES, 1)
    return out + _generator(_GEN_SAMPLE_ID, zone['sample'])


def build_sf2(samples: list[SampleMeta], instruments: list[list[Sf2Zone]], presets: list[Sf2Preset],
              sample_rate: int, name: str) -> bytes:
    """
    Assemble a SoundFont 2 file.

    Parameters
    ----------
    samples : list[destin.xg2.typing.SampleMeta]
        PCM and loop points for every sample, in SoundFont sample order.
    instruments : list[list[destin.xg2.typing.Sf2Zone]]
        Each instrument as a list of zones.
    presets : list[destin.xg2.typing.Sf2Preset]
        Presets, each naming an index into *instruments*. They are sorted by bank and program.
    sample_rate : int
        Playback rate written into every sample header.
    name : str
        Name recorded in the ``INAM`` chunk.

    Returns
    -------
    bytes
        The complete SoundFont file.
    """
    smpl = bytearray()
    headers: list[tuple[int, int, int, int]] = []
    for sample in samples:
        start = len(smpl) // 2
        for value in sample['pcm']:
            smpl += struct.pack('<h', value)
        end = len(smpl) // 2
        smpl += b'\x00\x00' * _GUARD_SAMPLES
        headers.append((start, end, sample['loop_start'], sample['loop_end']))
    sdta = _riff(b'LIST', b'sdta' + _riff(b'smpl', bytes(smpl)))

    inst = bytearray()
    ibag = bytearray()
    igen = bytearray()
    bag_index = 0
    gen_index = 0
    for index, zones in enumerate(instruments):
        inst += _name_bytes(f'i{index:03d}') + struct.pack('<H', bag_index)
        for zone in zones:
            ibag += struct.pack('<HH', gen_index, 0)
            bag_index += 1
            generators = _zone_generators(zone)
            igen += generators
            gen_index += len(generators) // 4
    inst += _name_bytes('EOI') + struct.pack('<H', bag_index)
    ibag += struct.pack('<HH', gen_index, 0)
    igen += b'\x00' * 4

    phdr = bytearray()
    pbag = bytearray()
    pgen = bytearray()
    bag_index = 0
    gen_index = 0
    for preset in sorted(presets, key=operator.itemgetter('bank', 'program')):
        phdr += _name_bytes(preset['name']) + struct.pack('<HHHIII', preset['program'],
                                                          preset['bank'], bag_index, 0, 0, 0)
        pbag += struct.pack('<HH', gen_index, 0)
        bag_index += 1
        pgen += _generator(_GEN_INSTRUMENT, preset['instrument'])
        gen_index += 1
    phdr += _name_bytes('EOP') + struct.pack('<HHHIII', 0, 0, bag_index, 0, 0, 0)
    pbag += struct.pack('<HH', gen_index, 0)
    pgen += b'\x00' * 4

    shdr = bytearray()
    for index, (start, end, loop_start, loop_end) in enumerate(headers):
        length = end - start
        low = min(loop_start, length)
        high = min(loop_end, length) if loop_end else length
        if high <= low:
            low, high = 0, length
        shdr += _name_bytes(f's{index:03d}') + struct.pack('<IIIIIBbHH', start, end, start + low,
                                                           start + high, sample_rate, 60, 0, 0, 1)
    shdr += _name_bytes('EOS') + struct.pack('<IIIIIBbHH', 0, 0, 0, 0, 0, 0, 0, 0, 0)

    pdta = b'pdta'
    for tag, body in ((b'phdr', phdr), (b'pbag', pbag), (b'pmod', bytearray(
            b'\x00' * 10)), (b'pgen', pgen), (b'inst', inst), (b'ibag', ibag),
                      (b'imod', bytearray(b'\x00' * 10)), (b'igen', igen), (b'shdr', shdr)):
        pdta += _riff(tag, bytes(body))
    info = _riff(
        b'LIST', b'INFO' + _riff(b'ifil', struct.pack('<HH', 2, 1)) +
        _riff(b'isng', _zstr_even('EMU8000')) + _riff(b'INAM', _zstr_even(name)))
    return _riff(b'RIFF', b'sfbk' + info + sdta + _riff(b'LIST', pdta))


def sample_meta(bank: ParsedBank) -> list[SampleMeta]:
    """
    Collect PCM and loop points for every sample in a bank.

    Parameters
    ----------
    bank : destin.xg2.typing.ParsedBank
        A parsed control bank.

    Returns
    -------
    list[destin.xg2.typing.SampleMeta]
        One entry per decoded sample, carrying the loop points of the zone that uses it.
    """
    meta: list[SampleMeta] = [{
        'pcm': pcm,
        'loop_start': 0,
        'loop_end': 0
    } for pcm in bank['samples']]
    for zones in [*bank['instruments'], bank['percussion']]:
        for zone in zones:
            meta[zone['sample']] = {
                'pcm': bank['samples'][zone['sample']],
                'loop_start': zone['loop_start'],
                'loop_end': zone['loop_end']
            }
    return meta


def make_zone(zone: SoundZone,
              sample_offset: int = 0,
              *,
              key_min: int | None = None,
              key_max: int | None = None,
              root: int | None = None,
              loop: bool | None = None) -> Sf2Zone:
    """
    Convert a bank sound zone to a SoundFont instrument zone.

    Parameters
    ----------
    zone : destin.xg2.typing.SoundZone
        The bank zone to convert.
    sample_offset : int
        Added to the zone's sample index, for banks merged into one sample pool.
    key_min : int | None
        Replacement lowest key, used when a drum kit is spread across the keyboard.
    key_max : int | None
        Replacement highest key.
    root : int | None
        Replacement root key.
    loop : bool | None
        Replacement loop flag; drum zones are written without looping.

    Returns
    -------
    destin.xg2.typing.Sf2Zone
        The converted zone.
    """
    return {
        'sample': sample_offset + zone['sample'],
        'key_min': zone['key_min'] if key_min is None else key_min,
        'key_max': zone['key_max'] if key_max is None else key_max,
        'velocity_min': zone['velocity_min'],
        'velocity_max': zone['velocity_max'],
        'root': zone['key_base'] if root is None else root,
        'detune': zone['detune'],
        'pan': zone['pan'],
        'volume': zone['volume'],
        'attack': zone['attack'],
        'decay': zone['decay'],
        'release': zone['release'],
        'loop': zone['loop'] if loop is None else loop
    }


def bank_to_sf2(bank: ParsedBank, name: str) -> bytes | None:
    """
    Build a SoundFont from one parsed bank's melodic instruments.

    Parameters
    ----------
    bank : destin.xg2.typing.ParsedBank
        A parsed control bank.
    name : str
        Name recorded in the SoundFont.

    Returns
    -------
    bytes | None
        The SoundFont, or ``None`` when the bank has no playable instrument.
    """
    instruments: list[list[Sf2Zone]] = []
    presets: list[Sf2Preset] = []
    for program, zones in enumerate(bank['instruments']):
        if not zones:
            continue
        presets.append({
            'bank': 0,
            'program': program,
            'name': f'prog{program:03d}',
            'instrument': len(instruments)
        })
        instruments.append([make_zone(zone) for zone in zones])
    if not presets:
        return None
    return build_sf2(sample_meta(bank), instruments, presets, bank['sample_rate'], name)


def build_combined(rom: bytes,
                   melodic: int,
                   drums: int | None = None,
                   name: str = 'ExtremeG',
                   drum_key_offset: int = 0) -> bytes:
    """
    Build one SoundFont holding a bank's melodic instruments and its drum kit.

    Melodic instruments go to bank 0 with the program taken from the instrument array index. The
    drum kit is read from the bank's own percussion pointer, where each sound already carries its
    key range and root; *drums* is used only as a fallback for a bank without one, in which case
    each of its first instrument's sounds is spread across consecutive keys.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    melodic : int
        Offset of the melodic control bank.
    drums : int | None
        Offset of a fallback drum control bank.
    name : str
        Name recorded in the SoundFont.
    drum_key_offset : int
        Subtracted from the fallback kit's sound index to place it on the keyboard.

    Returns
    -------
    bytes
        The SoundFont.

    Raises
    ------
    ValueError
        If the melodic bank could not be parsed.
    """
    bank = parse_bank(rom, melodic)
    if bank is None:
        msg = f'No ALBankFile could be parsed at 0x{melodic:X}.'
        raise ValueError(msg)
    samples = sample_meta(bank)
    instruments: list[list[Sf2Zone]] = []
    presets: list[Sf2Preset] = []
    for program, zones in enumerate(bank['instruments']):
        if not zones:
            continue
        presets.append({
            'bank': 0,
            'program': program,
            'name': f'prog{program:03d}',
            'instrument': len(instruments)
        })
        instruments.append([make_zone(zone) for zone in zones])
    kit = [
        make_zone(zone, loop=False) for zone in bank['percussion']
        if 0 <= zone['key_min'] <= _MAX_KEY
    ]
    if not kit and drums is not None:
        fallback = parse_bank(rom, drums)
        if fallback is not None:
            offset = len(samples)
            samples += sample_meta(fallback)
            zones = fallback['instruments'][0] if fallback['instruments'] else []
            kit = [
                make_zone(zone,
                          offset,
                          key_min=index - drum_key_offset,
                          key_max=index - drum_key_offset,
                          root=index - drum_key_offset,
                          loop=False) for index, zone in enumerate(zones)
                if 0 <= index - drum_key_offset <= _MAX_KEY
            ]
    if kit:
        presets.append({
            'bank': DRUM_BANK,
            'program': 0,
            'name': 'Drums',
            'instrument': len(instruments)
        })
        instruments.append(kit)
    return build_sf2(samples, instruments, presets, bank['sample_rate'], name)
