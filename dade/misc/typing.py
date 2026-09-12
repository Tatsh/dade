"""Typing helpers for the platform-level readers."""
from __future__ import annotations

from typing import Any, TypedDict

__all__ = ('DSStoreBlockDict', 'DSStoreDict', 'DSStoreHeaderDict', 'DSStoreStructureDict',
           'DSStoreTreeDict', 'MachOArchDict', 'MachODict', 'MachOSegmentDict')


class DSStoreBlockDict(TypedDict):
    """One block of a ``.DS_Store`` file, addressed by its position in the allocator's table."""

    offset: int
    """The block's offset, relative to the four-byte alignment word at the file's start."""
    size: int
    """The block's size, always a power of two."""


class DSStoreHeaderDict(TypedDict):
    """The header of a ``.DS_Store`` file."""

    alignment: int
    """The alignment word, always one."""
    allocator_offset: int
    """The allocator's offset, stored twice and reported once."""
    allocator_size: int
    """The allocator's size."""
    magic: str
    """The magic, always ``Bud1``."""


class DSStoreTreeDict(TypedDict):
    """The master block of one directory inside a ``.DS_Store`` file."""

    levels: int
    """The tree's depth."""
    nodes: int
    """The number of nodes the tree occupies."""
    page_size: int
    """The size of a node, always 4096."""
    records: int
    """The number of records the tree stores."""
    root_node: int
    """The block number of the tree's root node."""


class DSStoreStructureDict(TypedDict):
    """The bookkeeping a ``.DS_Store`` file wraps its records in."""

    blocks: list[DSStoreBlockDict]
    """Every block the allocator addresses, in table order."""
    directories: dict[str, DSStoreTreeDict]
    """Every named directory and the tree it points at. Finder writes one, ``DSDB``."""
    free_list: list[list[int]]
    """The 32 free lists, one per block size exponent, each of the offsets it stores."""
    header: DSStoreHeaderDict
    """The file header."""


class DSStoreDict(TypedDict):
    """A whole ``.DS_Store`` file."""

    entries: dict[str, dict[str, Any]]
    """Every record, grouped by file name and then by structure identifier."""
    structure: DSStoreStructureDict
    """The allocator's own bookkeeping."""


class MachOSegmentDict(TypedDict):
    """One ``LC_SEGMENT`` or ``LC_SEGMENT_64`` load command."""

    file_offset: int
    """The segment's offset within the image."""
    file_size: int
    """The number of bytes the segment occupies in the image."""
    name: str
    """The segment name, such as ``__TEXT``."""
    sections: list[str]
    """The segment's section names, each as ``segment,section``."""
    vm_address: int
    """The segment's virtual address."""
    vm_size: int
    """The segment's size in memory."""


class MachOArchDict(TypedDict):
    """One architecture slice of a Mach-O image."""

    architecture: str
    """A readable name for the CPU type and subtype, such as ``arm64``."""
    cpu_subtype: int
    """The CPU subtype, as stored."""
    cpu_type: int
    """The CPU type, as stored."""
    dylibs: list[str]
    """Every linked library's install name, in load order."""
    encryption: dict[str, Any] | None
    """The ``LC_ENCRYPTION_INFO`` command, when the slice includes one."""
    entitlements: dict[str, Any] | None
    """The entitlements embedded in the code signature, when they can be read."""
    file_type: str
    """A readable name for the Mach-O file type, such as ``execute``."""
    flags: list[str]
    """The header flag names that are set."""
    load_command_count: int
    """The number of load commands."""
    minimum_os: dict[str, str] | None
    """The platform and version floor, from ``LC_VERSION_MIN_*`` or ``LC_BUILD_VERSION``."""
    rpaths: list[str]
    """Every ``LC_RPATH`` search path."""
    segments: list[MachOSegmentDict]
    """Every segment."""
    source_version: str | None
    """The ``LC_SOURCE_VERSION`` string, when present."""
    uuid: str | None
    """The image's ``LC_UUID``, when present."""
    weak_dylibs: list[str]
    """The install names of the libraries linked weakly."""


class MachODict(TypedDict):
    """A whole Mach-O image, possibly with more than one architecture."""

    architectures: list[MachOArchDict]
    """One entry per slice; a thin image has exactly one."""
    is_universal: bool
    """Whether the image is a universal (``fat``) binary."""
    name: str
    """The image file's name."""
    sha256: str
    """The whole file's SHA-256 digest."""
    size: int
    """The image's size in bytes."""
