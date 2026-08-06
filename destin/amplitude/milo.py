"""Decompose Harmonix Milo/Rnd archives (``.rnd``) into their constituent objects."""
from __future__ import annotations

from typing import TYPE_CHECKING
import json
import struct
import zlib

from destin.common.utils import safe_name

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('EXTENSIONS', 'convert', 'milo_decompress')

EXTENSIONS = frozenset({'.rnd'})
"""File extensions handled by :py:func:`convert`."""

_MILO_MAGIC = frozenset({0xCABEDEAF, 0xCBBEDEAF, 0xCCBEDEAF, 0xCDBEDEAF})
_GZIP_MAGIC = 0xCCBEDEAF
_UNCOMPRESSED_MAGIC = 0xCABEDEAF
_SENTINEL = b'\xad\xde\xad\xde'  # 0xADDEADDE: Milo inter-object body terminator.
_GZIP_WBITS = 16 + zlib.MAX_WBITS
_MAX_NAME = 256
_MILO_V6 = 6  # FreQuency's uncompressed Milo directory version (stored as the leading u32).
_MILO_MIN_SIZE = 16  # Compressed Milo header: magic, dataStart, numBlocks, maxBlockSize.
_DIR_VERSION_SIZE = 4  # A directory's leading version u32.
_DIR_HEADER_SIZE = 8  # A directory's version plus its object count.


def milo_decompress(data: bytes) -> tuple[bytes | None, int]:
    """
    Decompress a Milo archive's directory.

    The container is ``u32 magic, u32 dataStart, u32 numBlocks, u32 maxBlockSize, u32[n]
    blockSizes``, then the (gzip- or zlib-) compressed blocks beginning at ``dataStart``.

    Parameters
    ----------
    data : bytes
        The ``.rnd`` file contents.

    Returns
    -------
    tuple[bytes | None, int]
        The decompressed directory bytes (``None`` if not a Milo archive) and the block count.
    """
    if len(data) < _MILO_MIN_SIZE:
        return None, 0
    magic = struct.unpack_from('<I', data, 0)[0]
    if magic not in _MILO_MAGIC:
        return None, 0
    if magic == _UNCOMPRESSED_MAGIC:
        return data[struct.unpack_from('<I', data, 4)[0]:], 1
    start = struct.unpack_from('<I', data, 4)[0]
    n = struct.unpack_from('<I', data, 8)[0]
    sizes = struct.unpack_from(f'<{n}I', data, 0x10)
    pos = start
    out = bytearray()
    for size in sizes:
        block = data[pos:pos + size]
        pos += size
        try:
            out += (zlib.decompress(block, _GZIP_WBITS)
                    if magic == _GZIP_MAGIC else zlib.decompress(block))
        except zlib.error:  # A stored (uncompressed) block.
            out += block
    return bytes(out), n


def _parse_table(body: bytes, count: int) -> tuple[list[tuple[str, str]], int, bool]:
    table: list[tuple[str, str]] = []
    off = 8
    for _ in range(count):
        # A struct or decode error anywhere in a record means the whole table is malformed.
        try:  # noqa: PLW0717
            tl = struct.unpack_from('<I', body, off)[0]
            if tl > _MAX_NAME:
                return table, off, False
            typ = body[off + 4:off + 4 + tl].decode('latin-1')
            off += 4 + tl
            nl = struct.unpack_from('<I', body, off)[0]
            if nl > _MAX_NAME:
                return table, off, False
            nam = body[off + 4:off + 4 + nl].decode('latin-1')
            off += 4 + nl
        except (struct.error, UnicodeDecodeError):
            return table, off, False
        table.append((typ, nam))
    return table, off, True


def _parse_v6_table(body: bytes, count: int) -> tuple[list[tuple[str, str]], int, bool]:
    # FreQuency (version 6) stores the object table as ``count`` NUL-terminated (type, name) pairs,
    # each followed by a 0x01 separator, then a single sentinel before the first object body.
    table: list[tuple[str, str]] = []
    off, n = 8, len(body)
    for _ in range(count):
        try:
            t_end = body.index(b'\0', off)
            typ = body[off:t_end].decode('latin-1')
            n_end = body.index(b'\0', t_end + 1)
            nam = body[t_end + 1:n_end].decode('latin-1')
            off = n_end + 1
        except (ValueError, UnicodeDecodeError):
            return table, off, False
        if len(typ) > _MAX_NAME or len(nam) > _MAX_NAME:
            return table, off, False
        if off < n and body[off] == 0x01:  # Inter-entry separator.
            off += 1
        table.append((typ, nam))
    if body[off:off + len(_SENTINEL)] == _SENTINEL:  # Sentinel terminates the table.
        off += len(_SENTINEL)
    return table, off, True


def convert(path: Path) -> Path | None:  # noqa: PLR0914
    """
    Decompose a ``.rnd`` Milo archive into a ``<name>/`` folder of objects plus a manifest.

    The Amplitude directory layout (version 10) is ``u32 version, u32 objectCount, then objectCount
    length-prefixed (type, name) pairs, then per-object bodies`` -- each body terminated by the
    ``0xADDEADDE`` sentinel, which lets the bodies be split without per-class deserializers.
    FreQuency (version 6) is stored uncompressed and uses NUL-terminated (type, name) pairs each
    followed by a ``0x01`` separator; the rest splits on the same sentinel.

    Parameters
    ----------
    path : pathlib.Path
        The ``.rnd`` file.

    Returns
    -------
    pathlib.Path | None
        The output directory, or ``None`` if the file was not a Milo archive.
    """
    data = path.read_bytes()
    body, n_blocks = milo_decompress(data)
    if body is None:
        # FreQuency stores its Milo (version 6) uncompressed: the file is the directory itself.
        if len(data) >= _DIR_HEADER_SIZE and struct.unpack_from('<I', data, 0)[0] == _MILO_V6:
            body, n_blocks = data, 1
        else:
            return None
    version = struct.unpack_from('<I', body, 0)[0] if len(body) >= _DIR_VERSION_SIZE else None
    count = struct.unpack_from('<I', body, 4)[0] if len(body) >= _DIR_HEADER_SIZE else 0
    table, off, ok = (_parse_v6_table(body, count) if version == _MILO_V6 else _parse_table(
        body, count))
    out_dir = path.with_suffix('')
    out_dir.mkdir(parents=True, exist_ok=True)
    objects: list[dict[str, object]] = []
    note: str | None = None
    if ok and table:
        pos = off
        used: dict[str, int] = {}
        for typ, nam in table:
            end = body.find(_SENTINEL, pos)
            end = len(body) if end < 0 else end
            blob = body[pos:end]
            pos = end + len(_SENTINEL)
            fn = safe_name(nam)
            seen = used.get(fn, 0)
            used[fn] = seen + 1
            if seen:
                stem, dot, ext = fn.rpartition('.')
                fn = f'{stem}_{seen}{dot}{ext}' if dot else f'{fn}_{seen}'
            (out_dir / fn).write_bytes(blob)
            objects.append({'type': typ, 'name': nam, 'file': fn, 'size': len(blob)})
    else:
        (out_dir / f'{path.stem}.milo').write_bytes(body)
        note = 'object table unparsed; decompressed Milo kept whole'
    manifest: dict[str, object] = {
        'source': path.name,
        'milo_magic': hex(struct.unpack_from('<I', data, 0)[0]),
        'blocks': n_blocks,
        'version': version,
        'object_count': count,
        'decompressed_size': len(body),
        'objects': objects,
    }
    if note is not None:
        manifest['note'] = note
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                           encoding='utf-8')
    path.unlink()
    return out_dir
