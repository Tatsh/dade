"""Shared typing helpers for :py:mod:`destin.monopoly08`."""
from __future__ import annotations

from typing import Literal, TypeAlias

__all__ = ('Endian', 'Platform')

Endian: TypeAlias = Literal['<', '>']
""":py:mod:`struct` byte-order character: little-endian or big-endian.

:meta hide-value:
"""

Platform: TypeAlias = Literal['xbox360', 'ps3', 'ps2', 'wii']
"""A detected disc platform.

:meta hide-value:
"""
