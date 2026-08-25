"""Typing helpers for :py:mod:`dade.bitrock.password_cracker`."""
from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ('ProgressCallback',)

ProgressCallback: TypeAlias = 'Callable[[int, bytes], None]'
"""Called periodically with the running candidate count and the latest candidate tried."""
