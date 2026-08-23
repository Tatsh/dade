"""The ``unbitrock`` command: extract or list InstallBuilder installer members."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import bascom
import click

from destin.bitrock.archive import InstallBuilderFile
from destin.bitrock.exceptions import BitrockError
from destin.bitrock.unpack import unpack

if TYPE_CHECKING:
    from destin.bitrock.typing import PageCompression

__all__ = ('extract_main',)

debug_option = bascom.debug_option({'destin.bitrock': {}, 'destin.common': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


def _members(count: int) -> str:
    """
    Return a member count phrase, pluralised.

    Parameters
    ----------
    count : int
        Number of members.

    Returns
    -------
    str
        For example ``'1 member'`` or ``'3 members'``.
    """
    return f'{count} member{"" if count == 1 else "s"}'


def _list_members(archive: Path) -> None:
    """
    Print each member and its size, followed by a total, in the manner of ``unzip -l``.

    Parameters
    ----------
    archive : :py:class:`~pathlib.Path`
        Path to the installer to list.
    """
    with InstallBuilderFile(archive) as opened:
        names = opened.namelist
        total = 0
        click.echo(f'{"Length":>12}  Name')
        click.echo(f'{"-" * 12}  {"-" * 4}')
        for name in names:
            size = opened.get_size(name)
            total += size
            click.echo(f'{size:>12}  {name}')
        click.echo(f'{"-" * 12}  {"-" * 4}')
        click.echo(f'{total:>12}  {_members(len(names))}')


@click.command(context_settings={'help_option_names': ('-h', '--help')})
@click.argument('archive', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('members', nargs=-1)
@click.option('-l', '--list', 'list_', is_flag=True, help='List the archive members and exit.')
@click.option('-o',
              '--output-dir',
              default='.',
              type=click.Path(file_okay=False, path_type=Path),
              help='Extract into this directory.')
@click.option('-p', '--password', help='Password for an encrypted installer.')
@click.option('-c',
              '--compression',
              type=click.Choice(('zip', 'lzma', 'lzham')),
              default=None,
              help='Override the auto-detected page compression for encrypted installers.')
@click.option('-n',
              '--dry-run',
              is_flag=True,
              help='Show what would be extracted without writing anything.')
@click.option('-q', '--quiet', is_flag=True, help='Do not print each member as it is extracted.')
@debug_option
@click.version_option()
def extract_main(archive: Path, members: tuple[str, ...], output_dir: Path, password: str | None,
                 compression: str | None, *, list_: bool, dry_run: bool, quiet: bool) -> None:
    """
    Extract or list the contents of an InstallBuilder installer.

    With no MEMBERS, every member is extracted; otherwise only the named members are. Paths are
    those shown by ``--list``. Encrypted installers prompt for a password when one is not given.
    """  # noqa: DOC501
    try:
        if list_:
            _list_members(archive)
            return
        with InstallBuilderFile(archive) as probe:
            needs_password = probe.is_encrypted
    except BitrockError as e:
        raise click.ClickException(str(e)) from e
    if needs_password and not password:
        password = click.prompt('Password', hide_input=True)
    try:
        results = list(
            unpack(archive,
                   output_dir,
                   members or None,
                   password=password,
                   page_compression=cast('PageCompression | None', compression),
                   dry_run=dry_run))
    except BitrockError as e:
        raise click.ClickException(str(e)) from e
    if not quiet:
        verb = 'would extract' if dry_run else 'extracting'
        for result in results:
            click.echo(f'  {verb}: {result.path}')
    click.echo(f'{_members(len(results))} {"listed" if dry_run else "extracted"}.', err=True)
