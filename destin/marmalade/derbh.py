r"""
Derbh archive (``.dz``) reader.

Derbh is Marmalade's compression/archive technology (packed by the SDK's ``dzip`` tool). On disk
every archive starts with the ASCII magic ``DTRZ``::

    +0x00  char[4]  "DTRZ"
    +0x04  u16      file_count (fc)
    +0x06  u16      folder_count (incl. root)
    +0x08  u8       0x00 (root folder placeholder)
    ...    cstr[fc]            file name strings (NUL-terminated)
    ...    cstr[fc_dirs]       folder path strings ('\\' separators)
    ...    rec[fc] (6 bytes)   attribute table: u16 folderIdx, u16 fileNo, u16 flags
    ...    loc-header           (small, width auto-detected)
    ...    rec[fc | fc+1] (16B) location table: u32 offset, sizeA, sizeB, method
    ...    data

Each file's bytes are decompressed per its ``method`` tag (``0x100`` stored, ``0x200`` LZMA-alone,
``0x8`` gzip with a corrupt trailer CRC). The location records are *not* in file order, so file data
must be windowed by ``offset + size`` rather than by the next record. The attribute table's
``folderIdx`` gives each file's real folder (files share folders), so it is read rather than
guessed.

This module is sans-I/O: :func:`unpack` takes ``bytes`` and returns
:class:`~destin.marmalade.typing.DerbhEntry` objects. :func:`unpack_to_dir` is a thin convenience
wrapper that writes them to disk.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
import logging
import lzma
import struct
import zlib

from .typing import DerbhEntry

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('MAGIC', 'is_derbh', 'unpack', 'unpack_to_dir')

log = logging.getLogger(__name__)

MAGIC = b'DTRZ'
"""Magic bytes at the start of every Derbh archive."""
_GZIP_MAGIC = b'\x1f\x8b'
_LZMA_ALONE_MAGIC = 0x5D
_MAX_TABLE_GAP = 0x1000
"""Maximum gap (bytes) tolerated between the location table and the data region."""
_METHOD_GZIP = 0x8
_METHOD_LZMA = 0x200
_METHOD_STORED = 0x100
_VALID_METHODS = frozenset((0x8, 0x100, 0x200, 0x300, 0x400))
_WINDOW_SLACK = 0x20000
"""Slack added to a file's window; every codec here self-terminates."""
_ZLIB_MAGIC = 0x78


def is_derbh(data: bytes) -> bool:
    """
    Return ``True`` if *data* begins with the Derbh ``DTRZ`` magic.

    Parameters
    ----------
    data : bytes
        Candidate archive bytes.

    Returns
    -------
    bool
        Whether the first four bytes equal :data:`MAGIC`.
    """
    return data[:4] == MAGIC


def _raw_inflate_gzip(blob: bytes) -> bytes:
    """
    Inflate a gzip member via raw DEFLATE, ignoring the (corrupt) trailer CRC.

    Parameters
    ----------
    blob : bytes
        A gzip member (header + DEFLATE stream).

    Returns
    -------
    bytes
        The inflated data.
    """
    flg = blob[3]
    p = 10
    if flg & 4:  # FEXTRA
        p += 2 + struct.unpack_from('<H', blob, p)[0]
    if flg & 8:  # FNAME
        p = blob.index(b'\x00', p) + 1
    if flg & 16:  # FCOMMENT
        p = blob.index(b'\x00', p) + 1
    if flg & 2:  # FHCRC
        p += 2
    d = zlib.decompressobj(wbits=-15)
    return d.decompress(blob[p:]) + d.flush()


def _decompress(blob: bytes, usize: int, method: int) -> bytes:
    """
    Decompress one file's window.

    Dispatch on the per-file ``method`` tag, not the leading magic byte: stored binary data (e.g.
    raw 16-bit PCM) can begin with ``0x5d``/``0x78``/``1f8b`` and would otherwise be misrouted into
    a decompressor.

    Parameters
    ----------
    blob : bytes
        A window starting at the file's data (over-reading is safe; codecs self-terminate).
    usize : int
        Expected uncompressed size, used to slice stored data.
    method : int
        Per-file compression-method tag.

    Returns
    -------
    bytes
        The decompressed file contents.
    """
    if not blob:
        return b''
    if method == _METHOD_STORED:
        return blob[:usize] if usize else blob
    if method == _METHOD_LZMA:
        return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(blob)
    if method == _METHOD_GZIP:
        return _raw_inflate_gzip(blob)
    b0 = blob[0]  # unknown method -> magic-byte fallback
    log.debug('Unknown method %#x; falling back to magic-byte detection (first byte %#04x).',
              method, b0)
    if b0 == _LZMA_ALONE_MAGIC:
        return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(blob)
    if blob[:2] == _GZIP_MAGIC:
        return _raw_inflate_gzip(blob)
    if b0 == _ZLIB_MAGIC:
        return zlib.decompressobj().decompress(blob)
    return blob[:usize] if usize else blob


def _find_loc_table(data: bytes, attr_end: int, fc: int) -> list[tuple[int, int, int, int]] | None:
    """
    Auto-detect the 16-byte-record location table after the attribute table.

    The table is a run of ``(offset, sizeA, sizeB, method)`` records whose offsets all land in
    ``[table_end, n]`` with sane methods; the data region begins at (or just after) the table. Some
    archives append a terminator record (``fc + 1`` records) and/or leave a small gap before the
    data.

    Parameters
    ----------
    data : bytes
        Full archive contents.
    attr_end : int
        Offset just past the attribute table (where the search begins).
    fc : int
        File count.

    Returns
    -------
    list[tuple[int, int, int, int]] or None
        The first ``fc`` location records, or ``None`` if no table was found.
    """
    n = len(data)
    for nrec in (fc + 1, fc):
        for hdr in range(128):
            p = attr_end + hdr
            end = p + nrec * 16
            if end > n:
                continue
            ok = True
            offs: list[tuple[int, int, int, int]] = []
            for i in range(nrec):
                o, a, b, m = struct.unpack_from('<IIII', data, p + i * 16)
                if not (end <= o <= n) or m not in _VALID_METHODS:
                    ok = False
                    break
                offs.append((o, a, b, m))
            if ok:
                mn = min(o for o, *_ in offs)
                if end <= mn <= end + _MAX_TABLE_GAP:
                    log.debug('Located location table at %#x (nrec=%d, header=%d bytes, gap=%d).',
                              p, nrec, hdr, mn - end)
                    return offs[:fc]
    return None


def _read_directory(data: bytes, fc: int,
                    fdirs: int) -> tuple[list[str], list[str], list[int], int]:
    """
    Read the file names, folder paths and attribute table from the archive header.

    Parameters
    ----------
    data : bytes
        Full archive contents.
    fc : int
        File count.
    fdirs : int
        Folder count excluding the root.

    Returns
    -------
    tuple[list[str], list[str], list[int], int]
        File names, folder paths (root first), each file's folder index, and the offset just past
        the attribute table.
    """
    p = 9
    names: list[str] = []
    for _ in range(fc):
        e = data.index(b'\x00', p)
        names.append(data[p:e].decode('latin-1'))
        p = e + 1
    folders = ['']
    for _ in range(fdirs):
        e = data.index(b'\x00', p)
        folders.append(data[p:e].decode('latin-1'))
        p = e + 1
    folder_idx = [struct.unpack_from('<H', data, p + i * 6)[0] for i in range(fc)]
    return names, folders, folder_idx, p + fc * 6


def _decode_entry(data: bytes, rec: tuple[int, int, int, int], name: str, folder: str,
                  n: int) -> DerbhEntry:
    r"""
    Decompress one file and build its :class:`~destin.marmalade.typing.DerbhEntry`.

    Parameters
    ----------
    data : bytes
        Full archive contents.
    rec : tuple[int, int, int, int]
        The file's ``(offset, sizeA, sizeB, method)`` location record.
    name : str
        The file's name.
    folder : str
        The file's folder path (``'\\'`` or ``'/'`` separated).
    n : int
        Total archive size.

    Returns
    -------
    DerbhEntry
        The decoded entry.
    """
    off, sa, sb, method = rec
    usize = sb or sa
    end = min(off + usize + _WINDOW_SLACK, n)
    out = _decompress(data[off:end], usize, method)
    parts = [s for s in folder.replace('\\', '/').split('/') if s]
    path = str(PurePosixPath(*parts, name)) if parts else name
    if usize and len(out) != usize:
        log.warning('Size mismatch for %s: decoded %d bytes, expected %d (method %#x).', path,
                    len(out), usize, method)
    else:
        log.debug('Unpacked %s (method %#x, %d bytes).', path, method, len(out))
    return DerbhEntry(path=path, data=out, method=method)


def unpack(data: bytes) -> Iterator[DerbhEntry]:
    """
    Unpack a Derbh (``.dz``) archive's bytes.

    Parameters
    ----------
    data : bytes
        Full archive contents (starting with ``DTRZ``).

    Yields
    ------
    DerbhEntry
        One entry per file: ``path`` (POSIX-relative), decompressed ``data``, and the raw
        compression ``method`` tag.

    Raises
    ------
    ValueError
        If *data* is not a Derbh archive or its location table cannot be found.
    """
    if not is_derbh(data):
        msg = f'Data is not a Derbh archive (magic {data[:4]!r}).'
        raise ValueError(msg)
    fc = struct.unpack_from('<H', data, 4)[0]
    fdirs = struct.unpack_from('<H', data, 6)[0] - 1
    log.debug('Reading Derbh archive of %d bytes with %d files and %d folders.', len(data), fc,
              fdirs)
    names, folders, folder_idx, attr_end = _read_directory(data, fc, fdirs)
    recs = _find_loc_table(data, attr_end, fc)
    if recs is None:
        msg = 'Could not locate the Derbh location table.'
        raise ValueError(msg)
    n = len(data)
    for i in range(fc):
        fi = folder_idx[i]
        folder = folders[fi] if fi < len(folders) else ''
        yield _decode_entry(data, recs[i], names[i], folder, n)


def unpack_to_dir(data: bytes, outdir: str | Path) -> int:
    """
    Unpack a Derbh archive to *outdir* on disk.

    Parameters
    ----------
    data : bytes
        Full archive contents.
    outdir : str or pathlib.Path
        Destination directory (created if absent).

    Returns
    -------
    int
        Number of files written.
    """
    root = Path(outdir)
    count = 0
    for entry in unpack(data):
        dst = root / entry.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(entry.data)
        count += 1
    log.debug('Wrote %d files to %s.', count, root)
    return count
