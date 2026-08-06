"""Shared types and helpers for converters."""
from __future__ import annotations

from destin.common.registry import Rule, name_match, suffix_match

__all__ = ('ConversionError', 'Rule', 'UnsupportedFormatError', 'name_match', 'suffix_match')


class UnsupportedFormatError(Exception):
    """
    Raised by a converter that matches a file whose format is not yet decoded.

    The dispatcher treats this as a skip with a warning rather than a failure.
    """


class ConversionError(Exception):
    """Raised when a converter matches a file but fails to convert it."""
