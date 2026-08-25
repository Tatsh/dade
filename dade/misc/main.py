"""Root Click group + subcommand wiring for the ``dade misc`` group."""
from __future__ import annotations

import click

from .commands.coredata import coredata
from .commands.macho import macho
from .commands.sc_info import sc_info
from .commands.strings import strings

__all__ = ('main', 'misc')


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option()
def misc() -> None:
    """Convert platform-level artefacts that are not tied to any one game."""


misc.add_command(coredata)
misc.add_command(macho)
misc.add_command(sc_info)
misc.add_command(strings)


def main() -> None:
    """Entry point for the ``misc`` group when it is run on its own."""
    misc()
