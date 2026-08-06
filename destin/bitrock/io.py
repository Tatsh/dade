"""File-backed :py:class:`~destin.common.io.Reader` implementations and source resolution."""
from __future__ import annotations

from destin.common.io import BytesReader, MmapReader, Reader, resolve_reader

__all__ = ('BytesReader', 'MmapReader', 'Reader', 'resolve_reader')
