"""``dade rhythmin extract-dialogue`` - lift the sugoroku dialogue pools from an app binary."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging

import click

from dade.rhythmin.dialogue import empty_pools, extract_pools, render_binary, render_c_header

from .utils import READABLE_FILE, WRITABLE_FILE, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('extract_dialogue',)

log = logging.getLogger(__name__)


@click.command(name='extract-dialogue')
@click.argument('output', metavar='OUTPUT', type=WRITABLE_FILE)
@click.option('-b',
              '--binary',
              type=READABLE_FILE,
              help='App binary to read the pools out of; without it the tables are written empty.')
@click.option('-f',
              '--format',
              'output_format',
              type=click.Choice(('binary', 'c')),
              default='c',
              show_default=True,
              help='Write the compiled-in C header or the runtime binary asset.')
@debug_option
def extract_dialogue(output: Path, binary: Path | None, output_format: str) -> None:
    """
    Write the sugoroku board dialogue pools from an app binary to OUTPUT.

    The dialogue is copyrighted game content and is not shipped with this package; point --binary
    at a copy of the app you own. Without it the tables are written out empty, which is what a
    build does when no binary is available.

    Raises
    ------
    click.Abort
        If --binary is not a 32-bit Mach-O holding the pools at the addresses this expects.
    """
    if binary is None:
        pools = empty_pools()
        log.debug('No binary given; writing empty tables to `%s`.', output)
    else:
        log.debug('Reading `%s`.', binary)
        try:
            pools = extract_pools(binary.read_bytes())
        except ValueError as e:
            click.echo(str(e), err=True)
            raise click.Abort from e
    if output_format == 'c':
        output.write_text(render_c_header(pools), encoding='utf-8')
    else:
        output.write_bytes(render_binary(pools))
    total = sum(len(pool.strings) for pool in pools)
    content = sum(len(text) for pool in pools for text in pool.strings)
    click.echo(f'Wrote {total} strings, {content} content bytes to {output} ({output_format}).',
               err=True)
