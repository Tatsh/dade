r"""
Read and extract the two Harmonix v2 ARK archive layouts.

The Amplitude layout (a single ``GEN/MAIN.ARK``) and the FreQuency layout
(``ARK/{ROOT,ARENAS,LOADING,LEVELS}.ARK``) are auto-detected by :py:func:`parse_directory`.

**Amplitude** (all little-endian), from the game's directory code
(``ConstructArkHashTable`` / ``FindArkHashEntry`` / ``FindArkFileEntry``)::

    u32  version            # == 2 (no magic; the file starts with the version)
    u32  count              # number of file records
    count * FileRecord:
        u32 dataOffset      # absolute byte offset of the file's data in the ARK
        u32 fileBkt         # hash-table bucket index of the file name
        u32 dirBkt          # hash-table bucket index of the dir name (0xFFFFFFFF = root)
        u32 size            # file size in bytes
        u32 flags
    u32  poolSize           # size of the name string pool
    u8   pool[poolSize]     # NUL-separated interned names (dirs and files)
    u32  nBuckets           # hash bucket count
    u32  bucket[nBuckets]   # each entry = a name's offset into the string pool
    ...  file data ...

A record's ``fileBkt``/``dirBkt`` are bucket indices; ``bucket[idx]`` is the name's offset
into the string pool, where a NUL-terminated string holds the name. The full path is
``<dir>/<file>`` (or just ``<file>`` at root).

**FreQuency** (all little-endian), from the loader ``FUN_00559858``::

    u32  magic              # 'ARK\\0' (0x004b5241)
    u32  version            # == 2
    u32  frecOff            # offset of the file-record table (always 0x100)
    u32  nFiles             # number of 24-byte file records
    u32  drecOff            # offset of the dir-record table (== frecOff + nFiles*24)
    u32  nDirs              # number of 8-byte dir records
    u32  poolOff            # offset of the name pool (== drecOff + nDirs*8)
    u32  nNames             # total interned names (== nFiles + nDirs)
    u32  dataOff            # first data byte; the first file starts at the next 0x800 block
    u32  blockSize          # data block size (0x800)
    nFiles * FileRecord (24 bytes):
        u32 nameHash        # name hash (unused for extraction)
        u32 nameOff         # absolute byte offset of the NUL-terminated file name
        u32 packed          # (inBlockOffset << 16) | dirIndex
        u32 block           # data block index; offset = block*0x800 + (packed >> 16)
        u32 onDiskSize      # bytes stored in the ARK (gzip stream when compressed)
        u32 rawSize         # uncompressed size (== onDiskSize when stored raw)
    nDirs * DirRecord (8 bytes):
        u32 nameHash        # dir-name hash (unused)
        u32 nameOff         # absolute byte offset of the NUL-terminated dir path
    u8   pool[...]          # NUL-separated names, spanning [poolOff, dataOff)
    ...  file data ...

Dir paths are already slash-joined (e.g. ``metagame/arena/gen``). A file is gzip-compressed
exactly when ``onDiskSize != rawSize``; in this archive that set is identical to the set of
entries whose name ends in ``.gz``, so :py:func:`extract`'s name-based gunzip handles both
layouts uniformly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import struct
import zlib

from destin.common.io import copy_region, read_cstring

from .typing import ARKEntry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO

__all__ = ('ARKDirectory', 'ExtractStats', 'extract', 'list_entries', 'parse_directory')

_HDR = struct.Struct('<II')
_REC = struct.Struct('<5I')  # dataOffset, fileBkt, dirBkt, size, flags
_CHUNK = 1 << 20
_GZIP_WBITS = 16 + zlib.MAX_WBITS
_ROOT_BUCKET = 0xFFFFFFFF

_ARK_VERSION = 2
_FREQ_MAGIC = b'ARK\x00'
_FREQ_HDR = struct.Struct('<10I')
_FREQ_REC = struct.Struct('<6I')  # nameHash, nameOff, packed, block, onDiskSize, rawSize
_FREQ_DREC = struct.Struct('<2I')  # nameHash, nameOff


class ARKDirectory(NamedTuple):
    """The parsed header and entry table of an ARK archive."""

    version: int
    """Archive format version (always ``2`` here)."""
    pool_size: int
    """Size of the name string pool in bytes."""
    n_buckets: int
    """Number of hash buckets."""
    dir_end: int
    """Byte offset where the directory ends and file data begins."""
    entries: tuple[ARKEntry, ...]
    """All file records, in directory order."""


class ExtractStats(NamedTuple):
    """Counts produced by :py:func:`extract`."""

    written: int
    """Number of files written to disk."""
    skipped: int
    """Number of records skipped because their data exceeded the archive."""
    gunzipped: int
    """Number of ``.gz`` entries decompressed in place."""
    gunzip_failed: int
    """Number of ``.gz``-named entries that were not valid gzip (kept verbatim)."""
    raw_bytes: int
    """Total bytes read from the archive."""
    disk_bytes: int
    """Total bytes written to disk."""


def _cstr(pool: bytes, off: int) -> str:
    if off < 0 or off >= len(pool):
        msg = f'Name offset {off:#x} out of pool (size {len(pool):#x}).'
        raise ValueError(msg)
    return read_cstring(pool, off)


def parse_directory(data: bytes) -> ARKDirectory:
    r"""
    Parse the header and entry table of an ARK archive, auto-detecting its layout.

    A leading ``ARK\\0`` magic selects the FreQuency layout; otherwise the Amplitude
    (magic-less, version-first) layout is assumed.

    Parameters
    ----------
    data : bytes
        At least the leading directory region of the archive.

    Returns
    -------
    ARKDirectory
        The parsed directory.
    """
    if data[:4] == _FREQ_MAGIC:
        return _parse_freq_directory(data)
    return _parse_amplitude_directory(data)


def _parse_freq_directory(data: bytes) -> ARKDirectory:  # noqa: PLR0914
    r"""
    Parse the FreQuency ``ARK\\0`` layout (see the module docstring).

    Parameters
    ----------
    data : bytes
        At least the leading directory region of the archive.

    Returns
    -------
    ARKDirectory
        The parsed directory.

    Raises
    ------
    ValueError
        If the version is not ``2`` or a directory index is out of range.
    """
    (_magic, version, frec_off, n_files, drec_off, n_dirs, pool_off, _n_names, data_off,
     block_size) = _FREQ_HDR.unpack_from(data, 0)
    if version != _ARK_VERSION:
        msg = f'Unsupported FreQuency ARK version {version} (expected 2).'
        raise ValueError(msg)
    dir_paths = [
        _cstr(data,
              _FREQ_DREC.unpack_from(data, drec_off + i * 8)[1]) for i in range(n_dirs)
    ]
    entries: list[ARKEntry] = []
    for i in range(n_files):
        _hash, name_off, packed, block, on_disk, _raw = _FREQ_REC.unpack_from(
            data, frec_off + i * 24)
        name = _cstr(data, name_off)
        dir_idx = packed & 0xFFFF
        if dir_idx >= n_dirs:
            msg = f'Dir index {dir_idx} >= nDirs {n_dirs} for {name!r}.'
            raise ValueError(msg)
        dname = dir_paths[dir_idx]
        offset = block * block_size + (packed >> 16)
        entries.append(ARKEntry(f'{dname}/{name}' if dname else name, offset, on_disk, 0))
    return ARKDirectory(version, max(0, data_off - pool_off), 0, data_off, tuple(entries))


def _parse_amplitude_directory(data: bytes) -> ARKDirectory:
    """
    Parse the Amplitude (magic-less, version-first) layout (see the module docstring).

    Parameters
    ----------
    data : bytes
        At least the leading directory region of the archive.

    Returns
    -------
    ARKDirectory
        The parsed directory.

    Raises
    ------
    ValueError
        If the version is not ``2`` or a bucket/name reference is out of range.
    """
    version, count = _HDR.unpack_from(data, 0)
    if version != _ARK_VERSION:
        msg = f'Unsupported ARK version {version} (expected 2).'
        raise ValueError(msg)
    recs = [_REC.unpack_from(data, 8 + i * _REC.size) for i in range(count)]
    pos = 8 + count * _REC.size
    (pool_size,) = struct.unpack_from('<I', data, pos)
    pos += 4
    pool = data[pos:pos + pool_size]
    pos += pool_size
    (n_buckets,) = struct.unpack_from('<I', data, pos)
    pos += 4
    buckets = struct.unpack_from(f'<{n_buckets}I', data, pos)
    dir_end = pos + n_buckets * 4

    def name_for_bucket(bkt: int) -> str:
        if bkt == _ROOT_BUCKET:
            return ''
        if bkt >= n_buckets:
            msg = f'Bucket index {bkt} >= nBuckets {n_buckets}.'
            raise ValueError(msg)
        return _cstr(pool, buckets[bkt])

    entries: list[ARKEntry] = []
    for data_off, file_bkt, dir_bkt, size, flags in recs:
        fname = name_for_bucket(file_bkt)
        dname = name_for_bucket(dir_bkt)
        entries.append(ARKEntry(f'{dname}/{fname}' if dname else fname, data_off, size, flags))
    return ARKDirectory(version, pool_size, n_buckets, dir_end, tuple(entries))


def _safe_join(out_dir: Path, rel: str) -> Path:
    parts = [
        p.replace(' ', '_') for p in rel.replace('\\', '/').lstrip('/').split('/')
        if p not in {'', '.', '..'}
    ]
    return out_dir.joinpath(*parts)


def _gunzip_region(src: BinaryIO, offset: int, size: int, dst: Path) -> int:
    src.seek(offset)
    dec = zlib.decompressobj(_GZIP_WBITS)
    remaining = size
    written = 0
    with dst.open('wb') as out:
        while remaining:
            chunk = src.read(min(remaining, _CHUNK))
            if not chunk:
                break
            remaining -= len(chunk)
            data = dec.decompress(chunk)
            if data:
                out.write(data)
                written += len(data)
            while dec.eof and dec.unused_data:  # Drain concatenated gzip members.
                leftover = dec.unused_data
                dec = zlib.decompressobj(_GZIP_WBITS)
                data = dec.decompress(leftover)
                if data:
                    out.write(data)
                    written += len(data)
        tail = dec.flush()
        # A decompressor fed without a length cap leaves nothing pending, so the tail is always
        # empty here; the write is kept in case that ever changes.
        if tail:  # pragma: no cover
            out.write(tail)
            written += len(tail)
    return written


def _read_directory(src: BinaryIO, ark_size: int) -> ARKDirectory:
    src.seek(0)  # The caller obtains ark_size via seek(0, 2), leaving the position at EOF.
    head = src.read(min(ark_size, 8 << 20))
    directory = parse_directory(head)
    if directory.dir_end > len(head):  # Unlikely: directory larger than 8 MiB.
        src.seek(0)
        directory = parse_directory(src.read(directory.dir_end))
    return directory


def extract(ark: Path,
            out_dir: Path,
            *,
            gunzip: bool = True,
            keep_gz: bool = False) -> ExtractStats:
    """
    Extract every entry of an ARK archive into ``out_dir``.

    Parameters
    ----------
    ark : pathlib.Path
        The archive to read.
    out_dir : pathlib.Path
        Output directory (created if missing).
    gunzip : bool
        Decompress ``.gz`` entries in place (writing the de-suffixed name).
    keep_gz : bool
        When decompressing a ``.gz`` entry, also keep the original compressed copy.

    Returns
    -------
    ExtractStats
        Extraction counts.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = gunzipped = gunzip_failed = 0
    raw_bytes = disk_bytes = 0
    with ark.open('rb') as src:
        ark_size = src.seek(0, 2)
        directory = _read_directory(src, ark_size)
        for entry in directory.entries:
            if entry.offset + entry.size > ark_size:
                skipped += 1
                continue
            raw_dst = _safe_join(out_dir, entry.path)
            gz = gunzip and entry.path.lower().endswith('.gz')
            dst = raw_dst.with_suffix('') if gz else raw_dst
            dst.parent.mkdir(parents=True, exist_ok=True)
            raw_bytes += entry.size
            if gz:
                try:
                    disk_bytes += _gunzip_region(src, entry.offset, entry.size, dst)
                    gunzipped += 1
                    if keep_gz:
                        copy_region(src, entry.offset, entry.size, raw_dst)
                except zlib.error:  # ".gz" name but not valid gzip: keep it verbatim.
                    gunzip_failed += 1
                    if dst.exists():  # pragma: no branch -- the decoder always creates it first.
                        dst.unlink()
                    disk_bytes += copy_region(src, entry.offset, entry.size, raw_dst)
            else:
                disk_bytes += copy_region(src, entry.offset, entry.size, raw_dst)
            written += 1
    return ExtractStats(written, skipped, gunzipped, gunzip_failed, raw_bytes, disk_bytes)


def list_entries(ark: Path) -> Iterator[ARKEntry]:
    """
    Yield the entries of an ARK archive without extracting.

    Parameters
    ----------
    ark : pathlib.Path
        The archive to read.

    Yields
    ------
    ARKEntry
        Each file record, in directory order.
    """
    with ark.open('rb') as src:
        ark_size = src.seek(0, 2)
        yield from _read_directory(src, ark_size).entries
