"""Command-line entry point for the Monopoly 2008 asset extractor."""
from __future__ import annotations

from pathlib import Path

from bascom import setup_logging
import click

from .pipeline import run

__all__ = ('main',)


@click.command(context_settings={'help_option_names': ('-h', '--help')})
@click.argument('root', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable verbose logging.')
@click.option('-j',
              '--workers',
              type=int,
              default=None,
              help='Process-pool size (defaults to the CPU count).')
@click.option('--no-movies', is_flag=True, help='Skip extracting the large movie archives.')
def main(root: Path,
         *,
         debug: bool = False,
         workers: int | None = None,
         no_movies: bool = False) -> None:
    """
    Unpack and convert an extracted Monopoly 2008 disc ROOT in place.

    ROOT must be the root of an extracted disc image. The platform is detected
    automatically, and every output is written next to its source file inside ROOT.

    Parameters
    ----------
    root : pathlib.Path
        The extracted disc root.
    debug : bool
        Enable verbose (DEBUG-level) logging.
    workers : int | None
        Process-pool size; defaults to the CPU count.
    no_movies : bool
        Skip extracting the large movie archives.
    """
    setup_logging(debug=debug, loggers={'destin.common': {}, 'destin.monopoly08': {}})
    stats = run(root, no_movies=no_movies, workers=workers)
    for step, result in stats.items():
        click.echo(f'{step:10} {result.ok} ok, {result.fail} fail')
