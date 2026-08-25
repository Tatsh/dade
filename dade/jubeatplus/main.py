"""Root Click group + subcommand wiring for the ``dade jubeatplus`` group."""
from __future__ import annotations

import click

from .commands.unpack import unpack

__all__ = ('jubeatplus', 'main')


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option()
def jubeatplus() -> None:
    """Tools for the Konami iOS rhythm game jubeat plus."""


jubeatplus.add_command(unpack)


def main() -> None:
    """Entry point for the ``jubeatplus`` group when it is run on its own."""
    jubeatplus()
