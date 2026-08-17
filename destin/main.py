"""
Unified command-line interface for the ``destin`` game asset extractors.

Every supported game is mounted as a sub-group of the top-level ``destin`` command, so each tool is
invoked as ``destin <game> <subcommand>`` (for example ``destin incoming extract`` or
``destin bitrock crack``). Converters for formats that belong to no single game are grouped under
``destin misc``.
"""
from __future__ import annotations

import click

from . import __version__
from .amplitude.main import main as amplitude_unpack
from .bit192.main import tonesphere as bit192_group
from .bitrock.commands.crack import crack_main as bitrock_crack
from .bitrock.commands.extract import extract_main as bitrock_extract
from .ddrsplus.main import ddrsplus as ddrsplus_group
from .frequency.main import main as frequency_unpack
from .i76.main import cli as i76_group
from .incoming.commands.extract_pvr_pack import extract_pvr_pack as incoming_pvr_pack
from .incoming.commands.ian2obj import ian2obj as incoming_ian2obj
from .incoming.main import main as incoming_extract
from .jubeatplus.main import jubeatplus as jubeatplus_group
from .marmalade.main import marm as marmalade_group
from .misc.main import misc as misc_group
from .monopoly08.main import main as monopoly_extract
from .rhythmin.main import rhythmin as rhythmin_group
from .thps2pc.main import cli as thps2pc_group
from .xg2.main import cli as xg2_group

__all__ = ('main',)

_CONTEXT_SETTINGS = {'help_option_names': ('-h', '--help')}


def _amplitude() -> click.Group:
    group = click.Group(name='amplitude',
                        help='PS2 Amplitude (Harmonix) asset unpacker.',
                        context_settings=_CONTEXT_SETTINGS)
    group.add_command(amplitude_unpack, name='unpack')
    return group


def _bitrock() -> click.Group:
    group = click.Group(name='bitrock',
                        help='BitRock/InstallBuilder installer extractor and password cracker.',
                        context_settings=_CONTEXT_SETTINGS)
    group.add_command(bitrock_crack, name='crack')
    group.add_command(bitrock_extract, name='extract')
    return group


def _frequency() -> click.Group:
    group = click.Group(name='frequency',
                        help='PS2 FreQuency (Harmonix) asset unpacker.',
                        context_settings=_CONTEXT_SETTINGS)
    group.add_command(frequency_unpack, name='unpack')
    return group


def _incoming() -> click.Group:
    group = click.Group(name='incoming',
                        help='Incoming (Rage Software / Interplay) PC and Dreamcast assets.',
                        context_settings=_CONTEXT_SETTINGS)
    group.add_command(incoming_extract, name='extract')
    group.add_command(incoming_pvr_pack, name='extract-pvr-pack')
    group.add_command(incoming_ian2obj, name='ian2obj')
    return group


def _monopoly08() -> click.Group:
    group = click.Group(name='monopoly08',
                        help='Monopoly 2008 (EA) multi-platform asset unpacker.',
                        context_settings=_CONTEXT_SETTINGS)
    group.add_command(monopoly_extract, name='extract')
    return group


@click.group(name='destin', context_settings=_CONTEXT_SETTINGS)
@click.version_option(__version__)
def main() -> None:
    """Extract and convert assets from a collection of PC and console video games."""


main.add_command(_amplitude())
main.add_command(bit192_group, name='bit192')
main.add_command(_bitrock())
main.add_command(ddrsplus_group, name='ddrsplus')
main.add_command(_frequency())
main.add_command(i76_group, name='i76')
main.add_command(_incoming())
main.add_command(jubeatplus_group, name='jubeatplus')
main.add_command(marmalade_group, name='marmalade')
main.add_command(misc_group, name='misc')
main.add_command(_monopoly08())
main.add_command(rhythmin_group, name='rhythmin')
main.add_command(thps2pc_group, name='thps2pc')
main.add_command(xg2_group, name='xg2')
