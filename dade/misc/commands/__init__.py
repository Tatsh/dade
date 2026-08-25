"""Click commands for the ``dade misc`` group."""
from __future__ import annotations

from .coredata import coredata
from .macho import macho
from .sc_info import sc_info
from .strings import strings

__all__ = ('coredata', 'macho', 'sc_info', 'strings')
