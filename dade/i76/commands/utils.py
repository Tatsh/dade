"""Shared helpers for the Interstate '76 commands."""
from __future__ import annotations

import bascom

__all__ = ('debug_option',)

debug_option = bascom.debug_option({'dade.common': {}, 'dade.i76': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""
