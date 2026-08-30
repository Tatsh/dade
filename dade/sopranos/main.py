"""Command-line entry points for The Sopranos: Road to Respect asset tools."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import struct

import bascom
import click

from dade.common.exceptions import InvalidFormatError

from .archive import is_disc_image, iter_disc_archives, iter_entries, read_directory
from .audio import convert_bank, convert_stream, convert_voice
from .gltf import write_glb, write_prop_glb
from .level import extract as extract_level
from .model import write_model
from .olv import Placement, read_placements
from .texture import convert as convert_texture, convert_geometry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

__all__ = ('archive_directory', 'iter_sources', 'sopranos')

_CONTEXT_SETTINGS = {'help_option_names': ('-h', '--help')}
_ARCHIVE_SUFFIX = '.fs'
_COOKER_SUFFIX = '_p'

debug_option = bascom.debug_option({'dade.common': {}, 'dade.sopranos': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


def _prop_libraries(path: Path) -> tuple[tuple[bytes, ...], tuple[Placement, ...]]:
    """
    Find the prop libraries and placements belonging to a geometry file's level.

    A level is split across sibling directories: the ``p_c`` one holds the objects every part of
    the level shares along with the placements for all of them, and the others hold variants of the
    geometry, each covering the whole level and carrying the slice of the cast it needs. So a
    geometry file is matched to its level by name, allowing for the ``_hub`` suffix the variants
    carry, and then offered its own library first, the shared one next, and the remaining variants
    last, so that every placed object can be drawn wherever its geometry happens to live.

    Parameters
    ----------
    path : Path
        The geometry file being converted.

    Returns
    -------
    tuple[tuple[bytes, ...], tuple[Placement, ...]]
        The libraries' bytes and the placements, both empty when the level records none.
    """
    cooked = path.parent.parent
    for shared in sorted((p for p in cooked.glob('p_c*') if p.is_dir()),
                         key=lambda p: len(p.name),
                         reverse=True):
        level = shared.name[3:]
        if not (path.stem.lower().endswith((level, f'{level}_hub'))):
            continue
        objects = next((p for p in shared.iterdir() if p.suffix.upper() == '.OLV'), None)
        if objects is None:
            continue
        ordered = [
            path.parent, shared,
            *(p for p in sorted(cooked.iterdir()) if p.is_dir() and p.name.endswith(
                (level, f'{level}_hub')) and p not in {path.parent, shared})
        ]
        libraries = tuple(found.read_bytes() for directory in ordered
                          if (found := next((p for p in directory.iterdir()
                                             if p.suffix.upper() == '.SGP2'), None)) is not None)
        return libraries, read_placements(objects.read_bytes())
    return (), ()


def _expand_level(path: Path) -> int:
    """
    Split one ``.LVL`` container into the directory beside it.

    Parameters
    ----------
    path : Path
        The container.

    Returns
    -------
    int
        The number of sub-assets written.
    """
    return len(extract_level(path, path.with_suffix('')))


def _convert_asset(path: Path) -> int:
    """
    Convert one extracted asset, if it is a kind that is recognised.

    Parameters
    ----------
    path : Path
        The file to convert.

    Returns
    -------
    int
        The number of files written, zero for anything not recognised.
    """
    written = 0
    match path.suffix.lower():
        case '.tex2':
            written += len(convert_texture(path, path.parent))
        case '.egp2':
            written += len(convert_geometry(path, path.parent / f'{path.stem}_textures'))
            written += len(write_model(path, path.parent))
            libraries, placements = _prop_libraries(path)
            written += len(write_glb(path, path.parent, libraries=libraries, placements=placements))
        case '.sgp2':
            written += len(convert_geometry(path, path.parent / f'{path.stem}_textures'))
        case '.msh' if (body := path.with_suffix('.msb')).is_file():
            written += len(convert_bank(path, body, path.parent))
        case '.mih' if (body := path.with_suffix('.mib')).is_file():
            written += bool(convert_stream(path, body, path.with_suffix('.wav')))
        case '.vo2':
            written += bool(convert_voice(path, path.with_suffix('.wav')))
    return written


def _guarded(convert: Callable[[Path], int], path: Path, *, ignore_failures: bool) -> int:
    """
    Run one conversion, optionally surviving its failure.

    Parameters
    ----------
    convert : Callable[[Path], int]
        The conversion to run.
    path : Path
        The file to convert.
    ignore_failures : bool
        Log and skip a failure instead of letting it out.

    Returns
    -------
    int
        The number of files written, zero when the conversion failed and was skipped.

    Raises
    ------
    InvalidFormatError
        If the conversion fails and *ignore_failures* is not set.
    OSError
        If the file cannot be read or the output cannot be written, and *ignore_failures* is not
        set.
    struct.error
        If the file ends in the middle of a record, and *ignore_failures* is not set.
    ValueError
        If the file's contents do not make sense, and *ignore_failures* is not set.
    """
    try:
        return convert(path)
    except (InvalidFormatError, OSError, struct.error, ValueError) as e:
        if not ignore_failures:
            raise
        click.echo(f'Skipping {path}: {e}', err=True)
        return 0


def _convert_audio(path: Path, output_dir: Path) -> int:
    """
    Convert one sound bank or music stream to WAV.

    Parameters
    ----------
    path : Path
        The ``.MSH`` or ``.MIH`` header.
    output_dir : Path
        Where the WAV files go.

    Returns
    -------
    int
        The number of files written.

    Raises
    ------
    click.ClickException
        If the file is neither a ``.MSH`` nor a ``.MIH``.
    """
    match path.suffix.lower():
        case '.msh':
            return len(convert_bank(path, path.with_suffix('.msb'), output_dir))
        case '.mih':
            convert_stream(path, path.with_suffix('.mib'), output_dir / f'{path.stem}.wav')
            return 1
        case _:
            msg = f'`{path.name}` is not a .MSH or .MIH file.'
            raise click.ClickException(msg)


def _convert_extracted(root: Path, *, ignore_failures: bool) -> int:
    """
    Convert every recognised asset already extracted under *root*.

    Parameters
    ----------
    root : Path
        Directory holding the extracted archive tree.
    ignore_failures : bool
        Log and skip a conversion failure instead of stopping.

    Returns
    -------
    int
        The number of files written.
    """
    # Levels are expanded first so that the textures they contain are converted by the same pass.
    written = sum(
        _guarded(_expand_level, path, ignore_failures=ignore_failures)
        for path in sorted(root.rglob('*.lvl')))
    return written + sum(
        _guarded(_convert_asset, path, ignore_failures=ignore_failures)
        for path in sorted(root.rglob('*')))


@click.group(context_settings=_CONTEXT_SETTINGS)
def sopranos() -> None:
    """Asset tools for The Sopranos: Road to Respect (PS2)."""


@sopranos.command(name='list')
@click.argument('archive', type=click.Path(dir_okay=False, exists=True, path_type=Path))
@debug_option
def list_(archive: Path) -> None:
    """List the contents of a .FS archive."""  # noqa: DOC501
    try:
        entries = read_directory(archive)
    except InvalidFormatError as e:
        raise click.ClickException(str(e)) from e
    for entry in entries:
        click.echo(f'{entry.size:>12}  {entry.offset:>12}  {entry.name}')
    click.echo(f'{len(entries)} file(s).')


def archive_directory(name: str) -> str:
    """
    Give the directory an archive's contents belong in.

    Every archive the cooker writes carries a ``_P`` tag, ``DATA_P.FS`` and so on. It is not a
    region code -- the NTSC-U disc, ``SLUS-21388``, uses it as well -- and it says nothing about
    what is inside, so it is dropped: ``DATA_P.FS`` unpacks into ``data``. An archive without the
    tag keeps its whole stem.

    Parameters
    ----------
    name : str
        The archive's file name.

    Returns
    -------
    str
        A directory name.
    """
    stem = Path(name).stem.lower()
    return stem.removesuffix(_COOKER_SUFFIX)


def iter_sources(paths: Iterable[Path]) -> Iterator[tuple[Path, str, int, int | None]]:
    """
    Expand what the user named into the archives to read.

    A path may be a disc image, in which case every ``.FS`` on it is read in place without being
    copied out first; a directory, which is searched for archives however they happen to be cased;
    or an archive itself.

    Parameters
    ----------
    paths : Iterable[Path]
        What the user named.

    Yields
    ------
    tuple[Path, str, int, int | None]
        The file to read from, the archive's name, and the byte offset and length of the archive
        within that file.
    """
    for path in paths:
        if path.is_dir():
            found = sorted(child for child in path.rglob('*')
                           if child.is_file() and child.suffix.lower() == _ARCHIVE_SUFFIX)
            for child in found:
                yield child, child.name, 0, None
        elif is_disc_image(path):
            for name, base, length in iter_disc_archives(path):
                yield path, name, base, length
        else:
            yield path, path.name, 0, None


@sopranos.command()
@click.argument('sources', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@debug_option
@click.option('-o',
              '--output-dir',
              type=click.Path(file_okay=False, path_type=Path),
              default=Path(),
              help='Output directory (created if missing).')
@click.option('--convert', is_flag=True, help='Also convert textures and audio after extracting.')
@click.option('--ignore-failures',
              is_flag=True,
              help='Log and skip a conversion failure instead of stopping.')
def unpack(sources: tuple[Path, ...],
           *,
           output_dir: Path,
           convert: bool = False,
           ignore_failures: bool = False) -> None:
    """
    Extract everything from a disc image, a directory of archives, or the archives themselves.

    Each archive lands in its own directory named after it, so unpacking a disc image gives the
    whole game in one command.
    """  # noqa: DOC501
    found = list(iter_sources(sources))
    if not found:
        msg = 'Nothing to unpack: no .FS archives were found.'
        raise click.ClickException(msg)
    count = 0
    try:
        for container, name, base, length in found:
            target = output_dir / archive_directory(name)
            for entry, data in iter_entries(container, base, length):
                destination = target / entry.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                count += 1
    except InvalidFormatError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f'Extracted {count} file(s) to {output_dir}.')
    if convert:
        click.echo(f'Converted {_convert_extracted(output_dir, ignore_failures=ignore_failures)} '
                   f'file(s).')


@sopranos.command()
@click.argument('files', nargs=-1, type=click.Path(dir_okay=False, exists=True, path_type=Path))
@debug_option
@click.option('-o',
              '--output-dir',
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help='Output directory (defaults to a directory beside each input).')
def level(files: tuple[Path, ...], *, output_dir: Path | None = None) -> None:
    """Split .LVL containers into their cooked sub-assets."""  # noqa: DOC501
    for path in files:
        try:
            written = extract_level(path, output_dir or path.with_suffix(''))
        except InvalidFormatError as e:
            raise click.ClickException(str(e)) from e
        click.echo(f'{path}: {len(written)} sub-asset(s).')


@sopranos.command()
@click.argument('files', nargs=-1, type=click.Path(dir_okay=False, exists=True, path_type=Path))
@debug_option
@click.option('-o',
              '--output-dir',
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help='Output directory (defaults to beside each input).')
def texture(files: tuple[Path, ...], *, output_dir: Path | None = None) -> None:
    """Convert .TEX2 texture banks to PNG."""  # noqa: DOC501
    for path in files:
        try:
            written = convert_texture(path, output_dir or path.parent)
        except InvalidFormatError as e:
            raise click.ClickException(str(e)) from e
        click.echo(f'{path}: {len(written)} image(s).')


@sopranos.command()
@click.argument('files', nargs=-1, type=click.Path(dir_okay=False, exists=True, path_type=Path))
@debug_option
@click.option('-o',
              '--output-dir',
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help='Output directory (defaults to beside each input).')
def mesh(files: tuple[Path, ...], *, output_dir: Path | None = None) -> None:
    """Convert .SGP2 or .EGP2 geometry to Wavefront OBJ and MTL."""
    for path in files:
        written = write_model(path, output_dir or path.parent)
        click.echo(f'{path}: {len(written)} file(s).')


@sopranos.command()
@click.argument('files', nargs=-1, type=click.Path(dir_okay=False, exists=True, path_type=Path))
@debug_option
@click.option('-o',
              '--output-dir',
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help='Output directory (defaults to beside each input).')
def gltf(files: tuple[Path, ...], *, output_dir: Path | None = None) -> None:
    """Convert .EGP2 level geometry or .SGP2 prop libraries to binary glTF."""
    for path in files:
        convert = write_prop_glb if path.suffix.lower() == '.sgp2' else write_glb
        written = convert(path, output_dir or path.parent)
        click.echo(f'{path}: {len(written)} file(s).')


@sopranos.command()
@click.argument('headers', nargs=-1, type=click.Path(dir_okay=False, exists=True, path_type=Path))
@debug_option
@click.option('-o',
              '--output-dir',
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help='Output directory (defaults to beside each input).')
def audio(headers: tuple[Path, ...], *, output_dir: Path | None = None) -> None:
    """Convert .MSH sound banks or .MIH music streams to WAV."""  # noqa: DOC501
    for path in headers:
        target = output_dir or path.parent
        try:
            written = _convert_audio(path, target)
        except (InvalidFormatError, FileNotFoundError) as e:
            raise click.ClickException(str(e)) from e
        click.echo(f'{path}: {written} file(s).')
