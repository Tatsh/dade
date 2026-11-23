"""Command-line interface for Mario Kart World assets."""
from __future__ import annotations

from pathlib import Path
import subprocess as sp

import click
import zstandard

from dade.common.tools import ToolNotFoundError

from .extract import extract

__all__ = ('mkw',)


@click.group(context_settings={'help_option_names': ('-h', '--help')})
def mkw() -> None:
    """Convert Mario Kart World assets from an extracted NUP directory."""


@mkw.command()
@click.argument('source', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('-o',
              '--output-dir',
              required=True,
              type=click.Path(file_okay=False, path_type=Path),
              help='Destination directory.')
@click.option('--limit', type=click.IntRange(min=1), help='Inspect at most this many files.')
@click.option('--pattern', default='*', help='Glob pattern of romfs paths to convert.')
@click.option('--force', is_flag=True, help='Replace existing converted files.')
def extract_command(source: Path, output_dir: Path, limit: int | None, pattern: str, *,
                    force: bool) -> None:
    """
    Extract and convert assets from SOURCE.

    Raises
    ------
    click.ClickException
        Conversion failed.
    """
    try:
        counts = extract(source, output_dir, limit, pattern, force=force)
    except (OSError, ValueError, ToolNotFoundError, sp.CalledProcessError,
            zstandard.ZstdError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(', '.join(f'{kind}: {count}' for kind, count in counts.items()))
