"""Shared helpers for the command-line utilities."""
from __future__ import annotations

import bascom

__all__ = ('debug_option',)

debug_option = bascom.debug_option({'dade.common': {}, 'dade.incoming': {}})
"""Attach ``-d/--debug`` to a leaf command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""
