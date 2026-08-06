"""Command line entry points for :py:mod:`bitrock`."""
from __future__ import annotations

from .crack import crack_main
from .extract import extract_main

__all__ = ('crack_main', 'extract_main')
