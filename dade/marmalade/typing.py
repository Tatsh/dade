"""Typed data structures shared across :mod:`marmalade`."""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ('DerbhEntry', 'ResGroup', 'Resource')


class DerbhEntry(NamedTuple):
    """One file unpacked from a Derbh (DTRZ) archive."""

    path: str
    """POSIX-style relative path (folder + file name), ``/`` separated."""
    data: bytes
    """Decompressed file contents."""
    method: int
    """Raw Derbh compression-method tag (``0x100`` stored, ``0x200`` LZMA-alone, ``0x8`` gzip)."""


class Resource(NamedTuple):
    """One serialised resource inside an :class:`ResGroup`."""

    name_hash: int
    """:func:`dade.marmalade.hashstring.iw_hash_string` of the resource's name (the original
    string is not stored in the group), or its in-group hash when the name is omitted."""
    body: bytes
    """Raw serialised body of the resource (decode with the per-class decoder)."""


class ResGroup(NamedTuple):
    """A parsed ``.group.bin`` (CIwResGroup)."""

    name: str | None
    """Group name from the ``ResGroupMembers`` section, if present."""
    resources: Mapping[str, Sequence[Resource]]
    """Map of class name (e.g. ``'CIwModel'``) to its resources, in file order."""
