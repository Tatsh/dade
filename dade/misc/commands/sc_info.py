"""``dade misc sc-info`` - describe the FairPlay bookkeeping in a purchased ``.app`` bundle."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import logging

import click

from dade.misc.sc_info import read_bundles, render_text, sc_info_to_json

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
              help='Read only the application, skipping its extensions and watch app.')
@click.option('--region',
              metavar='CC',
              help='Country code to build the App Store link with, such as jp, when the bundle '
              'has no iTunesMetadata.plist beside it to read the storefront from.')
@debug_option
def dump(path: Path, bundle: str | None, region: str | None, *, as_json: bool,
         main_bundle: bool) -> None:
    """
    Describe the SC_Info content at PATH.

    PATH may be an ``.ipa``, read without being unpacked, or the SC_Info directory itself, the
    ``.app`` bundle around it, the ``Payload`` directory above the bundle, or a directory with
    ``Payload`` inside.

    A download includes more than the application. An app extension under PlugIns and a watch app
    under Watch each have an SC_Info, and every one is read. Narrow the selection with
    --main-bundle or --bundle. Specifying the SC_Info directory or one bundle directly reads only
    that bundle.

    Nothing here is decrypted and none of it is a key: the report covers the purchase record, the
    embedded Apple FairPlay certificates, and the length and digest of the key material.

    The App Store link is regional where a storefront can be read from an iTunesMetadata.plist
    beside the bundle, and falls back to the region-less form otherwise. Pass --region to give one.
    """  # ruff: ignore[docstring-missing-exception]
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
