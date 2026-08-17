"""Shared helpers for the ``destin ddrsplus`` commands."""
from __future__ import annotations

from pathlib import Path

import bascom
import click

__all__ = ('READABLE_FILE', 'WRITABLE_DIR', 'debug_option')

debug_option = bascom.debug_option({'destin.ddrsplus': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""
READABLE_FILE = click.Path(dir_okay=False, exists=True, path_type=Path)
"""Click type for an argument naming a file that must already exist.

:meta hide-value:
"""
WRITABLE_DIR = click.Path(file_okay=False, path_type=Path)
"""Click type for an option naming a directory to be written into.

:meta hide-value:
"""
