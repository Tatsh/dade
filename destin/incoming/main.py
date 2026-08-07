"""Command-line interface."""
from __future__ import annotations

from tempfile import TemporaryDirectory
import asyncio
import logging
import pathlib

from anyio import Path
from destin import __version__
from destin.common.context import using_tool_paths
from destin.common.utils import pluralize
from destin.common.workers import default_jobs
import bascom
import click

from .dispatch import run_conversions
from .sources import SourceError, prepare_source
from .tools import ToolNotFoundError

__all__ = ('main',)

log = logging.getLogger(__name__)

debug_option = bascom.debug_option({'destin.common': {}, 'destin.incoming': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


async def _run(source: pathlib.Path, output: Path, *, jobs: int | None,
               tools: dict[str, pathlib.Path | None]) -> int:
    """
    Prepare *source* and convert it into *output* with a pool of worker tasks.

    Parameters
    ----------
    source : pathlib.Path
        The source disc, GDI, archive, or extracted directory.
    output : anyio.Path
        The output directory the source tree is mirrored into.
    jobs : int | None
        Number of concurrent jobs; defaults to the CPU count when not positive or ``None``.
    tools : dict[str, pathlib.Path | None]
        Optional override paths for the native helper tools.

    Returns
    -------
    int
        The process exit code (1 if any conversion failed, otherwise 0).

    Raises
    ------
    click.Abort
        If the source cannot be prepared.
    """
    await output.mkdir(parents=True, exist_ok=True)
    concurrency = jobs if jobs and jobs > 0 else default_jobs()
    with using_tool_paths(tools), TemporaryDirectory() as work:
        try:
            prepared = await asyncio.to_thread(prepare_source, source, pathlib.Path(work))
        except (SourceError, ToolNotFoundError) as e:
            log.error('%s', e)  # ruff:ignore[error-instead-of-exception]
            raise click.Abort from e
        summary = await run_conversions(prepared, output, jobs=concurrency)
    click.echo(f'Converted {pluralize(summary.converted, "file")} into '
               f'{pluralize(summary.produced, "output")}; copied {summary.copied} '
               f'(skipped {summary.skipped}), failed {summary.failed}.')
    return 1 if summary.failed else 0


@click.command(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option(__version__)
@debug_option
@click.option('-j',
              '--jobs',
              type=int,
              default=None,
              help='Number of concurrent conversion jobs; defaults to the CPU count.')
@click.option('-o',
              '--output',
              required=True,
              type=click.Path(file_okay=False, path_type=Path),
              help='Output directory; the source tree is mirrored into it.')
@click.option('--gdiextract-path',
              type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
              help='Path to the gdiextract binary.')
@click.option('--spvr2png-path',
              type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
              help='Path to the spvr2png binary.')
@click.option('--unshield-path',
              type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
              help='Path to the unshield binary.')
@click.argument('source', type=click.Path(exists=True, path_type=pathlib.Path, resolve_path=True))
def main(source: pathlib.Path,
         output: Path,
         *,
         jobs: int | None = None,
         gdiextract_path: pathlib.Path | None = None,
         spvr2png_path: pathlib.Path | None = None,
         unshield_path: pathlib.Path | None = None) -> None:
    """
    Extract and convert Incoming assets from SOURCE into the output directory.

    SOURCE may be a PC disc directory or ISO containing DATA1.CAB (or the DATA1.CAB itself), a
    Dreamcast GDI file, or a directory of already extracted PC or GD-ROM content. The source tree is
    mirrored into the output directory: recognised assets are converted and every other file is
    copied verbatim. The source is never modified.
    """  # ruff:ignore[docstring-missing-exception]
    tools = {'gdiextract': gdiextract_path, 'spvr2png': spvr2png_path, 'unshield': unshield_path}
    if asyncio.run(_run(source, output, jobs=jobs, tools=tools)):
        raise click.exceptions.Exit(1)
