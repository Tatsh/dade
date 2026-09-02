"""``dade maxpayne ldb-textures`` - write out the images a level embeds."""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
import logging
import pathlib

import click

from dade.maxpayne.blocks import unwrap
from dade.maxpayne.ldb import InvalidLevelError, read_textures

from .utils import debug_option

__all__ = ('ldb_textures',)

log = logging.getLogger(__name__)


def _relative(path: str) -> PurePosixPath:
    """
    Turn an authored Windows path into a safe relative one.

    Parameters
    ----------
    path : str
        The path as stored in the level.

    Returns
    -------
    PurePosixPath
        The path with any drive letter, leading separator and upward step removed, so it can only
        ever name somewhere under the output directory.
    """
    windows = PureWindowsPath(path)
    # A level's texture paths are whatever the artist's machine had, so they are not to be trusted
    # with where a file lands: `..` in one of them would write outside the directory asked for.
    parts = [
        part for part in windows.parts if part not in {'\\', '/', '.', '..'} and ':' not in part
    ]
    return PurePosixPath(*parts) if parts else PurePosixPath('texture')


@click.command(name='ldb-textures')
@click.argument('levels',
                nargs=-1,
                required=True,
                type=click.Path(exists=True, path_type=pathlib.Path))
@click.option('-o',
              '--output-dir',
              default='.',
              help='Directory to write the images into.',
              type=click.Path(file_okay=False, path_type=pathlib.Path))
@click.option('--flat', is_flag=True, help='Write every image into one directory.')
@debug_option
def ldb_textures(levels: tuple[pathlib.Path, ...], output_dir: pathlib.Path, *, flat: bool) -> None:
    """
    Write out the images embedded in each LEVELS ``.ldb``.

    A directory is searched recursively. Each image is stored in the level exactly as the artist
    saved it, so the bytes are written through untouched and keep their original extension. Images
    land under the directory tree of the path they were authored at, with the drive letter dropped;
    pass --flat to put them all in one directory instead.
    """  # noqa: DOC501
    found: list[pathlib.Path] = []
    for level in levels:
        found.extend(sorted(level.rglob('*.ldb')) if level.is_dir() else [level])
    if not found:
        click.echo('No .ldb files found.', err=True)
        raise click.Abort
    written = 0
    for level in found:
        try:
            textures = read_textures(unwrap(level.read_bytes())[0])
        except (IndexError, InvalidLevelError, ValueError) as e:
            click.echo(f'{level.name}: {e}', err=True)
            raise click.Abort from e
        for texture in textures:
            relative = _relative(texture.path)
            destination = output_dir / (relative.name if flat else relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(texture.data)
            written += 1
        click.echo(f'{level.name}: {len(textures)} images.')
    click.echo(f'{written} images written to {output_dir}.')
