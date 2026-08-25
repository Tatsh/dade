"""
Sans-I/O core for InstallBuilder installers.

Every byte manipulation lives here and runs against a :py:class:`Reader`: a small protocol that
returns bytes for a given offset and length. The caller decides where those bytes come from -- a
:py:class:`bytes` buffer via :py:class:`BytesReader`, a memory-mapped file, or ranged HTTP requests
-- so this module performs no I/O of its own.

The container format is a cookfs archive: an opaque prefix (the ELF launcher stub), a run of
compressed pages, a page directory, and a 16-byte suffix ending in the ``CFS0002`` signature. The
decompressed index (magic ``CFS2.200``) encodes the directory tree, each file listing the blocks
that make up its contents. The format is reproduced from the pure-Tcl cookfs reference
implementation shipped inside the installer (``libraries/cookfs-*/pages.tcl`` and ``fsindex.tcl``,
``(c) 2010-2014 Wojciech Kocjan``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, cast
import re

from dade.common.cookfs import (
    DEFAULT_SEARCH_WINDOW,
    decompress_page,
    locate_end_offset,
    parse_fs_index,
    parse_index,
    read_page_directory,
)
from dade.common.io import BytesReader

from .crypto import decrypt_page, parse_payload_info, verify_password
from .exceptions import CorruptArchiveError, DecryptionError, MemberNotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .typing import PageCompression, PayloadInfo, Reader

__all__ = ('BytesReader', 'CookFS', 'decompress_page', 'parse_fs_index')

_PAYLOAD_INFO_KEY = 'installbuilder.payloadinfo'
"""Metadata key under which InstallBuilder stores the password header.

:meta hide-value:
"""
_CUSTOM_COMPRESSION = b'\xff'
"""Leading page byte marking a page handled by a custom (here, encrypted) decompressor.

:meta hide-value:
"""
_DECOMPRESS_COMMAND_RE = re.compile(rb'decompresscommand\s+\{[^}]*\b(zip|lzma|lzham)\b')
"""
Extracts the page compression algorithm from the trailing ``cookfsinfo`` ``decompresscommand``.

The obfuscated decompressor procedure name is deliberately not matched, so a future InstallBuilder
release that renames it still resolves as long as the algorithm keyword remains a literal argument.

:meta hide-value:
"""
_BIG_FILE_RE = re.compile(r'^(?P<base>.+)___bitrockBigFile(?P<part>\d+)$')
"""Matches the sibling entries InstallBuilder creates when a file exceeds the per-entry limit.

:meta hide-value:
"""


class CookFS:
    """
    Sans-I/O reader over the members of a cookfs archive.

    Large files that InstallBuilder splits into ``___bitrockBigFile`` siblings are presented as a
    single logical member and reassembled transparently by :py:meth:`read`.

    Parameters
    ----------
    reader : Reader
        The byte source for the whole installer image.
    end_offset : int | None
        Offset just past the ``CFS0002`` signature. When ``None`` it is located by scanning the
        final ``search_window`` bytes.
    search_window : int
        Number of trailing bytes to scan when ``end_offset`` is ``None``.
    password : bytes | str | None
        Password for an encrypted installer. May also be supplied later via :py:meth:`unlock`.
    page_compression : PageCompression | None
        The compression algorithm applied to encrypted pages. When ``None`` it is auto-detected
        from the installer; pass an explicit value to override an unreliable detection.

    Raises
    ------
    BitrockError
        If the archive cannot be located or parsed.
    DecryptionError
        If ``password`` is given but incorrect.
    """
    def __init__(self,
                 reader: Reader,
                 *,
                 end_offset: int | None = None,
                 search_window: int = DEFAULT_SEARCH_WINDOW,
                 password: bytes | str | None = None,
                 page_compression: PageCompression | None = None) -> None:
        self._reader = reader
        self._end_offset = locate_end_offset(reader, end_offset, search_window)
        self._page_offsets, self._page_sizes, index_data = read_page_directory(
            reader, self._end_offset)
        self._entries, metadata = parse_index(index_data)
        self._logical = self._build_logical_map()
        self._cache: dict[int, bytes] = {}
        self._payload_info: PayloadInfo | None = (parse_payload_info(metadata[_PAYLOAD_INFO_KEY])
                                                  if _PAYLOAD_INFO_KEY in metadata else None)
        self._payload: tuple[bytes, bytes] | None = None
        self._page_compression: PageCompression = page_compression or (
            self._detect_compression() if self._payload_info is not None else 'zip')
        if password is not None:
            self.unlock(password)

    def _detect_compression(self) -> PageCompression:
        """
        Read the page compression algorithm from the trailing ``cookfsinfo`` metadata.

        Returns
        -------
        PageCompression
            The algorithm named in the ``decompresscommand``, or ``'zip'`` if none is found.
        """
        tail = self._reader.read(self._end_offset, self._reader.size - self._end_offset)
        if match := _DECOMPRESS_COMMAND_RE.search(tail):
            return cast('PageCompression', match.group(1).decode())
        return 'zip'

    @property
    def is_encrypted(self) -> bool:
        """Whether the installer is password-protected."""
        return self._payload_info is not None

    @property
    def payload_info(self) -> PayloadInfo | None:
        """The parsed password header, or ``None`` when the installer is not encrypted."""
        return self._payload_info

    def unlock(self, password: bytes | str) -> None:
        """
        Supply the password for an encrypted installer.

        Parameters
        ----------
        password : bytes | str
            The password to verify.

        Raises
        ------
        DecryptionError
            If the password is incorrect.
        """
        if self._payload_info is None:
            return
        if isinstance(password, str):
            password = password.encode()
        if (payload := verify_password(password, self._payload_info)) is None:
            msg = 'Invalid password.'
            raise DecryptionError(msg)
        self._payload = payload
        self._cache.clear()

    @property
    def namelist(self) -> tuple[str, ...]:
        """
        The logical member paths, sorted.

        Every file member, with ``___bitrockBigFile`` parts merged away.
        """
        return tuple(sorted(self._logical))

    def read(self, path: str) -> bytes:
        """
        Return the full contents of a logical member.

        Parameters
        ----------
        path : str
            A member path as returned by :py:attr:`namelist`.

        Returns
        -------
        bytes
            The reassembled member contents.

        Raises
        ------
        MemberNotFoundError
            If ``path`` is not a member of the archive.
        """
        if (parts := self._logical.get(path)) is None:
            msg = f'No such member: {path!r}.'
            raise MemberNotFoundError(msg)
        return b''.join(self._read_entry(entry) for entry in parts)

    def get_size(self, path: str) -> int:
        """
        Return the uncompressed size of a logical member without decompressing it.

        Parameters
        ----------
        path : str
            A member path as returned by :py:attr:`namelist`.

        Returns
        -------
        int
            The member's size in bytes, summed from the index metadata.

        Raises
        ------
        MemberNotFoundError
            If ``path`` is not a member of the archive.
        """
        if (parts := self._logical.get(path)) is None:
            msg = f'No such member: {path!r}.'
            raise MemberNotFoundError(msg)
        return sum(block.size for entry in parts for block in self._entries[entry])

    def page(self, index: int) -> bytes:
        """
        Return the decompressed contents of a page.

        Parameters
        ----------
        index : int
            Zero-based page index.

        Returns
        -------
        bytes
            The decompressed page.

        Raises
        ------
        CorruptArchiveError
            If ``index`` is out of range.
        DecryptionError
            If the page is encrypted and no valid password has been supplied.
        """
        if not 0 <= index < len(self._page_sizes):
            msg = f'Page index {index} out of range.'
            raise CorruptArchiveError(msg)
        if (cached := self._cache.get(index)) is not None:
            return cached
        raw = self._reader.read(self._page_offsets[index], self._page_sizes[index])
        if self._payload_info is not None and raw[:1] == _CUSTOM_COMPRESSION:
            if self._payload is None:
                msg = 'This installer is password-protected; a password is required.'
                raise DecryptionError(msg)
            page = decrypt_page(raw[1:], self._payload[0], self._payload[1], self._page_compression)
        else:
            page = decompress_page(raw)
        self._cache[index] = page
        return page

    def _build_logical_map(self) -> dict[str, tuple[str, ...]]:
        """
        Group raw index entries into logical members.

        Returns
        -------
        dict[str, tuple[str, ...]]
            Mapping of each logical path to the ordered raw entries that make it up.
        """
        bases: dict[str, dict[int, str]] = {}
        plain: dict[str, tuple[str, ...]] = {}
        for name in self._entries:
            if match := _BIG_FILE_RE.match(name):
                bases.setdefault(match['base'], {})[int(match['part'])] = name
            else:
                plain[name] = (name,)
        for base, siblings in bases.items():
            ordered = tuple(siblings[part] for part in sorted(siblings))
            plain[base] = (base, *ordered) if base in self._entries else ordered
        return plain

    def _read_entry(self, name: str) -> bytes:
        """
        Read the contents of a single raw index entry.

        Parameters
        ----------
        name : str
            Raw entry name present in the parsed index.

        Returns
        -------
        bytes
            The entry's contents, assembled from its blocks.
        """
        return b''.join(
            self.page(block.page_index)[block.offset:block.offset + block.size]
            for block in self._entries[name])

    def __iter__(self) -> Iterator[str]:
        """
        Iterate over the logical member paths.

        Returns
        -------
        Iterator[str]
            Iterator over the member paths.
        """
        return iter(self.namelist)
