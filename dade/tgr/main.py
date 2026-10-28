"""Command-line interface for the Top Gear Rally asset extractor."""
from __future__ import annotations

from pathlib import Path
import logging

import bascom
import click

from dade.common.exceptions import InvalidFormatError
from dade.common.tools import ToolNotFoundError, locate_tool

from .n64 import extract_rom
from .pc import extract_disc

__all__ = ('tgr',)

log = logging.getLogger(__name__)

_CONTEXT_SETTINGS = {'help_option_names': ('-h', '--help')}
_ROM_SUFFIXES = frozenset({'.n64', '.v64', '.z64'})

debug_option = bascom.debug_option({'dade.common': {}, 'dade.tgr': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


@click.group(context_settings=_CONTEXT_SETTINGS)
def tgr() -> None:
    """Top Gear Rally (Nintendo 64) and Boss Rally (Windows) assets."""


@tgr.command(context_settings=_CONTEXT_SETTINGS)
@click.argument('sources', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option('-o',
              '--output-dir',
              default=Path(),
              type=click.Path(file_okay=False, path_type=Path),
              help='Directory to write to.')
@click.option('--ffmpeg-path',
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Path to ffmpeg, used to render the music and to encode the CD audio.')
@click.option('--no-audio', is_flag=True, help='Skip rendering the music and the CD audio.')
@debug_option
def extract(sources: tuple[Path, ...],
            output_dir: Path,
            ffmpeg_path: Path | None = None,
            *,
            no_audio: bool = False) -> None:
    """
    Convert every asset of cartridge images and of the Boss Rally disc.

    Each SOURCE is a cartridge image (.z64, .v64, or .n64), a directory of the disc or of an
    installation, an ISO image, or the cue sheet or .bin of a cue/bin pair.
    """  # ruff: ignore[docstring-missing-exception]
    ffmpeg = None
    if not no_audio:
        try:
            ffmpeg = locate_tool('ffmpeg', ffmpeg_path)
        except ToolNotFoundError as e:
            log.warning('%s The audio is skipped.', e)
    for source in sources:
        try:
            if source.is_file() and source.suffix.lower() in _ROM_SUFFIXES:
                extract_rom(source, output_dir / 'n64', ffmpeg)
            else:
                extract_disc(source, output_dir / 'pc', ffmpeg)
        except InvalidFormatError as e:
            click.echo(f'{source}: {e}', err=True)
            raise click.Abort from e
