"""``dade misc ds-store`` - convert a Finder ``.DS_Store`` desktop database to JSON."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

import click

from dade.common.exceptions import InvalidFormatError
from dade.misc.ds_store import read_ds_store

from .utils import READABLE_FILE, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('ds_store',)

log = logging.getLogger(__name__)


@click.command(name='ds-store')
@click.argument('store', metavar='FILE', type=READABLE_FILE)
@debug_option
def ds_store(store: Path) -> None:
    """
    Convert the Finder desktop database FILE to JSON on standard output.

    Records are grouped by the file name they belong to, and the ``.`` entry belongs to the folder
    itself. Icon positions, window frames, and the property lists that store a view's settings are
    decoded; every other blob is reported as hex. The allocator's blocks, directories, and free
    lists are reported alongside the records.
    """  # ruff: ignore[docstring-missing-exception]
    log.debug('Reading `%s`.', store)
    try:
        converted = read_ds_store(store)
    except (InvalidFormatError, UnicodeDecodeError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(json.dumps(converted, ensure_ascii=False, indent=2, sort_keys=True))
