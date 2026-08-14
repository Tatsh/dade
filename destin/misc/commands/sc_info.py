"""``destin misc sc-info`` - describe the FairPlay bookkeeping in a purchased ``.app`` bundle."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

from destin.misc.sc_info import read_sc_info, render_text, sc_info_to_json
import click

from .utils import READABLE_DIR, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('dump', 'sc_info')

log = logging.getLogger(__name__)


@click.group(name='sc-info', context_settings={'help_option_names': ('-h', '--help')})
def sc_info() -> None:
    """Read the SC_Info directory of a purchased application bundle."""


@sc_info.command()
@click.argument('path', metavar='PATH', type=READABLE_DIR)
@click.option('--json', 'as_json', is_flag=True, help='Print JSON instead of a readable report.')
@click.option('--region',
              metavar='CC',
              help='Country code to build the App Store link with, such as jp, when the bundle '
              'has no iTunesMetadata.plist beside it to read the storefront from.')
@debug_option
def dump(path: Path, region: str | None, *, as_json: bool) -> None:
    """
    Describe the SC_Info content at PATH.

    PATH may be the SC_Info directory itself, the ``.app`` bundle holding it, or a directory
    holding that bundle, so pointing at an unpacked ``Payload`` works.

    Nothing here is decrypted and none of it is a key: the report covers the purchase record, the
    embedded Apple FairPlay certificates, and the length, digest, and entropy of the key material.

    The App Store link needs a storefront, which is read from an iTunesMetadata.plist beside the
    bundle when there is one. Without that, pass --region.

    Raises
    ------
    click.Abort
        If there is no SC_Info directory at or below PATH.
    """
    log.debug('Reading `%s`.', path)
    try:
        info = read_sc_info(path, region.lower() if region else None)
    except (OSError, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if as_json:
        click.echo(json.dumps(sc_info_to_json(info), ensure_ascii=False, indent=2, sort_keys=True))
        return
    click.echo(render_text(info), nl=False)
