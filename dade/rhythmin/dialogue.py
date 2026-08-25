"""
Extraction of the sugoroku board character-message dialogue pools from an app binary.

``getCharacterAssetName`` picks a board message from one of six pools, each a pointer array in the
binary's ``__const`` whose entries point at NUL-terminated UTF-8 strings in ``__cstring``. The
addresses in :data:`POOLS` are virtual addresses at an image base of ``0x4000``, so they are
resolved through the ``LC_SEGMENT`` load commands rather than assumed to be file offsets.

The dialogue is copyrighted game content and is not shipped with this package or with the
reconstruction it feeds; :func:`extract_pools` reads it out of a binary the caller already owns.
Two renderings are provided: :func:`render_c_header` writes the six ``static const char *const``
tables the reconstruction includes at build time, and :func:`render_binary` writes the runtime
asset, which is, for each pool in order, an ``int32`` entry count followed by that many records of
an ``int32`` byte length and that many UTF-8 bytes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('POOLS', 'DialoguePool', 'PoolSpec', 'empty_pools', 'extract_pools', 'render_binary',
           'render_c_header')


class PoolSpec(NamedTuple):
    """Where one dialogue pool lives in the binary."""

    name: str
    """Name of the C table the pool is rendered as."""
    address: int
    """Virtual address of the pointer array, at an image base of ``0x4000``."""
    entry_count: int
    """How many pointers the array holds."""


class DialoguePool(NamedTuple):
    """One extracted dialogue pool."""

    name: str
    """Name of the C table the pool is rendered as."""
    entry_count: int
    """How many entries the pool declares, which stands even when no strings were read."""
    strings: tuple[bytes, ...]
    """The pool's messages, as the UTF-8 bytes they are stored in."""


POOLS = (
    PoolSpec('kCharGroup6Slot0', 0x1335C8, 41),
    PoolSpec('kCharGroup6Slot1', 0x13366C, 35),
    PoolSpec('kCharGroup6Slot2', 0x1336F8, 47),
    PoolSpec('kCharGroup8Slot0', 0x1337B4, 64),
    PoolSpec('kCharGroup8Slot1', 0x1338B4, 72),
    PoolSpec('kCharGroup8Slot2', 0x1339D4, 71),
)
"""The six pools, in the order ``getCharacterAssetName`` expects them.

Slot 2 of group 6 is wac's and slot 1 of group 8 is TOMOSUKE's.

:meta hide-value:
"""

_CPU_TYPE_ARM = 12
_MH_MAGIC = 0xFEEDFACE
_MH_CIGAM = 0xCEFAEDFE
_FAT_MAGIC = 0xCAFEBABE
_FAT_CIGAM = 0xBEBAFECA
_LC_SEGMENT = 0x1
_FAT_ARCH_SIZE = 20
_LOAD_COMMANDS_OFFSET = 28
_NCMDS_OFFSET = 16
_SEGMENT_FIELDS_OFFSET = 24
_PRINTABLE = range(0x20, 0x7F)
_QUOTE = 0x22
_BACKSLASH = 0x5C
_QUESTION = 0x3F


class _Segment(NamedTuple):
    """One ``LC_SEGMENT`` mapping."""

    vm_address: int
    vm_size: int
    file_offset: int
    file_size: int


def _select_thin(data: bytes) -> bytes:
    """
    Unwrap a fat binary down to its 32-bit ARM slice.

    Parameters
    ----------
    data : bytes
        The file's contents, thin or fat.

    Returns
    -------
    bytes
        The thin image, which is the input unchanged when it was not fat.

    Raises
    ------
    ValueError
        If the file is fat but holds no 32-bit ARM slice.
    """
    if struct.unpack_from('>I', data, 0)[0] not in {_FAT_MAGIC, _FAT_CIGAM}:
        return data
    chosen: tuple[int, int] | None = None
    offset = 8
    for _ in range(struct.unpack_from('>I', data, 4)[0]):
        cpu_type, _, slice_offset, slice_size, _ = struct.unpack_from('>iIIII', data, offset)
        offset += _FAT_ARCH_SIZE
        if cpu_type == _CPU_TYPE_ARM:
            chosen = (slice_offset, slice_size)
    if chosen is None:
        msg = 'No 32-bit ARM slice in the fat binary.'
        raise ValueError(msg)
    return data[chosen[0]:chosen[0] + chosen[1]]


def _parse_segments(image: bytes) -> tuple[_Segment, ...]:
    """
    Read the ``LC_SEGMENT`` load commands of a 32-bit Mach-O image.

    Parameters
    ----------
    image : bytes
        The thin image.

    Returns
    -------
    tuple[_Segment, ...]
        Every segment mapping.

    Raises
    ------
    ValueError
        If the image is not a 32-bit Mach-O.
    """
    if struct.unpack_from('<I', image, 0)[0] not in {_MH_MAGIC, _MH_CIGAM}:
        magic = struct.unpack_from('<I', image, 0)[0]
        msg = f'Not a 32-bit Mach-O image: magic {magic:#010x}.'
        raise ValueError(msg)
    segments: list[_Segment] = []
    offset = _LOAD_COMMANDS_OFFSET
    for _ in range(struct.unpack_from('<I', image, _NCMDS_OFFSET)[0]):
        command, size = struct.unpack_from('<II', image, offset)
        if command == _LC_SEGMENT:
            segments.append(
                _Segment(*struct.unpack_from('<IIII', image, offset + _SEGMENT_FIELDS_OFFSET)))
        if size == 0:
            break
        offset += size
    return tuple(segments)


def _to_file_offset(segments: Sequence[_Segment], address: int) -> int | None:
    """
    Translate a virtual address to a file offset.

    Parameters
    ----------
    segments : Sequence[_Segment]
        The image's segment mappings.
    address : int
        The virtual address.

    Returns
    -------
    int | None
        The file offset, or ``None`` when the address is in no segment or lands in a segment's
        zero-filled tail, which has no bytes in the file.
    """
    for segment in segments:
        if segment.vm_address <= address < segment.vm_address + segment.vm_size:
            delta = address - segment.vm_address
            return segment.file_offset + delta if delta < segment.file_size else None
    return None


def extract_pools(data: bytes, pools: Sequence[PoolSpec] = POOLS) -> tuple[DialoguePool, ...]:
    """
    Read the dialogue pools out of an app binary.

    Parameters
    ----------
    data : bytes
        The binary's contents, thin or fat.
    pools : Sequence[PoolSpec]
        Which pools to read, defaulting to :data:`POOLS`.

    Returns
    -------
    tuple[DialoguePool, ...]
        One pool per specification, in the order given.

    Raises
    ------
    ValueError
        If the binary is not a 32-bit Mach-O, or a pool's pointer array or one of its strings falls
        outside the image, which means the addresses do not match this binary.
    """
    image = _select_thin(data)
    segments = _parse_segments(image)
    extracted: list[DialoguePool] = []
    for spec in pools:
        table = _to_file_offset(segments, spec.address)
        if table is None:
            msg = f'Pointer table for {spec.name} at {spec.address:#x} is in no segment.'
            raise ValueError(msg)
        strings: list[bytes] = []
        for index in range(spec.entry_count):
            pointer = struct.unpack_from('<I', image, table + index * 4)[0]
            offset = _to_file_offset(segments, pointer)
            if offset is None:
                msg = (f'Entry {index} of {spec.name} points at {pointer:#x}, which is not in the '
                       'file.')
                raise ValueError(msg)
            end = image.find(b'\0', offset)
            if end < 0:
                msg = f'Entry {index} of {spec.name} is not NUL-terminated.'
                raise ValueError(msg)
            strings.append(image[offset:end])
        extracted.append(DialoguePool(spec.name, spec.entry_count, tuple(strings)))
    return tuple(extracted)


def empty_pools(pools: Sequence[PoolSpec] = POOLS) -> tuple[DialoguePool, ...]:
    """
    Build pools that declare their sizes but hold no strings.

    This is the build fallback for when no app binary is available.

    Parameters
    ----------
    pools : Sequence[PoolSpec]
        Which pools to describe, defaulting to :data:`POOLS`.

    Returns
    -------
    tuple[DialoguePool, ...]
        One empty pool per specification.
    """
    return tuple(DialoguePool(spec.name, spec.entry_count, ()) for spec in pools)


def _c_literal(text: bytes) -> str:
    """
    Spell one string as a C literal, escaping anything that is not plainly printable.

    Parameters
    ----------
    text : bytes
        The string's bytes.

    Returns
    -------
    str
        The literal, quotes included. Non-printable and high bytes become three-digit octal, and
        ``?`` is escaped so that no trigraph can form.
    """
    parts = ['"']
    for byte in text:
        if byte == _QUOTE:
            parts.append('\\"')
        elif byte == _BACKSLASH:
            parts.append('\\\\')
        elif byte == _QUESTION:
            parts.append('\\?')
        elif byte in _PRINTABLE:
            parts.append(chr(byte))
        else:
            parts.append(f'\\{byte:03o}')
    parts.append('"')
    return ''.join(parts)


def render_c_header(pools: Sequence[DialoguePool]) -> str:
    """
    Render the pools as the C tables the reconstruction includes at build time.

    Parameters
    ----------
    pools : Sequence[DialoguePool]
        The pools to render.

    Returns
    -------
    str
        The header's text.
    """
    lines = [
        '// AUTO-GENERATED by `dade rhythmin extract-dialogue` -- do not edit or commit.',
        '// Sugoroku board character-message pools. Generated at CMake configure time from',
        '// an owned copy of the app binary; #included by TreasureMap.mm. If no binary was',
        '// supplied the tables are empty and getCharacterAssetName returns nullptr.',
        '',
    ]
    for pool in pools:
        if any(pool.strings):
            lines.append(f'static const char *const {pool.name}[{pool.entry_count}] = {{')
            lines += [f'    {_c_literal(text)},' for text in pool.strings]
            lines.append('};')
        else:
            lines.append(f'static const char *const {pool.name}[{pool.entry_count}] = {{0}};')
        lines.append('')
    return '\n'.join(lines)


def render_binary(pools: Sequence[DialoguePool]) -> bytes:
    """
    Render the pools as the runtime asset.

    Parameters
    ----------
    pools : Sequence[DialoguePool]
        The pools to render.

    Returns
    -------
    bytes
        For each pool in order, an ``int32`` entry count then that many length-prefixed strings.
    """
    out = bytearray()
    for pool in pools:
        out += struct.pack('<i', pool.entry_count)
        for text in pool.strings:
            out += struct.pack('<i', len(text)) + text
    return bytes(out)
