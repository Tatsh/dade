"""``dade misc macho`` - describe a Mach-O executable."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

import click

from dade.misc.macho import read_macho

from .utils import READABLE_FILE, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('dump', 'macho')

log = logging.getLogger(__name__)


@click.group(name='macho', context_settings={'help_option_names': ('-h', '--help')})
def macho() -> None:
    """Read the properties of a Mach-O executable."""


@macho.command()
@click.argument('path', metavar='BINARY', type=READABLE_FILE)
@debug_option
def dump(path: Path) -> None:
    """
    Write BINARY's properties as JSON.

    BINARY is a Mach-O image: an application's executable, a framework, or a dynamic library, thin
    or universal. Every architecture slice is read.

    The report covers the header and its flags, the segments and their sections, the libraries the
    image links, its UUID and source version, the minimum OS it declares, the entitlements inside
    its code signature, and, for an image bought from the App Store, the LC_ENCRYPTION_INFO command
    that says its text is still enciphered. Nothing is decrypted and no code is disassembled.
    """  # noqa: DOC501
    log.debug('Reading `%s`.', path)
    try:
        info = read_macho(path)
    except (OSError, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    click.echo(json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True))
