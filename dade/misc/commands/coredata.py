"""``dade misc coredata`` - convert a compiled Core Data model to JSON or SQL."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

import click

from dade.misc.coredata import build_sql, convert, load_mom_column_types

from .utils import READABLE_FILE, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('coredata',)

log = logging.getLogger(__name__)


@click.command()
@click.argument('model', metavar='MODEL', type=READABLE_FILE)
@click.option('--archive',
              is_flag=True,
              help='Dump the raw keyed-archive object graph rather than the model it encodes.')
@click.option('--mom',
              type=READABLE_FILE,
              help='Take column types and entity ordinals from this compiled destination model.')
@click.option('--sql', is_flag=True, help='Emit the effective SQLite script instead of JSON.')
@debug_option
def coredata(model: Path, mom: Path | None, *, archive: bool, sql: bool) -> None:
    """
    Convert the compiled Core Data model MODEL to JSON on standard output.

    A ``.cdm`` is a compiled mapping model and a ``.mom`` a compiled managed object model; both are
    keyed archives, and each is dispatched on the class at its root. The ``.omo`` beside a
    current-version ``.mom`` is deliberately unsupported: it is Core Data's undocumented load-time
    cache of that same model and carries nothing the ``.mom`` lacks.
    """  # noqa: DOC501
    log.debug('Reading `%s`.', model)
    try:
        converted = convert(model, archive_mode=archive)
        if sql:
            click.echo(build_sql(converted, load_mom_column_types(mom) if mom else None), nl=False)
            return
    except (KeyError, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(json.dumps(converted, ensure_ascii=False, indent=2, sort_keys=True))
