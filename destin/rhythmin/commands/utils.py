"""Shared helpers for the ``destin rhythmin`` commands."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import bascom
import click

__all__ = ('READABLE_DIR', 'READABLE_FILE', 'WRITABLE_FILE', 'debug_option', 'echo_json')

debug_option = bascom.debug_option({'destin.rhythmin': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""
READABLE_FILE = click.Path(dir_okay=False, exists=True, path_type=Path)
"""Click type for an argument naming a file that must already exist.

:meta hide-value:
"""
WRITABLE_FILE = click.Path(dir_okay=False, path_type=Path)
"""Click type for an argument naming a file to be written.

:meta hide-value:
"""
READABLE_DIR = click.Path(exists=True, file_okay=False, path_type=Path)
"""Click type for an argument naming a directory that must already exist.

:meta hide-value:
"""


def echo_json(obj: Any) -> None:
    """
    Write an object to standard output as indented, key-sorted JSON.

    Parameters
    ----------
    obj : Any
        A JSON-serialisable object.
    """
    click.echo(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
