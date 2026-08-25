"""Root Click group + subcommand wiring for the ``tonesphere`` CLI."""
from __future__ import annotations

import click

from .commands.decrypt_cz import decrypt_cz
from .commands.extract import extract
from .commands.save import save

__all__ = ('main', 'tonesphere')


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option()
def tonesphere() -> None:
    """Tools for the bit192labs game Tone Sphere."""


tonesphere.add_command(decrypt_cz)
tonesphere.add_command(extract)
tonesphere.add_command(save)


def main() -> None:
    """Entry point for the ``tonesphere`` console script."""
    tonesphere()
