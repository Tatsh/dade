"""``destin misc sc-info`` - describe the FairPlay bookkeeping in a purchased ``.app`` bundle."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

from destin.misc.sc_info import read_bundles, render_text, sc_info_to_json
import click

from .utils import READABLE_PATH, debug_option

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('dump', 'sc_info')

log = logging.getLogger(__name__)


@click.group(name='sc-info', context_settings={'help_option_names': ('-h', '--help')})
def sc_info() -> None:
    """Read the SC_Info directory of a purchased application bundle."""


@sc_info.command()
@click.argument('path', metavar='PATH', type=READABLE_PATH)
@click.option('--bundle',
              metavar='NAME',
              help='Read only this bundle, named in full or by its last component, such as '
              'NotificationService.appex.')
@click.option('--json', 'as_json', is_flag=True, help='Print JSON instead of a readable report.')
@click.option('--main-bundle',
              is_flag=True,
              help='Read only the application, leaving its extensions and watch app alone.')
@click.option('--region',
              metavar='CC',
              help='Country code to build the App Store link with, such as jp, when the bundle '
              'has no iTunesMetadata.plist beside it to read the storefront from.')
@debug_option
def dump(path: Path, bundle: str | None, region: str | None, *, as_json: bool,
         main_bundle: bool) -> None:
    """
    Describe the SC_Info content at PATH.

    PATH may be an ``.ipa``, which is read without being unpacked, or the SC_Info directory
    itself, the ``.app`` bundle holding it, the ``Payload`` directory holding that, or a directory
    holding ``Payload``.

    A download holds more than the application: an app extension under PlugIns and a watch app
    under Watch each carry an SC_Info of their own, and every one of them is read. Narrow that with
    --main-bundle or --bundle. Naming the SC_Info directory or one bundle directly reads that one.

    Nothing here is decrypted and none of it is a key: the report covers the purchase record, the
    embedded Apple FairPlay certificates, and the length and digest of the key material.

    The App Store link is regional where a storefront can be read from an iTunesMetadata.plist
    beside the bundle, and falls back to the region-less form otherwise. Pass --region to give one.

    Raises
    ------
    click.Abort
        If there is no SC_Info directory at or below PATH, or nothing matches --bundle.
    """
    log.debug('Reading `%s`.', path)
    try:
        infos = read_bundles(path,
                             region.lower() if region else None,
                             bundle,
                             main_only=main_bundle)
    except (OSError, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if as_json:
        click.echo(
            json.dumps([sc_info_to_json(info) for info in infos],
                       ensure_ascii=False,
                       indent=2,
                       sort_keys=True))
        return
    for index, info in enumerate(infos):
        if index:
            click.echo()
        click.echo(render_text(info), nl=False)
