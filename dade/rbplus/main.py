"""Root Click group + subcommand wiring for the ``dade rbplus`` group."""
from __future__ import annotations

import click

from .commands.dump_chart import dump_chart
from .commands.extract_assets import extract_assets
from .commands.unpack import unpack

__all__ = ('main', 'rbplus')


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option()
def rbplus() -> None:
    """Tools for the Konami iOS rhythm game REFLEC BEAT plus."""


rbplus.add_command(dump_chart)
rbplus.add_command(extract_assets)
rbplus.add_command(unpack)


def main() -> None:
    """Entry point for the ``rbplus`` group when it is run on its own."""
    rbplus()
