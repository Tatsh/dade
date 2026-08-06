"""Universal asset unpacker for Monopoly 2008 (Xbox 360 / PS3 / PS2 / Wii)."""
from __future__ import annotations

from .detect import DiscInfo, detect
from .pipeline import StepStats, run

__all__ = ('DiscInfo', 'StepStats', 'detect', 'run')
