"""Exceptions shared by more than one game submodule."""
from __future__ import annotations

__all__ = ('InvalidFormatError',)


class InvalidFormatError(ValueError):
    """Raised when a parser is given data that does not match its expected format."""
