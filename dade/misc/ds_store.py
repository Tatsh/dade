"""
Reading of the Finder ``.DS_Store`` desktop database.

A ``.DS_Store`` is a Buddy allocator file, identified by its ``Bud1`` magic, storing one B-tree.
Every record pairs a file name with a four-character structure identifier and a typed value, and
the tree is keyed on both. The tree is flattened into one entry per file name, and the allocator's
own bookkeeping is reported beside it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, NamedTuple
import io
import plistlib
import struct

from dade.common.exceptions import InvalidFormatError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .typing import DSStoreBlockDict, DSStoreDict, DSStoreStructureDict, DSStoreTreeDict

__all__ = ('read_ds_store',)

_MAGIC = b'Bud1'
# Every offset the allocator stores is relative to the four-byte alignment word at the file's start.
_BLOCK_BASE = 4
# A block address packs the size exponent into the five bits the 32-byte alignment frees up.
_SIZE_MASK = 0x1F
# The block address table is padded out to a whole multiple of this many entries.
_ADDRESS_PAGE = 256
_FREE_LISTS = 32
_PLIST_MAGIC = b'bplist00'
_FIRST_PRINTABLE = 0x20
_LAST_PRINTABLE = 0x7E
_MAC_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
# A ``dutc`` value counts 1/65536 of a second.
_MAC_TICKS = 65536
_CF_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
# Finder writes a modification date either as a ``dutc`` or as a blob of these two codes.
_DATE_BLOBS = ('moDD', 'modD')
_CF_DATE = struct.Struct('<d')
_U8 = struct.Struct('>B')
_U32 = struct.Struct('>I')
_I32 = struct.Struct('>i')
_I64 = struct.Struct('>q')
_HEADER = struct.Struct('>I4sIII')
_MASTER = struct.Struct('>IIIII')
_ILOC = struct.Struct('>II8s')
_FWI0 = struct.Struct('>4h4s4s')


class _Allocator(NamedTuple):
    """The allocator's bookkeeping, as stored."""

    blocks: tuple[tuple[int, int], ...]
    """Every block as an offset and a size, addressed by its position in the table."""
    directories: tuple[tuple[str, int], ...]
    """Every named directory and the master block it points at."""
    free_list: tuple[tuple[int, ...], ...]
    """The 32 free lists, one per block size exponent, each of the offsets it stores."""


def _take(stream: io.BytesIO, count: int) -> bytes:
    """
    Read exactly ``count`` bytes.

    Parameters
    ----------
    stream : io.BytesIO
        The file, positioned where the bytes begin.
    count : int
        The number of bytes to read.

    Returns
    -------
    bytes
        The bytes read.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        When the file ends first.
    """
    offset = stream.tell()
    data = stream.read(count)
    if len(data) != count:
        msg = f'Truncated at offset {offset}, where {count} bytes were expected.'
        raise InvalidFormatError(msg)
    return data


def _unpack(layout: struct.Struct, stream: io.BytesIO) -> tuple[Any, ...]:
    """
    Read one structure.

    Parameters
    ----------
    layout : struct.Struct
        The structure to read.
    stream : io.BytesIO
        The file, positioned where the structure begins.

    Returns
    -------
    tuple[Any, ...]
        Every field of the structure.
    """
    return layout.unpack(_take(stream, layout.size))


def _u8(stream: io.BytesIO) -> int:
    """
    Read one unsigned byte.

    Parameters
    ----------
    stream : io.BytesIO
        The file, positioned at the byte.

    Returns
    -------
    int
        The value read.
    """
    return int(_unpack(_U8, stream)[0])


def _u32(stream: io.BytesIO) -> int:
    """
    Read one big-endian unsigned 32-bit integer.

    Parameters
    ----------
    stream : io.BytesIO
        The file, positioned at the integer.

    Returns
    -------
    int
        The value read.
    """
    return int(_unpack(_U32, stream)[0])


def _fourcc(raw: bytes) -> str:
    """
    Render a four-character code, substituting a full stop for every unprintable byte.

    Parameters
    ----------
    raw : bytes
        The four bytes as stored.

    Returns
    -------
    str
        The code as text.
    """
    return ''.join(
        chr(byte) if _FIRST_PRINTABLE <= byte <= _LAST_PRINTABLE else '.' for byte in raw)


def _utf16(stream: io.BytesIO) -> str:
    """
    Read a string stored as a big-endian UTF-16 length and body.

    Parameters
    ----------
    stream : io.BytesIO
        The file, positioned at the length.

    Returns
    -------
    str
        The string read. The stored length counts UTF-16 code units rather than bytes.
    """
    return _take(stream, _u32(stream) * 2).decode('utf-16-be')


def _mac_date(value: int) -> str | int:
    """
    Render a ``dutc`` timestamp.

    Parameters
    ----------
    value : int
        The stored count of 1/65536 of a second since 1904.

    Returns
    -------
    str | int
        The moment as an ISO 8601 string, or the stored count when it falls outside the range a
        :py:class:`datetime.datetime` covers.
    """
    try:
        return (_MAC_EPOCH + timedelta(seconds=value / _MAC_TICKS)).isoformat()
    except (OverflowError, ValueError):
        return value


def _cf_date(value: float) -> str | float:
    """
    Render a Core Foundation absolute time.

    Parameters
    ----------
    value : float
        The stored count of seconds since 2001.

    Returns
    -------
    str | float
        The moment as an ISO 8601 string, or the stored count when it falls outside the range a
        :py:class:`datetime.datetime` covers.
    """
    try:
        return (_CF_EPOCH + timedelta(seconds=value)).isoformat()
    except (OverflowError, ValueError):
        return value


def _json_safe(value: Any) -> Any:
    """
    Convert a decoded property-list value to a form JSON can store.

    Parameters
    ----------
    value : Any
        A value from :py:func:`plistlib.loads`, of any type and nesting.

    Returns
    -------
    Any
        The same value with data, dates, and UIDs replaced by JSON-storable equivalents.
    """
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, plistlib.UID):
        return value.data
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return {'hex': bytes(value).hex(), 'length': len(value)}
    return value


def _decode_blob(code: str, data: bytes) -> Any:
    """
    Decode one ``blob`` value as far as its structure identifier allows.

    Parameters
    ----------
    code : str
        The record's four-character structure identifier, such as ``Iloc``.
    data : bytes
        The stored bytes.

    Returns
    -------
    Any
        The decoded property list for a blob that is one, the icon position for ``Iloc``, the window
        frame for ``fwi0``, the moment for ``modD`` and ``moDD``, and the bytes as hex for
        everything else.
    """
    if code in _DATE_BLOBS and len(data) == _CF_DATE.size:
        return _cf_date(float(_CF_DATE.unpack(data)[0]))
    if data[:len(_PLIST_MAGIC)] == _PLIST_MAGIC:
        try:
            return _json_safe(plistlib.loads(data))
        except (ValueError, plistlib.InvalidFileException):
            return {'hex': data.hex(), 'length': len(data)}
    if code == 'Iloc' and len(data) == _ILOC.size:
        x, y, trailer = _ILOC.unpack(data)
        return {'trailer': trailer.hex(), 'x': x, 'y': y}
    if code == 'fwi0' and len(data) == _FWI0.size:
        top, left, bottom, right, view, trailer = _FWI0.unpack(data)
        return {
            'bottom': bottom,
            'left': left,
            'right': right,
            'top': top,
            'trailer': trailer.hex(),
            'view': _fourcc(view)
        }
    return {'hex': data.hex(), 'length': len(data)}


def _read_value(stream: io.BytesIO, code: str, kind: str) -> Any:
    """
    Read one record's value.

    Parameters
    ----------
    stream : io.BytesIO
        The file, positioned where the value begins.
    code : str
        The record's four-character structure identifier.
    kind : str
        The record's four-character data type, such as ``long``.

    Returns
    -------
    Any
        The value, decoded according to its data type.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        When the data type is not one of the eight the format defines.
    """
    match kind:
        case 'bool':
            return _u8(stream) == 1
        case 'long' | 'shor':
            return int(_unpack(_I32, stream)[0])
        case 'comp':
            return int(_unpack(_I64, stream)[0])
        case 'dutc':
            return _mac_date(int(_unpack(_I64, stream)[0]))
        case 'type':
            return _fourcc(_take(stream, 4))
        case 'ustr':
            return _utf16(stream)
        case 'blob':
            return _decode_blob(code, _take(stream, _u32(stream)))
        case _:
            msg = f'Unknown record data type `{kind}`.'
            raise InvalidFormatError(msg)


def _read_record(stream: io.BytesIO) -> tuple[str, str, Any]:
    """
    Read one record.

    Parameters
    ----------
    stream : io.BytesIO
        The file, positioned where the record begins.

    Returns
    -------
    tuple[str, str, Any]
        The file name, the structure identifier, and the decoded value.
    """
    name = _utf16(stream)
    code = _fourcc(_take(stream, 4))
    kind = _fourcc(_take(stream, 4))
    return name, code, _read_value(stream, code, kind)


def _read_header(stream: io.BytesIO) -> tuple[int, int, int]:
    """
    Read and check the file header.

    Parameters
    ----------
    stream : io.BytesIO
        The file.

    Returns
    -------
    tuple[int, int, int]
        The alignment word, and the allocator's offset and size.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        When the magic, the alignment, the paired offsets, or the size is wrong.
    """
    stream.seek(0)
    alignment, magic, offset, size, offset_copy = _unpack(_HEADER, stream)
    if alignment != 1 or magic != _MAGIC:
        msg = f'Not a Buddy allocator file (magic {_fourcc(magic)!r}, alignment {alignment}).'
        raise InvalidFormatError(msg)
    if offset == 0 or offset != offset_copy:
        msg = f'Allocator offset {offset} does not match its copy {offset_copy}.'
        raise InvalidFormatError(msg)
    if size == 0:
        msg = 'The allocator has no size.'
        raise InvalidFormatError(msg)
    return int(alignment), int(offset), int(size)


def _read_allocator(stream: io.BytesIO, offset: int) -> _Allocator:
    """
    Read the allocator's block table, directory list, and free lists.

    Parameters
    ----------
    stream : io.BytesIO
        The file.
    offset : int
        The allocator's offset, as the header states it.

    Returns
    -------
    _Allocator
        Every block as an offset and size pair, every directory as a name and block number, and the
        32 free lists.
    """
    stream.seek(offset + _BLOCK_BASE)
    count = _u32(stream)
    _take(stream, 4)
    padded = -(-count // _ADDRESS_PAGE) * _ADDRESS_PAGE
    addresses = _unpack(struct.Struct(f'>{padded}I'), stream)[:count] if padded else ()
    blocks = tuple(
        (int(address) & ~_SIZE_MASK, 1 << (int(address) & _SIZE_MASK)) for address in addresses)
    directories = []
    for _ in range(_u32(stream)):
        name = _take(stream, _u8(stream)).decode()
        directories.append((name, _u32(stream)))
    free_list = []
    for _ in range(_FREE_LISTS):
        entries = _u32(stream)
        free_list.append(tuple(_u32(stream) for _ in range(entries)))
    return _Allocator(blocks, tuple(directories), tuple(free_list))


def _seek_block(stream: io.BytesIO, allocator: _Allocator, block: int) -> None:
    """
    Position the file at a block's body.

    Parameters
    ----------
    stream : io.BytesIO
        The file.
    allocator : _Allocator
        The allocator whose block table addresses the block.
    block : int
        The block number.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        When the block number is outside the block table.
    """
    if block >= len(allocator.blocks):
        msg = f'Block {block} is outside the table of {len(allocator.blocks)} blocks.'
        raise InvalidFormatError(msg)
    stream.seek(allocator.blocks[block][0] + _BLOCK_BASE)


def _walk(stream: io.BytesIO, allocator: _Allocator, block: int,
          visited: set[int]) -> Iterator[tuple[str, str, Any]]:
    """
    Walk one node of the B-tree, yielding every record at and below it in order.

    A node opens with the block number of its last child. Zero marks a leaf. A leaf stores its
    records back to back. Any other value marks an internal node. An internal node precedes each of
    its records with the block number of the child before it, and it takes the opening number as
    the child after the final record.

    Parameters
    ----------
    stream : io.BytesIO
        The file.
    allocator : _Allocator
        The allocator whose block table addresses the node.
    block : int
        The node's block number.
    visited : set[int]
        Block numbers already walked. A malformed file could otherwise cycle through them.

    Yields
    ------
    tuple[str, str, Any]
        The file name, the structure identifier, and the decoded value of each record.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        When a block is visited twice or lies outside the block table.
    """
    if block in visited:
        msg = f'Block {block} is part of a cycle.'
        raise InvalidFormatError(msg)
    visited.add(block)
    _seek_block(stream, allocator, block)
    last = _u32(stream)
    count = _u32(stream)
    if last == 0:
        for _ in range(count):
            yield _read_record(stream)
        return
    position = stream.tell()
    for _ in range(count):
        stream.seek(position)
        child = _u32(stream)
        position = stream.tell()
        yield from _walk(stream, allocator, child, visited)
        stream.seek(position)
        record = _read_record(stream)
        position = stream.tell()
        yield record
    yield from _walk(stream, allocator, last, visited)


def _read_tree(stream: io.BytesIO, allocator: _Allocator, block: int) -> DSStoreTreeDict:
    """
    Read a directory's master block.

    Parameters
    ----------
    stream : io.BytesIO
        The file.
    allocator : _Allocator
        The allocator whose block table addresses the master block.
    block : int
        The master block's number.

    Returns
    -------
    DSStoreTreeDict
        The tree's root node, depth, totals, and page size.
    """
    _seek_block(stream, allocator, block)
    root_node, levels, records, nodes, page_size = _unpack(_MASTER, stream)
    return {
        'levels': int(levels),
        'nodes': int(nodes),
        'page_size': int(page_size),
        'records': int(records),
        'root_node': int(root_node)
    }


def read_ds_store(path: Path) -> DSStoreDict:
    """
    Read a ``.DS_Store`` desktop database.

    Every directory the allocator lists is walked, and in practice a file stores the one directory
    Finder writes, ``DSDB``. Records are grouped by the file name they belong to. The ``.`` entry
    belongs to the folder the file sits in rather than to anything inside it.

    Parameters
    ----------
    path : pathlib.Path
        The file to read.

    Returns
    -------
    DSStoreDict
        Every record, grouped by file name, and the allocator's own bookkeeping beside it.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        When the file is not a Buddy allocator file, or a block, record, or data type inside it
        cannot be read.
    """  # ruff: ignore[docstring-extraneous-exception]
    stream = io.BytesIO(path.read_bytes())
    alignment, offset, size = _read_header(stream)
    allocator = _read_allocator(stream, offset)
    entries: dict[str, dict[str, Any]] = {}
    trees: dict[str, DSStoreTreeDict] = {}
    for name, block in allocator.directories:
        tree = _read_tree(stream, allocator, block)
        trees[name] = tree
        for filename, code, value in _walk(stream, allocator, tree['root_node'], set()):
            entries.setdefault(filename, {})[code] = value
    blocks: list[DSStoreBlockDict] = [{
        'offset': block_offset,
        'size': block_size
    } for block_offset, block_size in allocator.blocks]
    structure: DSStoreStructureDict = {
        'blocks': blocks,
        'directories': trees,
        'free_list': [list(free) for free in allocator.free_list],
        'header': {
            'alignment': alignment,
            'allocator_offset': offset,
            'allocator_size': size,
            'magic': _MAGIC.decode()
        }
    }
    return {'entries': entries, 'structure': structure}
