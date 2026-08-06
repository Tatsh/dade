"""
The Extreme-G 1 ``mfs`` archive directory.

Unlike the self-describing ``XG2Arch`` container the sequel uses, Extreme-G 1 stores a fixed table
of 16-byte records, each beginning with the literal magic ``LZSS`` followed by the decompressed
size, the compressed size, and a *cumulative* end offset. A file's start offset is the previous
file's end offset, and the first comes from the directory header, but all of them are relative to
an archive base that is not stored anywhere.

That base is recovered by :py:func:`calibrate_base`, which searches a small window and keeps the
candidate for which every file decodes and the total slack between files is smallest. A one-byte
error desynchronises LZSS into rubbish, so a wrong base fails loudly rather than quietly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import struct

from destin.common.lz import decompress_lzss0

from .offsets import XG1_MFS_COUNT, XG1_MFS_TABLE
from .typing import MfsEntry

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('MfsCalibrationError', 'calibrate_base', 'iter_files', 'read_table')

_RECORD_SIZE = 0x10
_SEARCH_LOW = -0x20
_SEARCH_HIGH = 0x40


class MfsCalibrationError(ValueError):
    """Raised when no archive base decodes every file in the directory."""
    def __init__(self) -> None:
        super().__init__('Could not calibrate the mfs archive base.')


def read_table(rom: bytes) -> tuple[int, list[MfsEntry]]:
    """
    Read the ``mfs`` directory header and records.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Returns
    -------
    tuple[int, list[destin.xg2.typing.MfsEntry]]
        The first file's start offset and one record per file.

    Raises
    ------
    ValueError
        If a record is missing its ``LZSS`` magic.
    """
    count, _, first = struct.unpack_from('>III', rom, XG1_MFS_COUNT)
    entries = []
    for i in range(count):
        offset = XG1_MFS_TABLE + i * _RECORD_SIZE
        if rom[offset:offset + 4] != b'LZSS':
            msg = f'mfs entry {i} is missing its LZSS magic at 0x{offset:X}.'
            raise ValueError(msg)
        entries.append(MfsEntry(*struct.unpack_from('>III', rom, offset + 4)))
    return first, entries


def _starts(first: int, entries: list[MfsEntry]) -> list[int]:
    return [first, *[entries[i - 1].end_offset for i in range(1, len(entries))]]


def calibrate_base(rom: bytes, first: int, entries: list[MfsEntry]) -> tuple[int, list[int]]:
    """
    Recover the archive base the directory's offsets are relative to.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.
    first : int
        The first file's start offset, from :py:func:`read_table`.
    entries : list[destin.xg2.typing.MfsEntry]
        The directory records, from :py:func:`read_table`.

    Returns
    -------
    tuple[int, list[int]]
        The archive base and each file's start offset relative to it.

    Raises
    ------
    MfsCalibrationError
        If no candidate base decodes every file.
    """
    count = len(entries)
    starts = _starts(first, entries)
    # The last slot's size cannot be derived from the table and is never checked.
    slots = [entries[i].end_offset - starts[i] for i in range(count)]
    table_end = XG1_MFS_TABLE + count * _RECORD_SIZE
    best: tuple[int, int] | None = None
    for candidate in range(table_end - first + _SEARCH_LOW, table_end - first + _SEARCH_HIGH):
        if candidate + starts[0] < table_end:
            continue
        slack = 0
        for i in range(count):
            try:
                _, consumed = decompress_lzss0(rom, candidate + starts[i],
                                               entries[i].decompressed_size)
            except IndexError:
                break
            if i < count - 1:
                if consumed > slots[i]:
                    break
                slack += slots[i] - consumed
        else:
            if best is None or slack < best[0]:
                best = (slack, candidate)
    if best is None:
        raise MfsCalibrationError
    return best[1], starts


def iter_files(rom: bytes) -> Iterator[tuple[int, int, MfsEntry, bytes]]:
    """
    Decompress every file in the ``mfs`` archive.

    Parameters
    ----------
    rom : bytes
        The whole ROM image.

    Yields
    ------
    tuple[int, int, destin.xg2.typing.MfsEntry, bytes]
        The file index, its absolute ROM offset, its directory record, and its contents. A
        :py:class:`MfsCalibrationError` propagates if no candidate archive base validates.
    """
    first, entries = read_table(rom)
    base, starts = calibrate_base(rom, first, entries)
    for i, entry in enumerate(entries):
        offset = base + starts[i]
        yield i, offset, entry, decompress_lzss0(rom, offset, entry.decompressed_size)[0]
