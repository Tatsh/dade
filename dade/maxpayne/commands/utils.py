"""Shared helpers for the Max Payne commands."""
from __future__ import annotations

import bascom

__all__ = ('debug_option',)

debug_option = bascom.debug_option({'dade.common': {}, 'dade.maxpayne': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""
