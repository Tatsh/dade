"""Root Click group and subcommand wiring for the ``dade thps2pc`` commands."""
from __future__ import annotations

import click

from .commands.convert_scene import convert_scene
from .commands.decode_textures import decode_textures
from .commands.dump_descriptors import dump_descriptors
from .commands.psx_info import psx_info
from .commands.render import (
    render_authoritative_command,
    render_layers_command,
    render_node_map_command,
    render_object_models_command,
    render_objects_command,
)
from .commands.unpack_pkr import unpack_pkr

__all__ = ('cli',)


@click.group(context_settings={'help_option_names': ('-h', '--help')})
def cli() -> None:
    """Tony Hawk's Pro Skater 2 (Neversoft/Activision) PC asset tools."""


cli.add_command(convert_scene)
cli.add_command(decode_textures)
cli.add_command(dump_descriptors)
cli.add_command(psx_info)
cli.add_command(render_authoritative_command)
cli.add_command(render_layers_command)
cli.add_command(render_node_map_command)
cli.add_command(render_object_models_command)
cli.add_command(render_objects_command)
cli.add_command(unpack_pkr)
