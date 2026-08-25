"""``dade i76 zfs-list`` - show the directory of a ZFSF or ZFS3 archive."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import logging

import click

from dade.i76.zfs import InvalidArchiveError, archive_format, read_directory

from .utils import debug_option

__all__ = ('zfs_list',)

log = logging.getLogger(__name__)


@click.command(name='zfs-list')
@click.argument('archive', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--json', 'as_json', is_flag=True, help='Print the directory as JSON.')
@debug_option
def zfs_list(archive: Path, *, as_json: bool) -> None:
    """
    List the members of ZFS archive ARCHIVE.

    Prints the archive format, a histogram of member extensions, and one line per member giving its
    offset, stored size, and compression flags.

    Raises
    ------
    click.Abort
        If ARCHIVE is not a ZFS archive.
    """
    data = archive.read_bytes()
    try:
        name = archive_format(data)
    except InvalidArchiveError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    entries = read_directory(data)
    if as_json:
        click.echo(
            json.dumps([{
                'flags': entry.flags,
                'name': entry.name,
                'offset': entry.offset,
                'size': entry.size
            } for entry in entries],
                       indent=2,
                       sort_keys=True))
        return
    histogram = Counter(
        entry.name.rsplit('.', 1)[-1].lower() if '.' in entry.name else '<none>'
        for entry in entries)
    click.echo(f'{archive.name}: {name.upper()}, {len(entries)} entries.')
    click.echo(f'By extension: {dict(histogram.most_common())}')
    for entry in entries:
        click.echo(f'  {entry.name:20s} offset=0x{entry.offset:<8x} '
                   f'size={entry.size:<9d} flags={entry.flags}')
