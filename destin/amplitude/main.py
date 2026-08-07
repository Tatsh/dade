"""Command-line entry point for the Amplitude game unpacker."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import asyncio

from destin.amplitude.unpacker import AmplitudeUnpacker
from rich.console import Console
import bascom
import click

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ('main',)

console = Console()
"""The shared Rich :py:class:`~rich.console.Console` used for the progress spinner.

:meta hide-value:
"""

debug_option = bascom.debug_option({
    'destin.amplitude': {},
    'destin.common': {},
    'destin.harmonix': {}
})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


@click.command(context_settings={'help_option_names': ('-h', '--help')})
@click.argument('input_', metavar='DISC', type=click.Path(exists=True, path_type=Path))
@debug_option
@click.option('-o',
              '--output-dir',
              type=click.Path(file_okay=False, path_type=Path),
              default=Path(),
              help='Output directory (created if missing).')
@click.option('-j',
              '--jobs',
              type=click.IntRange(min=0),
              default=0,
              help='Number of concurrent workers; 0 uses all CPUs.')
@click.option('--no-convert', is_flag=True, help='Extract assets without converting them.')
@click.option('--no-gunzip',
              is_flag=True,
              help='Extract .gz entries verbatim instead of decompressing.')
@click.option('--keep-gz',
              is_flag=True,
              help='Keep the original .gz entry alongside the decompressed output.')
@click.option('--ignore-failures',
              is_flag=True,
              help='Log and skip a conversion failure instead of stopping.')
def main(input_: Path,
         *,
         output_dir: Path = Path(),
         jobs: int = 0,
         no_convert: bool = False,
         no_gunzip: bool = False,
         keep_gz: bool = False,
         ignore_failures: bool = False) -> None:
    """Unpack a PS2 Amplitude disc (directory or ISO image) and convert its assets."""
    unpacker = AmplitudeUnpacker(input_)

    async def run(on_status: Callable[[str], None] | None) -> dict[str, str]:
        return await unpacker.unpack(output_dir,
                                     convert=not no_convert,
                                     gunzip=not no_gunzip,
                                     ignore_failures=ignore_failures,
                                     jobs=jobs,
                                     keep_gz=keep_gz,
                                     on_status=on_status)

    # With ``--debug`` the streaming debug log owns the terminal, so no live spinner is started.
    if click.get_current_context().params.get('debug', False):
        stats = asyncio.run(run(None))
    else:
        with console.status('Unpacking...') as status:
            stats = asyncio.run(run(status.update))
    for label, summary in stats.items():
        click.echo(f'{label}: {summary}')
