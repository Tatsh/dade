"""File-backed :py:class:`~dade.common.io.Reader` implementations and source resolution."""
from __future__ import annotations

from dade.common.io import BytesReader, MmapReader, Reader, resolve_reader

__all__ = ('BytesReader', 'MmapReader', 'Reader', 'resolve_reader')
