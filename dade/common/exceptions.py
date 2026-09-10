"""Exceptions shared by more than one game submodule."""
from __future__ import annotations

__all__ = ('InvalidFormatError', 'SelfCheckFailed', 'UnreachableState')


class InvalidFormatError(ValueError):
    """Raised when a parser is given data that does not match its expected format."""


class SelfCheckFailed(RuntimeError):
    """Raised when a module's ``demo`` finds one of that module's own invariants broken."""


class UnreachableState(RuntimeError):
    """Raised when execution arrives at a state an earlier check in the same function ruled out."""
