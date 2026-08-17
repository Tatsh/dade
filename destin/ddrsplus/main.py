"""Root Click group + subcommand wiring for the ``destin ddrsplus`` group."""
from __future__ import annotations

import click

from .commands.extract_gen import extract_gen

__all__ = ('ddrsplus', 'main')


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option()
def ddrsplus() -> None:
    """Decrypt and decode data files from the Konami game Dance Dance Revolution S+."""


ddrsplus.add_command(extract_gen)


def main() -> None:
    """Entry point for the ``ddrsplus`` group when it is run on its own."""
    ddrsplus()
