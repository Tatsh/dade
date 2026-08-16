"""``destin jubeatplus unpack`` - convert a whole download to open formats."""
from __future__ import annotations

from pathlib import Path
import logging

from destin.common.tools import ToolNotFoundError, locate_tool
from destin.jubeatplus.pipeline import unpack as unpack_download
import bascom
import click

__all__ = ('unpack',)

log = logging.getLogger(__name__)

debug_option = bascom.debug_option({'destin.common': {}, 'destin.jubeatplus': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


@click.command(name='unpack', context_settings={'help_option_names': ('-h', '--help')})
@click.argument('source', metavar='SOURCE', type=click.Path(exists=True, path_type=Path))
@debug_option
@click.option('--ffmpeg-path',
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Path to ffmpeg, when it is not on PATH.')
@click.option('-j',
              '--jobs',
              type=int,
              default=None,
              help='Process-pool size (defaults to the CPU count).')
@click.option('--no-audio', is_flag=True, help='Copy the .caf sound effects instead of converting.')
@click.option('--no-png', is_flag=True, help='Leave the PNGs Apple-optimised.')
@click.option('-o',
              '--output-dir',
              default=Path(),
              type=click.Path(file_okay=False, path_type=Path),
              help='Directory to write into (defaults to the current directory).')
@click.option('--pngdefry-path',
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Path to pngdefry, when it is not on PATH.')
def unpack(source: Path,
           output_dir: Path,
           ffmpeg_path: Path | None,
           pngdefry_path: Path | None,
           jobs: int | None,
           *,
           no_audio: bool = False,
           no_png: bool = False) -> None:
    """
    Unpack and convert the jubeat plus download at SOURCE.

    SOURCE may be an ``.ipa``, the ``.app`` bundle, the ``Payload`` directory, or a directory
    holding ``Payload``. It is only read; everything is written under --output-dir, into a
    directory named after the bundle.

    Apple-optimised PNGs are rewritten as ordinary ones, ``.tex`` textures are deciphered and
    rewritten the same way, ``.caf`` sound effects become WAV, ``.jbt`` tune packages and the
    marker ZIPs are unpacked into directories named after themselves with every entry deciphered
    and decoded, charts become JSON, property lists and localisation tables and Core Data models
    become JSON, and the executable's properties are written out as JSON beside it. Every other
    file is copied unchanged.

    Raises
    ------
    click.Abort
        If a required helper tool is missing, or SOURCE holds no application bundle.
    """
    log.debug('Reading `%s`.', source)
    try:
        ffmpeg = None if no_audio else locate_tool('ffmpeg', ffmpeg_path)
        pngdefry = None if no_png else locate_tool('pngdefry', pngdefry_path)
    except ToolNotFoundError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    try:
        stats = unpack_download(source, output_dir, ffmpeg=ffmpeg, pngdefry=pngdefry, workers=jobs)
    except (OSError, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    for action, result in stats.items():
        click.echo(f'{action:10} {result.ok} ok, {result.fail} fail')
