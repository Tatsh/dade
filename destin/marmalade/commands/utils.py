"""Shared helpers for the ``marm`` command-line tool."""
from __future__ import annotations

from rich.console import Console
import bascom

__all__ = ('console', 'debug_option')

console = Console()
"""
Shared Rich :py:class:`~rich.console.Console` used by command-side output.

:meta hide-value:
"""

debug_option = bascom.debug_option({'destin.common': {}, 'destin.marmalade': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

When set, every ``marmalade`` logger is switched to ``DEBUG`` for the duration of the command.

:meta hide-value:
"""
