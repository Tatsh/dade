"""Root Click group and subcommand wiring for the Interstate '76 and '82 tools."""
from __future__ import annotations

import click

from .commands.build_horizon import build_horizon
from .commands.decode_texture import decode_texture
from .commands.inspect_chunks import inspect_chunks
from .commands.pak_extract import pak_extract
from .commands.sdf2obj import sdf2obj
from .commands.stage_i82 import stage_i82
from .commands.stage_i82_objects import stage_i82_objects
from .commands.unpack_i82sim import unpack_i82sim
from .commands.zfs_extract import zfs_extract
from .commands.zfs_list import zfs_list

__all__ = ('cli',)


@click.group(name='i76', context_settings={'help_option_names': ('-h', '--help')})
def cli() -> None:
    """Extract and decode Interstate '76 and Interstate '82 (Activision) assets."""


cli.add_command(build_horizon)
cli.add_command(decode_texture)
cli.add_command(inspect_chunks)
cli.add_command(pak_extract)
cli.add_command(sdf2obj)
cli.add_command(stage_i82)
cli.add_command(stage_i82_objects)
cli.add_command(unpack_i82sim)
cli.add_command(zfs_extract)
cli.add_command(zfs_list)
