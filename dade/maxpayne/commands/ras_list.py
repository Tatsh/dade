"""``dade maxpayne ras-list`` - show the directory of a RAS archive, MPM package, or disc image."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import logging

import click

from dade.common.exceptions import InvalidFormatError
from dade.maxpayne.ras import InvalidArchiveError, read_directory

from .sources import NoArchivesFoundError, iter_archives
from .utils import debug_option

__all__ = ('ras_list',)

log = logging.getLogger(__name__)


def _describe(label: str, data: bytes, report: dict[str, list[dict[str, object]]] | None) -> None:
    contents = read_directory(data)
    if report is not None:
        report[label] = [{
            'modified': entry.modified,
            'path': entry.path,
            'size': entry.size,
            'stored_size': entry.stored_size
        } for entry in contents.entries]
        return
    histogram = Counter(
        entry.name.rsplit('.', 1)[-1].lower() if '.' in entry.name else '<none>'
        for entry in contents.entries)
    intact = 'intact' if contents.data_end == len(data) else 'TRUNCATED'
    click.echo(f'{label}: v{contents.header.version:.2f}, '
               f'{contents.header.file_count} members in '
               f'{contents.header.directory_count} directories, {intact}.')
    click.echo(f'By extension: {dict(histogram.most_common())}')
    for entry in contents.entries:
        click.echo(f'  {entry.size:>10d}  {entry.modified or "":<24s}  {entry.path}')


@click.command(name='ras-list')
@click.argument('sources', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option('--json', 'as_json', is_flag=True, help='Print the directory as JSON.')
@debug_option
def ras_list(sources: tuple[Path, ...], *, as_json: bool) -> None:
    """
    List the members of the archives named by SOURCES.

    SOURCES are RAS archives, MPM mod packages, directories, InstallShield cabinets, or disc
    images -- an ISO, a cue sheet, or a bare BIN. Give every disc a game shipped on: Max
    Payne 2 splits its cabinet across two, and the parts are gathered from all of them
    before it is unpacked.
    Every archive on a disc image is listed. For each archive this prints the format version,
    member and directory counts, a histogram of member extensions, and one line per member.

    An archive is reported intact when its header, both tables, and every stored size together
    account for the file exactly.
    """  # noqa: DOC501
    report: dict[str, list[dict[str, object]]] = {}
    try:
        for label, data in iter_archives(*sources):
            _describe(label, data, report if as_json else None)
    except (InvalidArchiveError, InvalidFormatError, NoArchivesFoundError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if as_json:
        click.echo(json.dumps(report, indent=2, sort_keys=True))
