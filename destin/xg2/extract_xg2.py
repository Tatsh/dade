"""
Full asset extraction for Extreme-G XG2 (N64, USA).

XG2 keeps almost everything in ``XG2Arch`` containers. The ``mfs`` archive holds named sound
effects and resource directories, a separate container holds the music sequences uncompressed, and
the master resource table indexes the model archives where most of the game's textures live. Level
containers are written out raw, as their internal layout has not been reversed.

The music is sequenced rather than streamed, in the same ``ALCSeq`` format the first game uses, so
the same converter handles both. XG2 is not General MIDI: it uses channel 10 as an ordinary bass
part, which a General MIDI player would force to percussion, so that channel is moved aside when a
free one exists.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

from .albank import parse_bank
from .alcseq import to_midi
from .archive import decode_entries, parse_archive
from .bmc import DEFAULT_SAMPLE_RATE, decode_bmc_dpcm, parse_bmc
from .fluidsynth import render_directory
from .images import write_png
from .models import collect_textures
from .offsets import XG2_MELODIC_BANK, XG2_MFS_ARCHIVE, XG2_SEQUENCE_ARCHIVE, XG2_SOUNDBANKS
from .rom import xg2_boot, xg2_level_bases, xg2_resource_archives
from .smf import DRUM_CHANNEL, remap_channel, used_channels
from .soundfont import bank_to_sf2
from .wav import pcm_to_bytes, write_wav16

if TYPE_CHECKING:
    from pathlib import Path

    from .typing import Texture

__all__ = ('SHAW_MAGIC', 'iter_model_blobs', 'run', 'unpack')

log = logging.getLogger(__name__)

SHAW_MAGIC = b'shaw'
"""Magic introducing a resource directory in the ``mfs`` archive.

:meta hide-value:
"""
_SHAW_RECORD_SIZE = 0x14
_SHAW_TABLE_START = 0x0C
_MAX_LEVEL_SIZE = 0x200000
_FALLBACK_LEVEL_SIZE = 0x80000
_MIDI_CHANNELS = 16


def _sanitise(name: str, index: int) -> str:
    cleaned = ''.join(c if (c.isalnum() or c in '._-') else '_' for c in name).strip('_')
    return cleaned or f'unnamed_{index:03d}'


def _extract_levels(rom: bytes, out: Path) -> int:
    directory = out / 'levels'
    directory.mkdir(parents=True, exist_ok=True)
    bases = xg2_level_bases(rom)
    bounds = [*bases, min(XG2_SOUNDBANKS)]
    for index, base in enumerate(bases):
        size = bounds[index + 1] - base
        if size <= 0 or size > _MAX_LEVEL_SIZE:
            size = _FALLBACK_LEVEL_SIZE
        (directory / f'level_{index:02d}_{base:07X}.bin').write_bytes(rom[base:base + size])
    return len(bases)


def _extract_sequences(rom: bytes, out: Path, *, convert: bool) -> tuple[int, int]:
    directory = out / 'audio' / 'sequences'
    directory.mkdir(parents=True, exist_ok=True)
    sequences = midis = 0
    for entry, blob in decode_entries(rom, parse_archive(rom, XG2_SEQUENCE_ARCHIVE)):
        (directory / f'seq{entry["index"]:02d}.seq').write_bytes(blob)
        sequences += 1
        if not convert:
            continue
        try:
            midi, tracks = to_midi(blob)
        except (IndexError, struct.error):
            log.warning('Sequence %d could not be converted to MIDI.', entry['index'])
            continue
        if not tracks:
            continue
        used = used_channels(midi)
        if DRUM_CHANNEL in used:
            free = [c for c in range(_MIDI_CHANNELS) if c != DRUM_CHANNEL and c not in used]
            if free:
                midi = remap_channel(midi, DRUM_CHANNEL, free[0])
        (directory / f'seq{entry["index"]:02d}.mid').write_bytes(midi)
        midis += 1
    return sequences, midis


def _extract_soundbanks(rom: bytes, out: Path, *, convert: bool) -> tuple[int, int]:
    audio = out / 'audio'
    audio.mkdir(parents=True, exist_ok=True)
    wavs = soundfonts = 0
    for control in XG2_SOUNDBANKS:
        bank = parse_bank(rom, control)
        if bank is None:
            log.warning('The bank at 0x%X did not parse.', control)
            continue
        directory = audio / f'bank_{control:07X}'
        directory.mkdir(parents=True, exist_ok=True)
        for index, pcm in enumerate(bank['samples']):
            if not pcm:
                continue
            (directory / f'smp{index:03d}.raw').write_bytes(pcm_to_bytes(pcm))
            if convert:
                write_wav16(directory / f'smp{index:03d}.wav', pcm, bank['sample_rate'])
                wavs += 1
        if convert and control == XG2_MELODIC_BANK:
            soundfont = bank_to_sf2(bank, f'XG2_{control:07X}')
            if soundfont is not None:
                (audio / f'bank_{control:07X}.sf2').write_bytes(soundfont)
                soundfonts += 1
    return wavs, soundfonts


def _extract_shaw(blob: bytes, directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '_container.bin').write_bytes(blob)
    count = struct.unpack_from('>I', blob, 8)[0]
    dumped = 0
    position = _SHAW_TABLE_START
    for index in range(count):
        if position + _SHAW_RECORD_SIZE > len(blob):
            break
        offset, _second, size, _padding = struct.unpack_from('>4x4I', blob, position)
        if 0 < offset < len(blob) and 0 < size <= len(blob) - offset:
            (directory / f'res{index:03d}_{offset:07X}.bin').write_bytes(blob[offset:offset + size])
            dumped += 1
        position += _SHAW_RECORD_SIZE
    return dumped


def _extract_mfs(rom: bytes, out: Path, *, convert: bool, rate: int) -> dict[str, int]:
    root = out / 'mfs'
    root.mkdir(parents=True, exist_ok=True)
    counts = {'bmc': 0, 'shaw': 0, 'other': 0, 'wav': 0}
    manifest = ['# index  rom_offset  codec  kind   detail']
    for entry, blob in decode_entries(rom, parse_archive(rom, XG2_MFS_ARCHIVE)):
        index = entry['index']
        sound = parse_bmc(blob)
        if sound is not None:
            counts['bmc'] += 1
            stem = f'aud{index:03d}_{_sanitise(sound.name, index)}'
            (root / f'{stem}.bin').write_bytes(blob)
            if convert and sound.data:
                write_wav16(root / f'{stem}.wav', decode_bmc_dpcm(sound.data), rate)
                counts['wav'] += 1
            manifest.append(f'{index:5d}  0x{entry["absolute"]:07X}  {entry["codec"]:<5s}  BMC    '
                            f'{sound.name!r} pcm={len(sound.data)}')
        elif blob[:4] == SHAW_MAGIC:
            counts['shaw'] += 1
            dumped = _extract_shaw(blob, root / f'shaw{index:03d}')
            manifest.append(f'{index:5d}  0x{entry["absolute"]:07X}  {entry["codec"]:<5s}  shaw   '
                            f'{dumped} resources')
        else:
            counts['other'] += 1
            (root / f'data{index:03d}_{blob[:4].hex()}.bin').write_bytes(blob)
            manifest.append(f'{index:5d}  0x{entry["absolute"]:07X}  {entry["codec"]:<5s}  raw    '
                            f'head={blob[:4].hex()} len={len(blob)}')
    (root / 'manifest.txt').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    return counts


def iter_model_blobs(rom: bytes) -> list[tuple[str, bytes]]:
    """
    Collect every decodable model blob, from the ``mfs`` archive and the model archives.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    list[tuple[str, bytes]]
        A label describing where each blob came from, paired with its decoded bytes.
    """
    out = [(f'mfs/file{entry["index"]:03d}', blob)
           for entry, blob in decode_entries(rom, parse_archive(rom, XG2_MFS_ARCHIVE))]
    for address in xg2_resource_archives(rom):
        try:
            entries = parse_archive(rom, address)
        except struct.error:
            continue
        for entry, blob in decode_entries(rom, entries):
            label = (f'models/arch_{address:07X}'
                     if len(entries) == 1 else f'models/arch_{address:07X}/{entry["index"]:03d}')
            out.append((label, blob))
    return out


def _write_textures(textures: list[Texture], directory: Path) -> int:
    if not textures:
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    for index, texture in enumerate(textures):
        write_png(
            directory / f'tex{index:03d}_{texture.offset:07X}_{texture.width}x'
            f'{texture.height}_{texture.pixel_format}.png', texture.width, texture.height,
            texture.rgba)
    return len(textures)


def _extract_textures(rom: bytes, out: Path) -> int:
    directory = out / 'textures'
    directory.mkdir(parents=True, exist_ok=True)
    return sum(
        _write_textures(collect_textures(blob), directory / label)
        for label, blob in iter_model_blobs(rom))


def run(rom: bytes,
        out: Path,
        *,
        convert: bool = False,
        rate: int = DEFAULT_SAMPLE_RATE,
        fluidsynth_path: Path | None = None) -> dict[str, int]:
    """
    Extract every Extreme-G XG2 asset into an output directory.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    out : pathlib.Path
        Output directory, created if missing.
    convert : bool
        Also decode audio to WAV, build SoundFonts, decode textures to PNG, and render the
        sequences when FluidSynth is available.
    rate : int
        Playback rate assumed for the ``BMC`` sound effects.
    fluidsynth_path : pathlib.Path | None
        Explicit path to the FluidSynth binary.

    Returns
    -------
    dict[str, int]
        Counts of what was written, keyed by category.
    """
    out.mkdir(parents=True, exist_ok=True)
    sequences, midis = _extract_sequences(rom, out, convert=convert)
    wavs, soundfonts = _extract_soundbanks(rom, out, convert=convert)
    mfs = _extract_mfs(rom, out, convert=convert, rate=rate)
    counts = {
        'levels': _extract_levels(rom, out),
        'sequences': sequences,
        'midis': midis,
        'wavs': wavs + mfs['wav'],
        'soundfonts': soundfonts,
        'bmc': mfs['bmc'],
        'shaw': mfs['shaw'],
        'other': mfs['other'],
        'textures': _extract_textures(rom, out) if convert else 0,
        'rendered': 0
    }
    if convert:
        counts['rendered'] = render_directory(out / 'audio' / 'sequences',
                                              out / 'audio' / f'bank_{XG2_MELODIC_BANK:07X}.sf2',
                                              fluidsynth_path)
    return counts


def unpack(rom: bytes, out: Path, prefix: str = 'extreme-g-2') -> dict[str, int]:
    """
    Write the raw boot images and every ``mfs`` entry, without converting anything.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    out : pathlib.Path
        Output directory, created if missing.
    prefix : str
        Base name for the boot images and the archive directory.

    Returns
    -------
    dict[str, int]
        The number of files written and their total decompressed size.
    """
    out.mkdir(parents=True, exist_ok=True)
    boot = xg2_boot(rom)
    (out / f'{prefix}.boot.bin').write_bytes(boot.code)
    (out / f'{prefix}.bootram.bin').write_bytes(boot.ram_image())
    (out / f'{prefix}.extended.z64').write_bytes(boot.extended_rom())
    directory = out / f'{prefix}.files'
    directory.mkdir(parents=True, exist_ok=True)
    manifest = ['# index  rom_offset  codec  decompressed  compressed  filename']
    total = 0
    count = 0
    for entry, blob in decode_entries(rom, parse_archive(rom, XG2_MFS_ARCHIVE)):
        name = f'file_{entry["index"]:03d}_{entry["absolute"]:07X}_{entry["codec"]}.bin'
        (directory / name).write_bytes(blob)
        total += len(blob)
        count += 1
        manifest.append(f'{entry["index"]:5d}  0x{entry["absolute"]:07X}  {entry["codec"]:<5s}  '
                        f'0x{entry["decompressed_size"]:07X}  '
                        f'0x{entry["compressed_size"]:07X}  {name}')
    (directory / 'manifest.txt').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    return {'files': count, 'bytes': total}
