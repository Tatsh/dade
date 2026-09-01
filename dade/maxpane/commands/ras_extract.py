"""``dade maxpane ras-extract`` - unpack a RAS archive, MPM package, or disc image."""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
import logging

import click

from dade.common.exceptions import InvalidFormatError
from dade.maxpane.ras import InvalidArchiveError, member_bytes, read_directory

from .sources import NoArchivesFoundError, iter_archives
from .utils import debug_option

__all__ = ('ras_extract',)

log = logging.getLogger(__name__)


def _under(output_dir: Path, path: str) -> Path | None:
    r"""
    Place one member's stored path inside the output directory, or refuse to.

    A member's path is whatever the archive says, and nothing stops an archive naming
    ``..\..\.ssh\authorized_keys``. Anything that would land outside the directory the caller
    asked for is dropped rather than written somewhere it was not wanted.

    Parameters
    ----------
    output_dir : Path
        Directory the caller asked members to be written into.
    path : str
        The member's path, as the archive stores it.

    Returns
    -------
    Path | None
        Where to write the member, or :py:obj:`None` when its path escapes *output_dir*.
    """
    root = output_dir.resolve()
    destination = (root / path).resolve()
    return destination if destination.is_relative_to(root) else None


def _unpack(label: str, data: bytes, patterns: tuple[str, ...], output_dir: Path, *,
            raw: bool) -> tuple[int, int]:
    selected = [
        entry for entry in read_directory(data).entries
        if not patterns or any(fnmatch(entry.path, pattern) for pattern in patterns)
    ]
    log.debug('Extracting %d members from `%s`.', len(selected), label)
    total = written = 0
    for entry in selected:
        if (destination := _under(output_dir, entry.path)) is None:
            log.warning('Skipping `%s`: it would be written outside the output directory.',
                        entry.path)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = member_bytes(data, entry, raw=raw)
        destination.write_bytes(payload)
        total += len(payload)
        written += 1
    return total, written


@click.command(name='ras-extract')
@click.argument('source', type=click.Path(exists=True, path_type=Path))
@click.argument('patterns', nargs=-1)
@click.option('-o',
              '--output-dir',
              default='.',
              help='Directory to write members into.',
              type=click.Path(file_okay=False, path_type=Path))
@click.option('--raw', is_flag=True, help='Keep the RA-> and RC-> wrappers.')
@debug_option
def ras_extract(source: Path, patterns: tuple[str, ...], output_dir: Path, *, raw: bool) -> None:
    """
    Extract members of the archives named by SOURCE into the output directory.

    SOURCE is a RAS archive, an MPM mod package, an ISO image, or the cue sheet of a cue/bin pair.
    Every archive on a disc image is extracted, all into the same tree, which reproduces the layout
    the game itself sees because the archives share one namespace.

    PATTERNS are globs matched against each member's full in-archive path. Every member is
    extracted when none are given.
    """  # noqa: DOC501
    total = 0
    count = 0
    try:
        for label, data in iter_archives(source):
            written_bytes, written_members = _unpack(label, data, patterns, output_dir, raw=raw)
            total += written_bytes
            count += written_members
    except (InvalidArchiveError, InvalidFormatError, NoArchivesFoundError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(f'{count} members, {total} bytes written to {output_dir}.')
