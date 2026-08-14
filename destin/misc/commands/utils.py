"""Shared helpers for the ``destin misc`` commands."""
from __future__ import annotations

from pathlib import Path

import bascom
import click

__all__ = ('READABLE_DIR', 'READABLE_FILE', 'debug_option')

debug_option = bascom.debug_option({'destin.misc': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""
READABLE_FILE = click.Path(dir_okay=False, exists=True, path_type=Path)
"""Click type for an argument naming a file that must already exist.

:meta hide-value:
"""
READABLE_DIR = click.Path(exists=True, file_okay=False, path_type=Path)
"""Click type for an argument naming a directory that must already exist.

:meta hide-value:
"""
