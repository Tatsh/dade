"""Root Click group and subcommands for the Extreme-G tools."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import logging

import bascom
import click

from .bmc import DEFAULT_SAMPLE_RATE
from .extract_pc import iter_model_blobs as iter_pc_model_blobs, run as run_pc
from .extract_xg1 import run as run_xg1, unpack as unpack_xg1
from .extract_xg2 import (
    iter_model_blobs as iter_n64_model_blobs,
    run as run_xg2,
    unpack as unpack_xg2,
)
from .images import write_png
from .models import collect_textures
from .montage import DEFAULT_CELL, DEFAULT_COLUMNS, build_index, build_montage
from .offsets import XG1_GAME_CODE, XG2_GAME_CODE
from .rom import game_code
from .smf import GM_DRUM_MAP, to_xg
from .soundfont import build_combined

if TYPE_CHECKING:
    from .typing import Texture

__all__ = ('cli',)

log = logging.getLogger(__name__)

_CONTEXT_SETTINGS = {'help_option_names': ('-h', '--help')}
_ROM_ARGUMENT = click.Path(exists=True, dir_okay=False, path_type=Path)
_OUTPUT_ARGUMENT = click.Path(file_okay=False, path_type=Path)
debug_option = bascom.debug_option({'dade.common': {}, 'dade.xg2': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


def _read_rom(path: Path, expected: bytes) -> bytes:
    """
    Read a ROM and warn when its game code is not the expected one.

    Returns
    -------
    bytes
        The whole ROM image.
    """
    rom = path.read_bytes()
    code = game_code(rom)
    if code != expected:
        log.warning('The ROM game code is %r, expected %r.', code, expected)
    return rom


@click.group(context_settings=_CONTEXT_SETTINGS)
def cli() -> None:
    """Extreme-G and Extreme-G XG2 (Probe/Acclaim) asset tools for N64 and PC."""


@cli.command(name='extract-xg1')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@click.option('-c',
              '--convert',
              is_flag=True,
              help='Also decode textures to PNG and audio to WAV, SoundFont, and MIDI.')
@debug_option
def extract_xg1(rom: Path, out: Path, *, convert: bool = False) -> None:
    """
    Extract every Extreme-G (N64) asset from ROM into OUT.

    The boot segment, the mfs archive, the level containers, and the master directory are always
    written. Level sub-blobs and texture banks are LZHUF-compressed, which is not implemented, so
    those are written out as raw compressed slices and noted in OUT/extract.log.
    """
    counts = run_xg1(_read_rom(rom, XG1_GAME_CODE), out, convert=convert)
    click.echo(f'boot: {counts["boot"]}, mfs: {counts["mfs"]}, '
               f'levels: {counts["levels"]} files in {counts["containers"]} containers, '
               f'directory: {counts["directory"]}, textures: {counts["textures"]}, '
               f'audio: {counts["audio"]}')


@cli.command(name='extract-xg2')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@click.option('-c',
              '--convert',
              is_flag=True,
              help='Also decode audio to WAV, build SoundFonts, and decode textures to PNG.')
@debug_option
@click.option('-r',
              '--rate',
              type=click.IntRange(min=1),
              default=DEFAULT_SAMPLE_RATE,
              show_default=True,
              help='Playback rate for the BMC sound effects. This has not been confirmed against '
              'the game.')
@click.option('--fluidsynth-path',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Path to the fluidsynth binary used to render the sequences.')
def extract_xg2(rom: Path,
                out: Path,
                *,
                convert: bool = False,
                rate: int = DEFAULT_SAMPLE_RATE,
                fluidsynth_path: Path | None = None) -> None:
    """
    Extract every Extreme-G XG2 (N64) asset from ROM into OUT.

    Level containers are written out raw, as their internal layout has not been reversed. With
    --convert the sequences are also rendered to WAV when FluidSynth is available.
    """
    counts = run_xg2(_read_rom(rom, XG2_GAME_CODE),
                     out,
                     convert=convert,
                     rate=rate,
                     fluidsynth_path=fluidsynth_path)
    click.echo(f'levels: {counts["levels"]}, sequences: {counts["sequences"]} '
               f'({counts["midis"]} MIDI, {counts["rendered"]} rendered), '
               f'mfs: {counts["bmc"]} BMC + {counts["shaw"]} shaw + {counts["other"]} raw, '
               f'WAV: {counts["wavs"]}, SoundFonts: {counts["soundfonts"]}, '
               f'textures: {counts["textures"]}')


@cli.command(name='extract-xg2-pc')
@click.argument('data1', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument('out', type=_OUTPUT_ARGUMENT)
@debug_option
def extract_xg2_pc(data1: Path, out: Path) -> None:
    """
    Extract every Extreme-G XG2 (Windows) asset from DATA1 into OUT.

    DATA1 is the port's data1 directory. Its layout is mirrored into OUT: containers are written
    out decompressed with their textures beside them as PNG, loose bitmaps become PNG, and the
    sound effects are copied verbatim.
    """
    counts = run_pc(data1, out)
    click.echo(f'containers: {counts["containers"]}, raw models: {counts["raw"]}, '
               f'textures: {counts["textures"]}, WAV: {counts["wavs"]}, '
               f'bitmaps: {counts["bitmaps"]}')


@cli.command(name='unpack-xg1-rom')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@debug_option
@click.option('-p',
              '--prefix',
              default='extreme-g',
              show_default=True,
              help='Base name for the boot images and the archive directory.')
def unpack_xg1_rom(rom: Path, out: Path, *, prefix: str = 'extreme-g') -> None:
    """
    Write the raw Extreme-G (N64) boot images and mfs files from ROM into OUT.

    Alongside the decompressed boot segment and a RAM image, an extended ROM is written with the
    segment placed at the offset it runs from, so a disassembler can see the main code.
    """
    counts = unpack_xg1(_read_rom(rom, XG1_GAME_CODE), out, prefix)
    click.echo(f'boot images: 3, mfs files: {counts["files"]} ({counts["bytes"]} bytes)')


@cli.command(name='unpack-xg2-rom')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@debug_option
@click.option('-p',
              '--prefix',
              default='extreme-g-2',
              show_default=True,
              help='Base name for the boot images and the archive directory.')
def unpack_xg2_rom(rom: Path, out: Path, *, prefix: str = 'extreme-g-2') -> None:
    """
    Write the raw Extreme-G XG2 (N64) boot images and mfs entries from ROM into OUT.

    Entries using the unimplemented LHUF codec are skipped with a warning.
    """
    counts = unpack_xg2(_read_rom(rom, XG2_GAME_CODE), out, prefix)
    click.echo(f'boot images: 3, mfs files: {counts["files"]} ({counts["bytes"]} bytes)')


@cli.command(name='convert-midi')
@click.argument('midi', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('out', type=click.Path(dir_okay=False, path_type=Path))
@debug_option
@click.option('-m',
              '--mode',
              type=click.Choice(('xg', 'generic')),
              default='xg',
              show_default=True,
              help='Keep the game drum keys, or remap them onto General MIDI percussion.')
@click.option('-p',
              '--drum-program',
              type=click.IntRange(0, 127),
              default=0,
              show_default=True,
              help='Drum kit selected on the percussion channel.')
def convert_midi(midi: Path, out: Path, *, mode: str = 'xg', drum_program: int = 0) -> None:
    """
    Add XG initialisation to the standard MIDI file MIDI and write it to OUT.

    In xg mode the note numbers are left alone, which is faithful to the game but needs its
    SoundFont to sound right. In generic mode the drum notes are remapped onto General MIDI
    percussion so the result plays recognisably on any device.
    """
    converted = to_xg(midi.read_bytes(),
                      drum_map=GM_DRUM_MAP if mode == 'generic' else None,
                      drum_program=drum_program)
    out.write_bytes(converted)
    click.echo(f'Wrote {out} ({mode}, {len(converted)} bytes).')


@cli.command(name='make-sf2')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=click.Path(dir_okay=False, path_type=Path))
@debug_option
@click.option('--drum-bank',
              type=str,
              default=None,
              help='Offset of a fallback drum control bank, for a bank without percussion.')
@click.option('--drum-key-offset',
              type=int,
              default=0,
              show_default=True,
              help='Subtracted from a fallback kit sound index to place it on the keyboard.')
@click.option('--melodic-bank',
              type=str,
              required=True,
              help='Offset of the melodic control bank, for example 0x710710.')
@click.option('-n',
              '--name',
              default='ExtremeG',
              show_default=True,
              help='Name recorded in the SoundFont.')
def make_sf2(rom: Path,
             out: Path,
             *,
             melodic_bank: str,
             drum_bank: str | None = None,
             drum_key_offset: int = 0,
             name: str = 'ExtremeG') -> None:
    """
    Build a SoundFont from the ALBankFile control bank at MELODIC_BANK in ROM.

    Melodic instruments are written to bank 0 and the drum kit, when the bank has one, to bank 128.

    Raises
    ------
    click.Abort
        If an offset is not a valid integer or the melodic bank could not be parsed.
    """
    try:
        melodic = int(melodic_bank, 0)
        drums = int(drum_bank, 0) if drum_bank is not None else None
        soundfont = build_combined(rom.read_bytes(), melodic, drums, name, drum_key_offset)
    except ValueError as e:
        log.error('%s', e)  # ruff:ignore[error-instead-of-exception]
        raise click.Abort from e
    out.write_bytes(soundfont)
    click.echo(f'Wrote {out} ({len(soundfont)} bytes).')


def _write_montage(textures: list[Texture], labels: list[str], out: Path, index_path: Path | None,
                   cell: int, columns: int) -> None:
    """Render a contact sheet and, when asked, the index mapping cells back to their sources."""
    width, height, rgba = build_montage(textures, cell, columns)
    write_png(out, width, height, rgba)
    if index_path is not None:
        index_path.write_text(build_index(textures, labels, columns), encoding='utf-8')
    click.echo(f'Wrote {out} ({width}x{height}, {len(textures)} textures).')


@cli.command(name='montage-n64')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=click.Path(dir_okay=False, path_type=Path))
@click.option('--cell',
              type=click.IntRange(min=1),
              default=DEFAULT_CELL,
              show_default=True,
              help='Side of one cell in pixels.')
@click.option('--columns',
              type=click.IntRange(min=1),
              default=DEFAULT_COLUMNS,
              show_default=True,
              help='Number of cells per row.')
@debug_option
@click.option('-i',
              '--index',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Also write a text index mapping each cell back to its source.')
def montage_n64(rom: Path,
                out: Path,
                *,
                cell: int = DEFAULT_CELL,
                columns: int = DEFAULT_COLUMNS,
                index: Path | None = None) -> None:
    """
    Tile every Extreme-G XG2 (N64) texture in ROM into one contact sheet at OUT.

    The display-list walker infers dimensions the hardware never stored, so a mis-parse shows up as
    a striped or skewed cell rather than an error. This sheet is how those are spotted.
    """
    textures: list[Texture] = []
    labels: list[str] = []
    for label, blob in iter_n64_model_blobs(_read_rom(rom, XG2_GAME_CODE)):
        for texture in collect_textures(blob):
            textures.append(texture)
            labels.append(f'{label}#{texture.offset:07X}')
    _write_montage(textures, labels, out, index, cell, columns)


@cli.command(name='montage-pc')
@click.argument('data1', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument('out', type=click.Path(dir_okay=False, path_type=Path))
@click.option('--cell',
              type=click.IntRange(min=1),
              default=DEFAULT_CELL,
              show_default=True,
              help='Side of one cell in pixels.')
@click.option('--columns',
              type=click.IntRange(min=1),
              default=DEFAULT_COLUMNS,
              show_default=True,
              help='Number of cells per row.')
@debug_option
@click.option('-i',
              '--index',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Also write a text index mapping each cell back to its source.')
def montage_pc(data1: Path,
               out: Path,
               *,
               cell: int = DEFAULT_CELL,
               columns: int = DEFAULT_COLUMNS,
               index: Path | None = None) -> None:
    """
    Tile every Extreme-G XG2 (Windows) texture under DATA1 into one contact sheet at OUT.

    Labelling each cell by its source file makes a wrong-stride decode easy to trace back.
    """
    textures: list[Texture] = []
    labels: list[str] = []
    for label, blob in iter_pc_model_blobs(data1):
        for texture in collect_textures(blob, '<'):
            textures.append(texture)
            labels.append(f'{label}#{texture.offset:07X}')
    _write_montage(textures, labels, out, index, cell, columns)
