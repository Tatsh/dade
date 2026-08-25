"""``dade rhythmin dump-chara`` - decrypt a ``.chr`` character-data file."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

import click

from dade.rhythmin.chara import decrypt_chara, parse_chara

from .utils import READABLE_FILE, debug_option, echo_json

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('dump_chara',)

log = logging.getLogger(__name__)


@click.command(name='dump-chara')
@click.argument('chara', metavar='CHR', type=READABLE_FILE)
@click.option('--raw', is_flag=True, help='Write the decrypted bytes verbatim instead of JSON.')
@debug_option
def dump_chara(chara: Path, *, raw: bool) -> None:
    """
    Decrypt the character-data file CHR and write it to standard output as JSON.

    Raises
    ------
    click.Abort
        If CHR is not an encrypted payload, or its plaintext is not the JSON it should be, which
        usually means it belongs to another game or another key.
    """
    log.debug('Reading `%s`.', chara)
    try:
        payload = decrypt_chara(chara.read_bytes())
    except ValueError as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if raw:
        click.get_binary_stream('stdout').write(payload)
        return
    try:
        echo_json(parse_chara(payload))
    except json.JSONDecodeError as e:
        click.echo(f'The decrypted payload is not JSON: {e}. Pass --raw to inspect it.', err=True)
        raise click.Abort from e
