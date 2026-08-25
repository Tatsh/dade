"""Root Click group + subcommand wiring for the ``dade rhythmin`` group."""
from __future__ import annotations

import click

from .commands.dump_chara import dump_chara
from .commands.dump_idx import dump_idx
from .commands.dump_map import dump_map
from .commands.dump_sheet import dump_sheet
from .commands.extract_dialogue import extract_dialogue

__all__ = ('main', 'rhythmin')


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option()
def rhythmin() -> None:
    """Decrypt and decode data files from the Konami game pop'n rhythmin."""


rhythmin.add_command(dump_chara)
rhythmin.add_command(dump_idx)
rhythmin.add_command(dump_map)
rhythmin.add_command(dump_sheet)
rhythmin.add_command(extract_dialogue)


def main() -> None:
    """Entry point for the ``rhythmin`` group when it is run on its own."""
    rhythmin()
