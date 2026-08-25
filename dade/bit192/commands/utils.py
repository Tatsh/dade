"""Shared helpers for the ``tonesphere`` command-line tool."""
from __future__ import annotations

from rich.console import Console
import bascom

__all__ = ('console', 'debug_option')

console = Console()
"""
Shared Rich :py:class:`~rich.console.Console` used by command-side output.

:meta hide-value:
"""

debug_option = bascom.debug_option({'dade.bit192': {}, 'dade.common': {}, 'dade.marmalade': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

When set, both the ``bit192`` and ``marmalade`` loggers switch to ``DEBUG`` for the command.

:meta hide-value:
"""
