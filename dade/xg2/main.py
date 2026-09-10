"""Root Click group and subcommands for the Extreme-G tools."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
import logging

import bascom
import click

from dade.common.disc import as_directory, find_by_suffix
from dade.common.exceptions import InvalidFormatError

from .bmc import parse_bmc
from .extract_pc import iter_model_blobs as iter_pc_model_blobs, run as run_pc
from .extract_xg1 import run as run_xg1, unpack as unpack_xg1
from .extract_xg2 import (
    iter_model_blobs as iter_n64_model_blobs,
    run as run_xg2,
    unpack as unpack_xg2,
)
from .gltf import build_clip_glb, build_glb, build_level_glb, build_track_glb, iter_models
from .images import write_png
from .models import collect_textures
from .montage import DEFAULT_CELL, DEFAULT_COLUMNS, build_index, build_montage
from .offsets import XG1_GAME_CODE, XG2_GAME_CODE
from .rom import game_code, normalize_rom, xg1_level_bases, xg2_level_bases
from .skeleton import Skeleton, parse_skeleton
from .smf import GM_DRUM_MAP, to_xg
from .soundfont import build_combined
from .xg1_level import XG1, XG2, XG2PC, decode_level_geometry, decode_level_textures
from .xg1_objects import (
    glow_model,
    glow_textures,
    object_placements,
    read_code_segment,
    read_entities,
    read_object_models,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    from .typing import Endian, Texture
    from .xg1_level import Dialect

__all__ = ('cli',)

log = logging.getLogger(__name__)

_CONTEXT_SETTINGS = {'help_option_names': ('-h', '--help')}
_ROM_ARGUMENT = click.Path(exists=True, dir_okay=False, path_type=Path)
_OUTPUT_ARGUMENT = click.Path(file_okay=False, path_type=Path)
_DISC_ARGUMENT = click.Path(exists=True, path_type=Path)
"""The Windows port's files, as an installation directory or as the disc they came on.

:meta hide-value:
"""
debug_option = bascom.debug_option({'dade.common': {}, 'dade.xg2': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


def _read_rom(path: Path, expected: bytes) -> bytes:
    """
    Read a ROM, put it in big-endian order, and warn when its game code is not the expected one.

    Returns
    -------
    bytes
        The whole ROM image, in ``.z64`` order whichever of the three layouts it was dumped in.
    """
    rom = normalize_rom(path.read_bytes())
    code = game_code(rom)
    if code != expected:
        log.warning('The ROM game code is %r, expected %r.', code, expected)
    return rom


@contextmanager
def _disc_directory(source: Path) -> Generator[Path]:
    """
    Read a source directory or disc image, reporting an unreadable image as a graceful failure.

    Parameters
    ----------
    source : pathlib.Path
        An already-extracted directory, an ISO image, or the ``.cue`` or ``.bin`` of a cue/bin
        pair.

    Yields
    ------
    pathlib.Path
        The directory to read from.

    Raises
    ------
    click.Abort
        If the source is a file that is not a readable disc image.
    """
    try:
        with as_directory(source) as directory:
            yield directory
    except InvalidFormatError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e


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
    written. Level sub-blobs and texture banks are LZHUF-compressed, and that is not implemented
    here. Those are written out as raw compressed slices and noted in OUT/extract.log.
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
@click.option('--fluidsynth-path',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Path to the fluidsynth binary used to render the sequences.')
def extract_xg2(rom: Path,
                out: Path,
                *,
                convert: bool = False,
                fluidsynth_path: Path | None = None) -> None:
    """
    Extract every Extreme-G XG2 (N64) asset from ROM into OUT.

    The ``mfs`` archive's ``BMC`` entries are skeletal motion clips rather than sound effects, and
    they are written out as they are and described in the manifest. With --convert the sequences
    are also rendered to WAV when FluidSynth is available.
    """
    counts = run_xg2(_read_rom(rom, XG2_GAME_CODE),
                     out,
                     convert=convert,
                     fluidsynth_path=fluidsynth_path)
    click.echo(f'levels: {counts["levels"]}, sequences: {counts["sequences"]} '
               f'({counts["midis"]} MIDI, {counts["rendered"]} rendered), '
               f'mfs: {counts["bmc"]} BMC + {counts["shaw"]} shaw + {counts["other"]} raw, '
               f'WAV: {counts["wavs"]}, SoundFonts: {counts["soundfonts"]}, '
               f'textures: {counts["textures"]}')


@cli.command(name='extract-xg2-pc')
@click.argument('data1', type=_DISC_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@debug_option
def extract_xg2_pc(data1: Path, out: Path) -> None:
    """
    Extract every Extreme-G XG2 (Windows) asset from DATA1 into OUT.

    DATA1 is the port's data1 directory, or the disc it came on as an ISO image or a cue/bin pair.
    Its layout is mirrored into OUT: containers are written out decompressed with their textures
    beside them as PNG, loose bitmaps become PNG, and the sound effects are copied verbatim.
    """
    with _disc_directory(data1) as source:
        counts = run_pc(source, out)
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
    segment placed at the offset it runs from, letting a disassembler see the main code.
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
              help='Retain the game drum keys, or remap them onto General MIDI percussion.')
@click.option('-p',
              '--drum-program',
              type=click.IntRange(0, 127),
              default=0,
              show_default=True,
              help='Drum kit selected on the percussion channel.')
def convert_midi(midi: Path, out: Path, *, mode: str = 'xg', drum_program: int = 0) -> None:
    """
    Add XG initialisation to the standard MIDI file MIDI and write it to OUT.

    In xg mode the note numbers are unchanged, faithful to the game but needing its SoundFont to
    sound right. In generic mode the drum notes are remapped onto General MIDI percussion, and the
    result plays recognisably on any device.
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
    """  # ruff: ignore[docstring-missing-exception]
    try:
        melodic = int(melodic_bank, 0)
        drums = int(drum_bank, 0) if drum_bank is not None else None
        soundfont = build_combined(rom.read_bytes(), melodic, drums, name, drum_key_offset)
    except ValueError as e:
        log.error('%s', e)  # ruff:ignore[error-instead-of-exception]
        raise click.Abort from e
    out.write_bytes(soundfont)
    click.echo(f'Wrote {out} ({len(soundfont)} bytes).')


def _write_glbs(blobs: Iterable[tuple[str, bytes]], out: Path, endian: Endian) -> tuple[int, int]:
    """
    Convert every model in a set of archive entries to a separate ``.glb``.

    Parameters
    ----------
    blobs : collections.abc.Iterable[tuple[str, bytes]]
        A label and the decoded bytes of each archive entry.
    out : pathlib.Path
        Output directory, created if missing.
    endian : dade.xg2.typing.Endian
        Byte order: ``>`` for the N64 builds, ``<`` for the PC port.

    Returns
    -------
    tuple[int, int]
        The number of files written and the number of models that drew nothing.
    """
    out.mkdir(parents=True, exist_ok=True)
    written = empty = 0
    for label, blob in blobs:
        for suffix, model in iter_models(blob, endian):
            name = f'{label}{suffix}'.replace('/', '_').replace('#', '_')
            glb = build_glb(model, collect_textures(model, endian), name, endian)
            if glb is None:
                empty += 1
                continue
            (out / f'{name}.glb').write_bytes(glb)
            written += 1
    return written, empty


def _write_montage(textures: list[Texture], labels: list[str], out: Path, index_path: Path | None,
                   cell: int, columns: int) -> None:
    """Render a contact sheet and, when requested, the index mapping cells to their sources."""
    width, height, rgba = build_montage(textures, cell, columns)
    write_png(out, width, height, rgba)
    if index_path is not None:
        index_path.write_text(build_index(textures, labels, columns), encoding='utf-8')
    click.echo(f'Wrote {out} ({width}x{height}, {len(textures)} textures).')


def _write_levels(image: bytes, bases: list[int], out: Path, dialect: Dialect) -> tuple[int, int]:
    """
    Convert every level container to a separate ``.glb``.

    Parameters
    ----------
    image : bytes
        The whole ROM image.
    bases : list[int]
        Container offsets from the level table.
    out : pathlib.Path
        Output directory, created if missing.
    dialect : dade.xg2.xg1_level.Dialect
        Which game's bytecode to interpret.

    Returns
    -------
    tuple[int, int]
        Files written, and containers that drew nothing.
    """
    out.mkdir(parents=True, exist_ok=True)
    # The objects a track places are drawn from a second code segment every level shares, and it is
    # therefore decompressed once. Only Extreme-G has it; XG2 stores its objects elsewhere.
    segment = read_code_segment(image) if dialect.region_fields else b''
    models = read_object_models(segment) if segment else []
    panels = glow_model(segment) if segment else None
    # The glow scrolls, beyond what a glTF can express, and only its first step is written.
    glow_images = glow_textures(segment, 1) if segment else []
    written = empty = 0
    for index, base in enumerate(bases):
        meshes = decode_level_geometry(image, base, dialect)
        name = f'level_{index:02d}_{base:07X}'
        textures = decode_level_textures(image, base, dialect) + glow_images
        placements = object_placements(read_entities(image, base, dialect), models)
        glb = (build_track_glb(meshes, textures, placements, panels, name, dialect.texture_scale)
               if meshes else None)
        if glb is None:
            empty += 1
            continue
        (out / f'{name}.glb').write_bytes(glb)
        written += 1
    return written, empty


@cli.command(name='xg1-to-glb')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@debug_option
def xg1_to_glb(rom: Path, out: Path) -> None:
    """
    Convert every Extreme-G (N64) level in ROM to a binary glTF in OUT.

    ROM must be the original image. The extended one overwrites the level table's neighbourhood
    with the decompressed code segment, and its offsets no longer mean anything.

    A level's geometry is a compressed bytecode rather than a display list. This therefore runs the
    same interpreter the game's loader does and collects the triangles it would have drawn.
    """
    image = _read_rom(rom, XG1_GAME_CODE)
    written, empty = _write_levels(image, xg1_level_bases(image), out, XG1)
    click.echo(f'Wrote {written} glTF files to {out} ({empty} containers drew nothing).')


@cli.command(name='xg2-to-glb')
@click.argument('rom', type=_ROM_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@debug_option
def xg2_to_glb(rom: Path, out: Path) -> None:
    """
    Convert every Extreme-G XG2 (N64) level and model in ROM to a binary glTF in OUT.

    The two come out of the ROM differently. Models are stored as F3DEX2 display lists and are read
    straight off; levels are the same compressed bytecode the first game uses, with twenty opcodes
    instead of fifteen and a visibility byte in front of every triangle.
    """
    image = _read_rom(rom, XG2_GAME_CODE)
    levels, skipped = _write_levels(image, xg2_level_bases(image), out, XG2)
    written, empty = _write_glbs(iter_n64_model_blobs(image), out, '>')
    # Riders include the skeleton the clips drive; any of them will do, as they are identical.
    skeleton = next(
        (s for _, blob in iter_n64_model_blobs(image) if (s := parse_skeleton(blob)) is not None),
        None)
    clips = _write_clips(iter_n64_model_blobs(image), out, skeleton)
    click.echo(f'Wrote {levels} levels, {written} models and {clips} animations to {out} '
               f'({skipped} containers and {empty} models drew nothing).')


def _write_clips(blobs: Iterable[tuple[str, bytes]],
                 out: Path,
                 skeleton: Skeleton | None = None) -> int:
    """
    Convert every ``BMC`` motion clip to a separate ``.glb``.

    Parameters
    ----------
    blobs : collections.abc.Iterable[tuple[str, bytes]]
        A label and the decoded bytes of each archive entry.
    out : pathlib.Path
        Output directory, created if missing.
    skeleton : dade.xg2.skeleton.Skeleton | None
        Skeleton the clips drive, turning them from loose curves into a real hierarchy.

    Returns
    -------
    int
        The number of files written.
    """
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for label, blob in blobs:
        clip = parse_bmc(blob)
        if clip is None:
            continue
        name = f'anim_{label.replace("/", "_")}_{clip.name.replace(".", "_")}'
        glb = build_clip_glb(clip, name, skeleton)
        if glb is None:
            continue
        (out / f'{name}.glb').write_bytes(glb)
        written += 1
    return written


@cli.command(name='xg2-pc-to-glb')
@click.argument('data1', type=_DISC_ARGUMENT)
@click.argument('out', type=_OUTPUT_ARGUMENT)
@debug_option
def xg2_pc_to_glb(data1: Path, out: Path) -> None:
    """
    Convert every Extreme-G XG2 (Windows) track under DATA1 to a binary glTF in OUT.

    DATA1 is the port's data1 directory, or the disc it came on as an ISO image or a cue/bin pair.

    The port's tracks are the console levels with their multi-byte fields byte-swapped, and the same
    bytecode interpreter reads both. Its bikes are not converted. Those are display lists that take
    their vertices from segment 8. The engine fills that segment at run time, and the vertices are
    not in the game's files at all.
    """
    out.mkdir(parents=True, exist_ok=True)
    written = empty = 0
    with _disc_directory(data1) as source:
        for path in find_by_suffix(source, '.pcb'):
            data = path.read_bytes()
            meshes = decode_level_geometry(data, 0, XG2PC)
            # ISO 9660 upper-cases its names, and the stem is folded so a disc and an installation
            # write the same file names.
            name = f'track_{path.stem.lower()}'
            glb = (build_level_glb(meshes, decode_level_textures(data, 0, XG2PC), name,
                                   XG2PC.texture_scale) if meshes else None)
            if glb is None:
                empty += 1
                continue
            (out / f'{name}.glb').write_bytes(glb)
            written += 1
    click.echo(f'Wrote {written} tracks to {out} ({empty} drew nothing).')


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

    The display-list walker infers dimensions the hardware never stored, and a mis-parse therefore
    shows up as a striped or skewed cell rather than an error. This sheet is how those are spotted.
    """
    textures: list[Texture] = []
    labels: list[str] = []
    for label, blob in iter_n64_model_blobs(_read_rom(rom, XG2_GAME_CODE)):
        for texture in collect_textures(blob):
            textures.append(texture)
            labels.append(f'{label}#{texture.offset:07X}')
    _write_montage(textures, labels, out, index, cell, columns)


@cli.command(name='montage-pc')
@click.argument('data1', type=_DISC_ARGUMENT)
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

    DATA1 is the port's data1 directory, or the disc it came on as an ISO image or a cue/bin pair.
    Labelling each cell by its source file makes a wrong-stride decode easy to trace back.
    """
    textures: list[Texture] = []
    labels: list[str] = []
    with _disc_directory(data1) as source:
        for label, blob in iter_pc_model_blobs(source):
            for texture in collect_textures(blob, '<'):
                textures.append(texture)
                labels.append(f'{label}#{texture.offset:07X}')
    _write_montage(textures, labels, out, index, cell, columns)
