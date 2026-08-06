"""Shared helpers for the ``tonesphere`` command-line tool."""
from __future__ import annotations

from destin.common.cli import make_debug_option
from rich.console import Console

__all__ = ('console', 'debug_option')

console = Console()
"""
Shared Rich :py:class:`~rich.console.Console` used by command-side output.

:meta hide-value:
"""

debug_option = make_debug_option(('destin.bit192', 'destin.common', 'destin.marmalade'))
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

When set, both the ``bit192`` and ``marmalade`` loggers switch to ``DEBUG`` for the command.

:meta hide-value:
"""
