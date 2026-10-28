"""
Read-only ISO 9660 filesystem reader.

Parse a standard ISO 9660 image and extract files by path. The image may be an in-memory buffer or
any :py:class:`~dade.common.io.Reader`, and it therefore reads from a cue/bin data track as well.

When the image has a Joliet supplementary volume descriptor, its tree is read instead of the tree
of the primary descriptor, and paths are the long names it records with their case retained.
Otherwise paths are the short upper-case names of the primary descriptor. Lookups ignore case in
both trees.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import re

from dade.common.exceptions import InvalidFormatError
from dade.common.io import BytesReader, u16, u32

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Self

    from dade.common.io import Reader

__all__ = ('Iso9660Image',)

_PVD_OFFSET = 16 * 2048
"""Byte offset of the primary volume descriptor (logical block address 16).

:meta hide-value:
"""
_STANDARD_ID = b'\x01CD001'
"""Volume-descriptor type byte (``1``) followed by the ``CD001`` standard identifier.

:meta hide-value:
"""
_JOLIET_TYPE = 2
"""Volume-descriptor type of a supplementary volume descriptor.

:meta hide-value:
"""
_TERMINATOR_TYPE = 255
"""Volume-descriptor type that ends the descriptor set.

:meta hide-value:
"""
_JOLIET_ESCAPES = frozenset({b'%/@', b'%/C', b'%/E'})
"""Escape sequences marking a supplementary descriptor as Joliet, one for each UCS-2 level.

:meta hide-value:
"""
_ESCAPE_OFFSET = 88
"""Offset of the escape sequences within a supplementary volume descriptor.

:meta hide-value:
"""
_DESCRIPTOR_LIMIT = 32
"""The most volume descriptors read before giving up on a terminator.

:meta hide-value:
"""
_BLOCK_SIZE_OFFSET = 128
"""Offset of the logical block size within the primary volume descriptor.

:meta hide-value:
"""
_ROOT_RECORD_OFFSET = 156
"""Offset of the root directory record within the primary volume descriptor.

:meta hide-value:
"""
_ROOT_RECORD_LENGTH = 34
"""Length of the root directory record.

:meta hide-value:
"""
_EXTENT_OFFSET = 2
"""Offset of the extent logical block address within a directory record.

:meta hide-value:
"""
_SIZE_OFFSET = 10
"""Offset of the data length within a directory record.

:meta hide-value:
"""
_FLAGS_OFFSET = 25
"""Offset of the flags byte within a directory record.

:meta hide-value:
"""
_ID_LENGTH_OFFSET = 32
"""Offset of the file-identifier length within a directory record.

:meta hide-value:
"""
_ID_OFFSET = 33
"""Offset at which the file identifier begins within a directory record.

:meta hide-value:
"""
_FLAG_DIRECTORY = 0x02
"""Directory record flag bit marking a subdirectory.

:meta hide-value:
"""
_VERSION_RE = re.compile(r';\d+$')
"""Match a trailing ``;N`` version suffix on an ISO 9660 file identifier."""


class Iso9660Image:
    """
    A read-only view over an ISO 9660 image.

    Parameters
    ----------
    reader : dade.common.io.Reader
        The byte source for the whole image.

    Raises
    ------
    dade.common.exceptions.InvalidFormatError
        If the primary volume descriptor is missing its ``CD001`` identifier, or a directory record
        references an extent outside the image.
    """
    def __init__(self, reader: Reader) -> None:
        self._reader = reader
        pvd = reader.read(_PVD_OFFSET, 2048)
        if pvd[:6] != _STANDARD_ID:
            msg = 'Not an ISO 9660 image: CD001 identifier not found.'
            raise InvalidFormatError(msg)
        self._block_size = u16(pvd, _BLOCK_SIZE_OFFSET)
        self._files: dict[str, tuple[int, int]] = {}
        self._names: dict[str, str] = {}
        self._joliet = False
        root = pvd
        for index in range(1, _DESCRIPTOR_LIMIT):
            descriptor = reader.read(_PVD_OFFSET + index * 2048, 2048)
            if descriptor[1:6] != _STANDARD_ID[1:] or descriptor[0] == _TERMINATOR_TYPE:
                break
            if descriptor[0] == _JOLIET_TYPE and descriptor[_ESCAPE_OFFSET:_ESCAPE_OFFSET +
                                                            3] in _JOLIET_ESCAPES:
                root, self._joliet = descriptor, True
                break
        self._walk(root[_ROOT_RECORD_OFFSET:_ROOT_RECORD_OFFSET + _ROOT_RECORD_LENGTH], '')

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> Self:
        """
        Build an image from an in-memory buffer.

        Parameters
        ----------
        data : bytes | bytearray | memoryview
            The whole ISO 9660 image.

        Returns
        -------
        Self
            The parsed image.
        """
        return cls(BytesReader(data))

    def contains(self, path: str) -> bool:
        """
        Report whether a file exists at ``path``.

        Parameters
        ----------
        path : str
            POSIX-style, case-insensitive path such as ``GEN/MAIN.ARK``.

        Returns
        -------
        bool
            ``True`` if the file is present.
        """
        return _normalize(path) in self._files

    def iter_files(self) -> Iterator[tuple[str, int]]:
        """
        Yield each file's path and size.

        Yields
        ------
        tuple[str, int]
            The POSIX-style path and the file size in bytes, sorted by path.
        """
        for path in sorted(self._files):
            yield self._names[path], self._files[path][1]

    def locate(self, path: str) -> tuple[int, int]:
        """
        Return where a file's data starts in the image and how long it is.

        This lets a caller stream a large file out of the image, or hand its byte range to another
        reader, without materialising it first.

        Parameters
        ----------
        path : str
            POSIX-style, case-insensitive path such as ``DATA/AUDIO_P.FS``.

        Returns
        -------
        tuple[int, int]
            Byte offset of the file's extent within the image, and its size in bytes.

        Raises
        ------
        KeyError
            If no file exists at ``path``.
        """  # ruff: ignore[docstring-extraneous-exception]
        lba, size = self._files[_normalize(path)]
        return lba * self._block_size, size

    def read_file(self, path: str, length: int | None = None) -> bytes:
        """
        Read the contents of a file, or a leading prefix of it.

        Parameters
        ----------
        path : str
            POSIX-style, case-insensitive path such as ``GEN/MAIN.ARK``.
        length : int | None
            Read at most this many leading bytes (clamped to the file size); ``None`` reads the
            whole file. A prefix read avoids pulling a large file out of the image just to inspect
            its header.

        Returns
        -------
        bytes
            The file contents, or its first ``length`` bytes.
        """
        lba, size = self._files[_normalize(path)]
        return self._read_extent(lba, size if length is None else min(length, size))

    def _read_extent(self, lba: int, size: int) -> bytes:
        """
        Read ``size`` bytes of the extent at ``lba``.

        Parameters
        ----------
        lba : int
            Logical block address of the extent.
        size : int
            Number of bytes to read.

        Returns
        -------
        bytes
            The extent contents.

        Raises
        ------
        dade.common.exceptions.InvalidFormatError
            If the extent lies outside the image.
        """
        offset = lba * self._block_size
        if offset + size > self._reader.size:
            msg = f'Directory record references an extent outside the image at LBA {lba}.'
            raise InvalidFormatError(msg)
        return self._reader.read(offset, size)

    def _walk(self, record: bytes, prefix: str) -> None:
        """
        Recursively add the entries of the directory described by ``record``.

        Parameters
        ----------
        record : bytes
            The directory record of the directory to walk.
        prefix : str
            Path prefix for entries in this directory (empty for the root).
        """
        data = self._read_extent(u32(record, _EXTENT_OFFSET), u32(record, _SIZE_OFFSET))
        pos = 0
        while pos < len(data):
            if (length := data[pos]) == 0:
                pos = ((pos // self._block_size) + 1) * self._block_size
                continue
            child = data[pos:pos + length]
            pos += length
            identifier = child[_ID_OFFSET:_ID_OFFSET + child[_ID_LENGTH_OFFSET]]
            if identifier in {b'\x00', b'\x01'}:
                continue
            name = _VERSION_RE.sub('', identifier.decode('utf-16-be' if self._joliet else 'ascii'))
            if child[_FLAGS_OFFSET] & _FLAG_DIRECTORY:
                self._walk(child, f'{prefix}{name}/')
            else:
                key = f'{prefix}{name}'.upper()
                self._names[key] = f'{prefix}{name}' if self._joliet else key
                self._files[key] = (u32(child, _EXTENT_OFFSET), u32(child, _SIZE_OFFSET))


def _normalize(path: str) -> str:
    """
    Normalise a lookup path to the form used as a dictionary key.

    Parameters
    ----------
    path : str
        A POSIX-style or Windows-style path.

    Returns
    -------
    str
        The path with backslashes converted to forward slashes, surrounding slashes stripped, and
        upper-cased.
    """
    return path.replace('\\', '/').strip('/').upper()
