"""``dade rhythmin dump-idx`` - decode an AEP ``.idx`` animation index."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import struct

import click

from dade.rhythmin.aep import entry_to_json, index_to_json, read_aep_index

from .utils import READABLE_FILE, debug_option, echo_json

if TYPE_CHECKING:
    from pathlib import Path

    from dade.rhythmin.aep import AepIndex

__all__ = ('dump_idx',)

log = logging.getLogger(__name__)

_GROUP = 'group'


def _layer_json(index: AepIndex, layer: str) -> dict[str, object]:
    """
    Render one layer's chain.

    Parameters
    ----------
    index : dade.rhythmin.aep.AepIndex
        The index to read.
    layer : str
        The layer's name.

    Returns
    -------
    dict[str, object]
        The layer's ordinal, entry index, and chain.

    Raises
    ------
    KeyError
        If the index holds no such layer.
    """
    ordinal = index.layer_names.index(layer) if layer in index.layer_names else -1
    if ordinal < 0:
        msg = f'{layer!r} is not a layer name in this index.'
        raise KeyError(msg)
    return {
        'layer': layer,
        'ordinal': ordinal,
        'entryIndex': index.layer_numbers[ordinal],
        'entries': [entry_to_json(index, entry) for entry in index.layer_chain(layer)],
    }


def _found_json(index: AepIndex, wanted: str) -> dict[str, object]:
    """
    Render where a name appears, and the group entries that refer to it.

    A group entry's child is a user-name ordinal, so when the name is a user name only the entries
    pointing at it are listed; otherwise every group entry is, which is what the original survey
    of an index shows.

    Parameters
    ----------
    index : dade.rhythmin.aep.AepIndex
        The index to read.
    wanted : str
        The name to look for.

    Returns
    -------
    dict[str, object]
        The name's locations and the relevant group entries.
    """
    target = index.user_names.index(wanted) if wanted in index.user_names else None
    return {
        'name':
            wanted,
        'locations': [{
            'block': location.block,
            'ordinal': location.ordinal,
            'sprite': location.sprite._asdict() if location.sprite is not None else None,
        } for location in index.find(wanted)],
        'groupEntries': [
            entry_to_json(index, entry) for entry in index.frame_entries
            if entry.type_name == _GROUP and (target is None or entry.child == target)
        ],
    }


def _render(index_path: Path, wanted: str | None, layer: str | None, *,
            names: bool) -> dict[str, object]:
    """
    Read an index and render whichever view was asked for.

    Parameters
    ----------
    index_path : pathlib.Path
        The ``.idx`` to read.
    wanted : str | None
        A name to locate, or ``None``.
    layer : str | None
        A layer whose chain to emit, or ``None``.
    names : bool
        Emit only the header and the name blocks.

    Returns
    -------
    dict[str, object]
        The rendered view.
    """
    index = read_aep_index(index_path)
    if layer is not None:
        return _layer_json(index, layer)
    if wanted is not None:
        return _found_json(index, wanted)
    return index_to_json(index, names_only=names)


@click.command(name='dump-idx')
@click.argument('index_path', metavar='IDX', type=READABLE_FILE)
@click.option('--find',
              'wanted',
              metavar='NAME',
              help='Emit only where NAME appears, and the group entries that refer to it.')
@click.option('--layer',
              metavar='NAME',
              help="Emit only layer NAME's frame-entry chain, with its channels decoded.")
@click.option('--names', is_flag=True, help='Emit only the header and the three name blocks.')
@debug_option
def dump_idx(index_path: Path, wanted: str | None, layer: str | None, *, names: bool) -> None:
    """Decode the animation index IDX and write it to standard output as JSON."""  # noqa: DOC501
    log.debug('Reading `%s`.', index_path)
    try:
        rendered = _render(index_path, wanted, layer, names=names)
    except (KeyError, ValueError, struct.error) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    echo_json(rendered)
