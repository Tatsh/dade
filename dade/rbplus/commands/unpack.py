"""``dade rbplus unpack`` - convert a whole download to open formats."""
from __future__ import annotations

from pathlib import Path
import logging

import bascom
import click

from dade.common.tools import ToolNotFoundError, locate_tool
from dade.rbplus.pipeline import unpack as unpack_download
from dade.rbplus.render import DEFAULT_SCALE, DEFAULT_SEED, DEFAULT_SPEED, SCALE_RANGE, SPEED_RANGE

__all__ = ('unpack',)

log = logging.getLogger(__name__)

debug_option = bascom.debug_option({'dade.common': {}, 'dade.rbplus': {}})
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
@click.option('--no-images', is_flag=True, help='Skip the rendered chart strips.')
@click.option('--no-png', is_flag=True, help='Leave the PNGs Apple-optimised.')
@click.option('-o',
              '--output-dir',
              default=Path(),
              type=click.Path(file_okay=False, path_type=Path),
              help='Directory to write into (defaults to the current directory).')
@click.option('--scale',
              type=click.FloatRange(*SCALE_RANGE),
              default=DEFAULT_SCALE,
              show_default=True,
              help='Write the chart images this many times their usual size.')
@click.option('--seed',
              type=int,
              default=DEFAULT_SEED,
              help='Pin the lane layout the chart images draw, which is otherwise fresh each run.')
@click.option('--speed',
              type=click.FloatRange(*SPEED_RANGE),
              default=DEFAULT_SPEED,
              show_default=True,
              help='Speed modifier for the chart images, from 1.0 to 2.0 in steps of 0.1.')
@click.option('--pngdefry-path',
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Path to pngdefry, when it is not on PATH.')
def unpack(source: Path,
           output_dir: Path,
           ffmpeg_path: Path | None,
           pngdefry_path: Path | None,
           jobs: int | None,
           scale: float,
           seed: int | None,
           speed: float,
           *,
           no_audio: bool = False,
           no_images: bool = False,
           no_png: bool = False) -> None:
    """
    Unpack and convert the REFLEC BEAT plus download at SOURCE.

    SOURCE may be an ``.ipa``, the ``.app`` bundle, the ``Payload`` directory, or a directory
    holding ``Payload``. It is only read; everything is written under --output-dir, into a
    directory named after the bundle.

    Every ``.rb`` tune package becomes a directory holding its metadata as JSON, its images as
    ordinary PNGs, each note chart as both JSON and a rendered strip, and its audio as ``.m4a``.
    Apple-optimised PNGs are rewritten as ordinary ones, ``.caf`` sound effects become WAV,
    property lists and localisation tables and Core Data models become JSON, and the ``SC_Info``
    bookkeeping is described in one report. Mach-O images are left behind entirely. Every other
    file is copied unchanged.
    """  # noqa: DOC501
    log.debug('Reading `%s`.', source)
    try:
        ffmpeg = None if no_audio else locate_tool('ffmpeg', ffmpeg_path)
        pngdefry = None if no_png else locate_tool('pngdefry', pngdefry_path)
    except ToolNotFoundError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    try:
        stats = unpack_download(source,
                                output_dir,
                                ffmpeg=ffmpeg,
                                pngdefry=pngdefry,
                                render=not no_images,
                                scale=scale,
                                seed=seed,
                                speed=speed,
                                workers=jobs)
    except (OSError, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    for action, result in stats.items():
        click.echo(f'{action:10} {result.ok} ok, {result.fail} fail')
