"""
EA ``BIGF`` archive reader.

A generic EA RenderWare-era container. The header is mixed-endian (its signature
quirk): magic ``BIGF``, a little-endian archive size, then a big-endian entry count
and table-of-contents size. Each TOC entry is a big-endian ``(offset, size)`` pair
followed by a NUL-terminated, ``/``-separated relative path. Payloads are stored raw.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO

__all__ = ('BigEntry', 'iter_big_payloads', 'parse_toc', 'unpack')

_CHUNK = 1 << 20
_HEADER = 16


class BigEntry(NamedTuple):
    """A single table-of-contents record in a ``BIGF`` archive."""

    offset: int
    """Absolute byte offset of the payload from the start of the archive."""
    size: int
    """Payload size in bytes."""
    name: str
    """Relative path of the entry within the archive."""


def parse_toc(path: Path) -> tuple[tuple[BigEntry, ...], int]:
    """
    Parse the header and table of contents of a ``BIGF`` archive.

    Parameters
    ----------
    path : pathlib.Path
        Path to the ``.big`` archive.

    Returns
    -------
    tuple[tuple[BigEntry, ...], int]
        The parsed entries and the real on-disk file size.

    Raises
    ------
    ValueError
        If the file does not begin with the ``BIGF`` magic.
    """
    real = path.stat().st_size
    with path.open('rb') as f:
        head = f.read(_HEADER)
        if head[:4] != b'BIGF':
            msg = f'{path}: not a BIGF archive (magic={head[:4]!r})'
            raise ValueError(msg)
        count = struct.unpack('>I', head[8:12])[0]
        entries = []
        for _ in range(count):
            off, sz = struct.unpack('>II', f.read(8))
            name = bytearray()
            while (c := f.read(1)) not in {b'\x00', b''}:
                name += c
            entries.append(BigEntry(off, sz, name.decode('latin1')))
    return tuple(entries), real


def _safe_join(base: Path, rel: str) -> Path:
    cleaned = rel.replace('\\', '/').lstrip('/')
    dest = (base / cleaned).resolve()
    if dest != base.resolve() and base.resolve() not in dest.parents:
        msg = f'unsafe path escapes base: {rel!r}'
        raise ValueError(msg)
    return dest


def _copy_range(src: BinaryIO, dest: Path, size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    remaining = size
    with dest.open('wb') as out:
        while remaining:
            if not (chunk := src.read(min(_CHUNK, remaining))):
                msg = f'{dest}: short read'
                raise EOFError(msg)
            out.write(chunk)
            remaining -= len(chunk)


def unpack(path: Path, out_root: Path) -> tuple[int, int]:
    """
    Extract every entry of a ``BIGF`` archive into ``out_root/<stem>/``.

    A ``_manifest.tsv`` listing ``name``, ``offset`` and ``size`` is written
    alongside the extracted files.

    Parameters
    ----------
    path : pathlib.Path
        The ``.big`` archive to extract.
    out_root : pathlib.Path
        Directory under which the ``<stem>/`` output tree is created.

    Returns
    -------
    tuple[int, int]
        The number of entries written and the total number of bytes written.

    Raises
    ------
    ValueError
        If an entry's byte range exceeds the file size.
    """
    entries, real = parse_toc(path)
    base = out_root / path.stem
    base.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open('rb') as f:
        for entry in entries:
            if entry.offset + entry.size > real:
                msg = f'{entry.name}: range {entry.offset}+{entry.size} exceeds file {real}'
                raise ValueError(msg)
            f.seek(entry.offset)
            _copy_range(f, _safe_join(base, entry.name), entry.size)
            written += entry.size
    (base / '_manifest.tsv').write_text('name\toffset\tsize\n' +
                                        ''.join(f'{e.name}\t{e.offset}\t{e.size}\n'
                                                for e in entries))
    return len(entries), written


def iter_big_payloads(path: Path) -> Iterator[tuple[str, bytes]]:
    """
    Yield ``(name, payload)`` for each entry without writing to disk.

    Parameters
    ----------
    path : pathlib.Path
        The ``.big`` archive.

    Yields
    ------
    tuple[str, bytes]
        The entry name and its raw payload bytes.
    """
    entries, _ = parse_toc(path)
    with path.open('rb') as f:
        for entry in entries:
            f.seek(entry.offset)
            yield entry.name, f.read(entry.size)
