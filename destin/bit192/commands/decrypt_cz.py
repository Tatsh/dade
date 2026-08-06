"""``tonesphere decrypt-cz`` - undo the ``.cz`` XOR layer to recover a Derbh archive."""
from __future__ import annotations

from pathlib import Path
import logging

from destin.bit192 import cz
import click

from .utils import console, debug_option

__all__ = ('decrypt_cz',)

log = logging.getLogger(__name__)


@click.command(name='decrypt-cz')
@click.argument('source', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('dest', type=click.Path(dir_okay=False, path_type=Path))
@debug_option
def decrypt_cz(source: Path, dest: Path) -> None:
    """
    Decrypt SOURCE (a ``.cz`` file) to DEST (a Derbh ``.dz`` archive).

    Unpack DEST afterwards with ``marm extract-dz``.
    """
    log.debug('Decrypting %s to %s.', source, dest)
    data = cz.decrypt(source.read_bytes())
    if data[:4] != b'DTRZ':
        console.print('[yellow]Warning:[/yellow] the result is not a Derbh archive (wrong keys?).')
    dest.write_bytes(data)
    console.print(f'[green]Decrypted {source.name} to {dest}.[/green]')
