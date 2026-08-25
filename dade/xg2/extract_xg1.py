"""
Full asset extraction for Extreme-G (N64, USA).

The game keeps its content in four places: the compressed boot and main code segment, a 50-file
``mfs`` archive, a set of level containers holding LZHUF sub-blobs, and a master directory of
small assets. With conversion enabled the texture banks are decoded to PNG and the audio banks to
WAV, SoundFont, and MIDI.

Level sub-blobs and texture banks are LZHUF-compressed, which :py:mod:`dade.xg2.lzhuf` does not
implement. Those are written out as raw compressed slices instead so nothing is silently lost, and
every skip is recorded in the run log.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import operator
import struct

from .albank import BANK_MAGIC, parse_bank
from .alcseq import to_midi
from .images import decode_i8, read_tlut, write_png
from .lzhuf import LzhufUnavailableError, decompress_lzhuf
from .mfs import MfsCalibrationError, iter_files
from .offsets import XG1_DIRECTORY_POINTER, XG1_LEVEL_MAX, XG1_LEVEL_MIN
from .rom import read_u32, xg1_boot, xg1_level_bases, xg1_texture_banks
from .smf import GM_DRUM_MAP, to_xg
from .soundfont import build_combined
from .wav import write_wav16

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('LEVEL_SUB_BLOBS', 'RunLog', 'run', 'unpack')

log = logging.getLogger(__name__)

LEVEL_SUB_BLOBS = (('t1_desc', 0x0C, 0x10, 0x0C), ('r2', 0x14, 0x18, 1), ('r3', 0x1C, 0x20, 1),
                   ('t4', 0x34, 0x38, 4))
"""Level container sub-blobs as name, offset field, size field, and size multiplier.

:meta hide-value:
"""
_HEADER_SIZE = 0x44
_MAX_SUB_BLOB = 0x400000
_OBJECT_RECORD_SIZE = 0x28
_MAX_OBJECTS = 0x4000
_MAX_BANK_SIZE = 0x200000
_SEQUENCE_MAGIC = b'S1\x00'
_MAX_SEQUENCES = 256
_MAX_SEQUENCE_SIZE = 0x400000
_MAX_TEXTURE_SIDE = 256
_TLUT_BYTES = 512
_MIN_SEQUENCE_OFFSET = 4
_MIN_BANKS_FOR_FALLBACK = 2


class RunLog:
    """A run log that both records messages for a report file and emits them to the logger."""
    def __init__(self) -> None:
        self.messages: list[str] = []

    def add(self, message: str) -> None:
        """
        Record one message.

        Parameters
        ----------
        message : str
            The message to record.
        """
        self.messages.append(message)
        log.warning('%s', message)

    def write(self, path: Path) -> None:
        """
        Write the recorded messages to a file.

        Parameters
        ----------
        path : pathlib.Path
            Destination file, whose parent must already exist.
        """
        path.write_text('\n'.join(self.messages) + ('\n' if self.messages else ''),
                        encoding='utf-8')


def _extract_boot(rom: bytes, out: Path) -> int:
    directory = out / 'boot'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'main_8004b8a0.bin').write_bytes(xg1_boot(rom).code)
    return 1


def _extract_mfs(rom: bytes, out: Path, run_log: RunLog) -> int:
    directory = out / 'mfs'
    directory.mkdir(parents=True, exist_ok=True)
    try:
        files = list(iter_files(rom))
    except (MfsCalibrationError, ValueError) as e:
        run_log.add(f'mfs: {e}')
        return 0
    for index, _, _, data in files:
        (directory / f'file_{index:02d}.bin').write_bytes(data)
    return len(files)


def _extract_levels(rom: bytes, out: Path, run_log: RunLog) -> tuple[int, int]:
    directory = out / 'levels'
    directory.mkdir(parents=True, exist_ok=True)
    bases = xg1_level_bases(rom)
    written = 0
    for index, base in enumerate(bases):
        level_dir = directory / f'{index:02d}_{base:07X}'
        level_dir.mkdir(parents=True, exist_ok=True)
        header = rom[base:base + _HEADER_SIZE]
        for name, offset_field, size_field, multiplier in LEVEL_SUB_BLOBS:
            offset = read_u32(header, offset_field)
            size = read_u32(header, size_field) * multiplier
            if offset == 0 or size == 0 or size > _MAX_SUB_BLOB:
                continue
            source = base + offset
            try:
                (level_dir / f'{name}.bin').write_bytes(decompress_lzhuf(rom, source, size))
                written += 1
            except LzhufUnavailableError:
                # Keep the compressed slice so nothing is lost until the codec exists.
                following = bases[index + 1] if base != bases[-1] else len(rom)
                (level_dir / f'{name}.lzhuf.raw').write_bytes(
                    rom[source:min(source + size, following)])
                run_log.add(f'level {index:02d} {name}: LZHUF is not implemented, wrote raw.')
        objects_offset, objects = read_u32(header, 0), read_u32(header, 4)
        if 0 < objects < _MAX_OBJECTS and XG1_LEVEL_MIN <= base + objects_offset < XG1_LEVEL_MAX:
            start = base + objects_offset
            (level_dir / 'objects.bin').write_bytes(
                rom[start:start + objects * _OBJECT_RECORD_SIZE])
            written += 1
    return written, len(bases)


def _extract_directory(rom: bytes, out: Path) -> int:
    directory = out / 'dir'
    directory.mkdir(parents=True, exist_ok=True)
    address = read_u32(rom, XG1_DIRECTORY_POINTER)
    size = read_u32(rom, XG1_DIRECTORY_POINTER + 4)
    (directory / f'directory_{address:07X}.bin').write_bytes(rom[address:address + size])
    return 1


def _extract_texture_banks(rom: bytes, out: Path, run_log: RunLog) -> int:
    directory = out / 'textures'
    directory.mkdir(parents=True, exist_ok=True)
    total = 0
    for offset, name in sorted(xg1_texture_banks(rom).items()):
        size = read_u32(rom, offset)
        if not 0 < size < _MAX_BANK_SIZE:
            continue
        try:
            bank = decompress_lzhuf(rom, offset + 4, size)
        except LzhufUnavailableError:
            run_log.add(f'texture bank {name} at 0x{offset:X}: LZHUF is not implemented, skipped.')
            continue
        total += _write_texture_bank(bank, directory / name, name, run_log)
    return total


def _bank_descriptors(bank: bytes) -> tuple[list[tuple[int, int, int]], int]:
    """
    Read the descriptor table that precedes a texture bank's pixels.

    Returns
    -------
    tuple[list[tuple[int, int, int]], int]
        Each texture's pixel offset, width, and height, and the offset the table ends at.
    """
    descriptors: list[tuple[int, int, int]] = []
    offset = 8
    while offset + 8 <= len(bank):
        pixels = struct.unpack_from('>I', bank, offset)[0]
        width, height = struct.unpack_from('>2H', bank, offset + 4)
        if (pixels == 0 or pixels >= len(bank) or not 0 < width <= _MAX_TEXTURE_SIDE
                or not 0 < height <= _MAX_TEXTURE_SIDE):
            break
        descriptors.append((pixels, width, height))
        offset += 8
    return descriptors, offset


def _write_texture_bank(bank: bytes, directory: Path, name: str, run_log: RunLog) -> int:
    descriptors, table_end = _bank_descriptors(bank)
    if not descriptors or descriptors[0][0] < table_end:
        run_log.add(f'texture bank {name}: no valid descriptor table.')
        return 0
    # The pixels are colour indices sharing one palette at the end of the bank, which the header's
    # first word points at. Fall back to greyscale only when no valid palette is present.
    palette_offset = struct.unpack_from('>I', bank, 0)[0]
    pixels_end = max(pixels + width * height for pixels, width, height in descriptors)
    palette = None
    if palette_offset == pixels_end and palette_offset + _TLUT_BYTES <= len(bank):
        palette = read_tlut(bank, palette_offset, _MAX_TEXTURE_SIDE)
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for index, (pixels, width, height) in enumerate(descriptors):
        data = bank[pixels:pixels + width * height]
        if len(data) < width * height:
            continue
        rgba = (_decode_indexed(data, palette, width, height) if palette else decode_i8(
            data, width, height))
        write_png(directory / f'tex{index:03d}_{width}x{height}.png', width, height, rgba)
        written += 1
    return written


def _decode_indexed(data: bytes, palette: list[bytes], width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    for i in range(width * height):
        out[i * 4:i * 4 + 4] = palette[data[i]]
    return bytes(out)


def _find_magic(rom: bytes, magic: bytes) -> Iterator[int]:
    position = 0
    while True:
        position = rom.find(magic, position)
        if position < 0:
            return
        yield position
        position += len(magic)


def _sequence_entries(rom: bytes, base: int) -> list[tuple[int, int]]:
    count = struct.unpack_from('>H', rom, base + 2)[0]
    if not 0 < count < _MAX_SEQUENCES:
        return []
    entries = []
    for i in range(count):
        offset, size = struct.unpack_from('>2I', rom, base + 4 + i * 8)
        if (not _MIN_SEQUENCE_OFFSET <= offset < _MAX_SEQUENCE_SIZE
                or not 0 < size < _MAX_SEQUENCE_SIZE or base + offset + size > len(rom)):
            return []
        entries.append((offset, size))
    return entries


def _extract_sequences(rom: bytes, out: Path, run_log: RunLog) -> int:
    """
    Write every ``S1`` sound bank's sequences as raw blobs and MIDI variants.

    Returns
    -------
    int
        The number of files written.
    """
    audio = out / 'audio'
    audio.mkdir(parents=True, exist_ok=True)
    written = 0
    for base in _find_magic(rom, _SEQUENCE_MAGIC):
        entries = _sequence_entries(rom, base)
        if not entries:
            continue
        directory = audio / f'soundbank_{base:07X}'
        directory.mkdir(parents=True, exist_ok=True)
        for index, (offset, size) in enumerate(entries):
            sequence = rom[base + offset:base + offset + size]
            (directory / f'seq{index:02d}.seq').write_bytes(sequence)
            written += 1
            try:
                midi, tracks = to_midi(sequence)
            except (IndexError, struct.error) as e:
                run_log.add(f'seq{index:02d}: ALCSeq to MIDI failed ({e}).')
                continue
            if not tracks:
                continue
            (directory / f'seq{index:02d}.mid').write_bytes(midi)
            written += 1
            try:
                (directory / f'seq{index:02d}.xg.mid').write_bytes(to_xg(midi))
                (directory / f'seq{index:02d}.gm.mid').write_bytes(to_xg(midi,
                                                                         drum_map=GM_DRUM_MAP))
                written += 2
            except (IndexError, ValueError) as e:
                run_log.add(f'seq{index:02d}: XG conversion failed ({e}).')
    return written


def _extract_control_bank(rom: bytes, control: int, out: Path, run_log: RunLog) -> int:
    """
    Decode every sound in one control bank to WAV.

    Returns
    -------
    int
        The number of sounds written.
    """
    bank = parse_bank(rom, control)
    if bank is None:
        return 0
    directory = out / 'audio' / f'samples_{control:07X}'
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for index, pcm in enumerate(bank['samples']):
        if not pcm:
            continue
        write_wav16(directory / f'sample{index:03d}.wav', pcm, bank['sample_rate'])
        written += 1
    if written:
        run_log.add(f'audio bank at 0x{control:X}: {written} sounds at {bank["sample_rate"]} Hz.')
    return written


def _extract_audio(rom: bytes, out: Path, run_log: RunLog) -> int:
    written = _extract_sequences(rom, out, run_log)
    banks = []
    for control in _find_magic(rom, BANK_MAGIC):
        count = _extract_control_bank(rom, control, out, run_log)
        if count:
            banks.append((control, count))
            written += count
    if banks:
        # The bank with the most sounds is the melodic one; the smaller is the effects bank, which
        # is passed only as a fallback for a bank without its own percussion pointer.
        melodic = max(banks, key=operator.itemgetter(1))[0]
        drums = (min(banks, key=operator.itemgetter(1))[0]
                 if len(banks) >= _MIN_BANKS_FOR_FALLBACK else None)
        try:
            (out / 'audio' / 'ExtremeG.sf2').write_bytes(build_combined(rom, melodic, drums))
            written += 1
        except (ValueError, struct.error) as e:
            run_log.add(f'audio: the combined SoundFont failed ({e}).')
    return written


def run(rom: bytes, out: Path, *, convert: bool = False) -> dict[str, int]:
    """
    Extract every Extreme-G 1 asset into an output directory.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    out : pathlib.Path
        Output directory, created if missing.
    convert : bool
        Also decode textures to PNG and audio to WAV, SoundFont, and MIDI.

    Returns
    -------
    dict[str, int]
        Counts of what was written, keyed by category.
    """
    out.mkdir(parents=True, exist_ok=True)
    run_log = RunLog()
    levels, containers = _extract_levels(rom, out, run_log)
    counts = {
        'boot': _extract_boot(rom, out),
        'mfs': _extract_mfs(rom, out, run_log),
        'levels': levels,
        'containers': containers,
        'directory': _extract_directory(rom, out),
        'textures': _extract_texture_banks(rom, out, run_log) if convert else 0,
        'audio': _extract_audio(rom, out, run_log) if convert else 0
    }
    run_log.write(out / 'extract.log')
    return counts


def unpack(rom: bytes, out: Path, prefix: str = 'extreme-g') -> dict[str, int]:
    """
    Write the raw boot images and every ``mfs`` file, without converting anything.

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
        The number of files written and their total decompressed size. A
        :py:class:`~dade.xg2.mfs.MfsCalibrationError` propagates if the archive base cannot be
        calibrated.
    """
    out.mkdir(parents=True, exist_ok=True)
    boot = xg1_boot(rom)
    (out / f'{prefix}.boot.bin').write_bytes(boot.code)
    (out / f'{prefix}.bootram.bin').write_bytes(boot.ram_image())
    (out / f'{prefix}.extended.z64').write_bytes(boot.extended_rom())
    directory = out / f'{prefix}.files'
    directory.mkdir(parents=True, exist_ok=True)
    manifest = ['# index  rom_offset  decompressed  compressed  filename']
    total = 0
    count = 0
    for index, offset, entry, data in iter_files(rom):
        name = f'file_{index:02d}_{offset:07X}.bin'
        (directory / name).write_bytes(data)
        total += len(data)
        count += 1
        manifest.append(f'{index:5d}  0x{offset:07X}  0x{entry.decompressed_size:07X}  '
                        f'0x{entry.compressed_size:07X}  {name}')
    (directory / 'manifest.txt').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    return {'files': count, 'bytes': total}
