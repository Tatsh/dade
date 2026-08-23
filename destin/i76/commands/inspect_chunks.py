"""``destin i76 inspect-chunks`` - dump the FOURCC chunk tree of a BWD2 container."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import logging

import click

from destin.i76.bwd2 import DEFAULT_CONTAINER_TAGS, ascii_strings, walk

from .utils import debug_option

if TYPE_CHECKING:
    from collections.abc import Iterable

    from destin.i76.typing import Chunk

__all__ = ('inspect_chunks',)

log = logging.getLogger(__name__)

_HEAD_BYTES = 48
"""Number of payload bytes shown for a leaf chunk.

:meta hide-value:
"""
_MAX_STRINGS = 10
"""Number of printable runs shown for a leaf chunk.

:meta hide-value:
"""


def _render(chunks: Iterable[Chunk], depth: int) -> None:
    """
    Print a chunk tree.

    Parameters
    ----------
    chunks : collections.abc.Iterable[Chunk]
        The chunks to print.
    depth : int
        Current nesting depth, used for indentation.
    """
    indent = '  ' * depth
    for chunk in chunks:
        payload_length = chunk.size - 8
        if chunk.children:
            click.echo(f'{indent}{chunk.tag} (container) total={chunk.size} '
                       f'payload={payload_length} @{chunk.offset:#x}')
            _render(chunk.children, depth + 1)
        else:
            strings = ascii_strings(chunk.payload)
            extra = f' strs={list(strings[:_MAX_STRINGS])}' if strings else ''
            click.echo(f'{indent}{chunk.tag} total={chunk.size} payload={payload_length} '
                       f'head={chunk.payload[:_HEAD_BYTES].hex()}{extra}')


@click.command(name='inspect-chunks')
@click.argument('container', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--container-tags',
              default=None,
              help='Comma-separated chunk tags to treat as containers.')
@debug_option
def inspect_chunks(container: Path, container_tags: str | None) -> None:
    """
    Dump the chunk tree of BWD2 container CONTAINER.

    Which tags nest further chunks is not recorded in the file, so the container tags default to
    the set observed in the shipped missions and can be overridden with ``--container-tags``.
    """
    tags = DEFAULT_CONTAINER_TAGS if container_tags is None else set(container_tags.split(','))
    data = container.read_bytes()
    click.echo(f'{container}: {len(data)} bytes')
    _render(walk(data, tags), 0)
