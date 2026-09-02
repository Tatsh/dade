"""Root Click group and subcommand wiring for the Max Payne tools."""
from __future__ import annotations

import click

from .commands.inspect_tags import inspect_tags
from .commands.ldb2glb import ldb2glb
from .commands.ldb_textures import ldb_textures
from .commands.ras_extract import ras_extract
from .commands.ras_list import ras_list

__all__ = ('cli',)


@click.group(name='maxpayne', context_settings={'help_option_names': ('-h', '--help')})
def cli() -> None:
    """Extract and decode Max Payne (Remedy Entertainment) assets."""


cli.add_command(inspect_tags)
cli.add_command(ldb2glb)
cli.add_command(ldb_textures)
cli.add_command(ras_extract)
cli.add_command(ras_list)
