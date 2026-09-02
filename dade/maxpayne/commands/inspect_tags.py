"""``dade maxpayne inspect-tags`` - summarise the tagged stream inside a Max Payne asset."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import logging

import click

from dade.maxpayne.blocks import unwrap
from dade.maxpayne.memoryfile import BasicType, iter_values

from .utils import debug_option

__all__ = ('inspect_tags',)

log = logging.getLogger(__name__)


@click.command(name='inspect-tags')
@click.argument('asset', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-n', '--limit', default=32, help='Number of leading values to print.', type=int)
@debug_option
def inspect_tags(asset: Path, limit: int) -> None:
    """
    Decode the tagged R_MemoryFile stream at the start of ASSET.

    Accepts a loose file or one still wrapped in RA-> or RC-> blocks. Walks from the first byte and
    stops where the stream leaves tagged territory, which happens as soon as untagged bulk data
    such as a string or lightmap begins. Prints where it stopped so the boundary is visible.
    """
    data, layers = unwrap(asset.read_bytes())
    if layers:
        click.echo(f'Unwrapped: {" -> ".join(layers)}.')
    histogram: Counter[str] = Counter()
    reached = 0
    for index, value in enumerate(iter_values(data)):
        histogram[BasicType(value.tag).name] += 1
        reached = value.end
        if index < limit:
            shown = (repr(value.payload.decode('latin-1'))
                     if value.tag == BasicType.STRING else value.payload.hex(' '))
            click.echo(f'  0x{value.offset:08x}  {BasicType(value.tag).name:<10s} {shown}')
    # An asset that unwrapped to nothing has been walked in full, vacuously.
    covered = 100.0 * reached / len(data) if data else 100.0
    click.echo(f'{asset.name}: {len(data)} bytes, walked to {reached} ({covered:.2f}%).')
    click.echo(f'By tag: {dict(histogram.most_common())}')
    if reached < len(data):
        click.echo(f'Stopped on 0x{data[reached]:02x} at offset {reached}.')
