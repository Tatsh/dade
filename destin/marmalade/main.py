"""Root Click group + subcommand wiring for the ``marm`` CLI."""
from __future__ import annotations

import click

from .commands.extract_dz import extract_dz
from .commands.extract_group import extract_group

__all__ = ('main', 'marm')


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option()
def marm() -> None:
    """Unpack and decode Marmalade SDK game assets."""


marm.add_command(extract_dz)
marm.add_command(extract_group)


def main() -> None:
    """Entry point for the ``marm`` console script."""
    marm()
