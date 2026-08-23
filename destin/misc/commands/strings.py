"""``destin misc strings`` - convert an Xcode ``.strings`` table to JSON."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

import click

from destin.misc.strings import read_strings

from .utils import READABLE_FILE, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('strings',)

log = logging.getLogger(__name__)


@click.command()
@click.argument('table', metavar='STRINGS', type=READABLE_FILE)
@debug_option
def strings(table: Path) -> None:
    """
    Convert the localisation table STRINGS to JSON on standard output.

    Both forms are read: the flat binary plist a compiled table ships as, and the old-style text
    form an uncompiled one keeps.

    Raises
    ------
    click.Abort
        If STRINGS is neither form of table.
    """
    log.debug('Reading `%s`.', table)
    try:
        converted = read_strings(table)
    except (UnicodeDecodeError, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(json.dumps(converted, ensure_ascii=False, indent=2, sort_keys=True))
