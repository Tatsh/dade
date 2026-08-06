"""Shared helpers for the Interstate '76 commands."""
from __future__ import annotations

from destin.common.cli import make_debug_option

__all__ = ('debug_option',)

debug_option = make_debug_option(('destin.common', 'destin.i76'))
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""
