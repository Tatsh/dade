"""Command-line interface for the In The Groove PS2 asset extractor."""
from __future__ import annotations

from pathlib import Path
import logging

import bascom
import click

from dade.common.exceptions import InvalidFormatError
from dade.common.tools import ToolNotFoundError, locate_tool
from dade.common.workers import default_jobs

from .extract import extract_disc

__all__ = ('itgps2',)

log = logging.getLogger(__name__)

_CONTEXT_SETTINGS = {'help_option_names': ('-h', '--help')}

debug_option = bascom.debug_option({'dade.common': {}, 'dade.itgps2': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


@click.group(context_settings=_CONTEXT_SETTINGS)
def itgps2() -> None:
    """In The Groove and In The Groove 2 (PlayStation 2) assets."""


@itgps2.command(context_settings=_CONTEXT_SETTINGS)
@click.argument('sources', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option('-o',
              '--output-dir',
              default=Path(),
              type=click.Path(file_okay=False, path_type=Path),
              help='Directory to write to.')
@click.option('--ffmpeg-path',
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Path to ffmpeg, used to write the movies.')
@click.option('-j',
              '--jobs',
              default=default_jobs,
              type=click.IntRange(min=1),
              help='Number of streams to convert at once.')
@click.option('--no-video', is_flag=True, help='Skip writing the movies.')
@debug_option
def extract(sources: tuple[Path, ...],
            output_dir: Path,
            ffmpeg_path: Path | None = None,
            jobs: int = 1,
            *,
            no_video: bool = False) -> None:
    """
    Convert In The Groove PS2 discs to StepMania songs, courses, and themes.

    Each SOURCE is an ISO image of a disc or a directory of its files. Each release is written to a
    directory identifying it (itg or itg2-beta).
    """  # ruff: ignore[docstring-missing-exception]
    ffmpeg = None
    if not no_video:
        try:
            ffmpeg = locate_tool('ffmpeg', ffmpeg_path)
        except ToolNotFoundError as e:
            log.warning('%s The movies are skipped.', e)
    for source in sources:
        try:
            release, counts = extract_disc(source, output_dir, ffmpeg, jobs)
        except InvalidFormatError as e:
            click.echo(f'{source}: {e}', err=True)
            raise click.Abort from e
        click.echo(f'{output_dir / release}: ' +
                   ', '.join(f'{kind}: {count}' for kind, count in sorted(counts.items())))
