"""Convenience wrapper tying a source to the sans-I/O :py:class:`~destin.bitrock.sansio.CookFS`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .io import resolve_reader
from .sansio import CookFS

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from typing_extensions import Self

    from .typing import PageCompression, PayloadInfo, Reader

__all__ = ('InstallBuilderFile',)


class InstallBuilderFile:
    """
    Read-only view over the members of an InstallBuilder installer.

    Accepts a filesystem path (memory-mapped on demand), an in-memory image, or any object
    implementing :py:class:`~destin.bitrock.typing.Reader`. When given a path, the mapping is
    released by :py:meth:`close` or by using the archive as a context manager.

    Parameters
    ----------
    source : str | :py:class:`~pathlib.Path` | bytes | bytearray | memoryview | Reader
        The installer to read.
    end_offset : int | None
        Offset just past the ``CFS0002`` signature, when known. Skips the auto-detection scan.
    password : bytes | str | None
        Password for an encrypted installer. May also be supplied later via :py:meth:`unlock`.
    page_compression : PageCompression | None
        Override the auto-detected compression algorithm for encrypted pages. ``None`` auto-detects.
    """
    def __init__(self,
                 source: str | Path | bytes | bytearray | memoryview | Reader,
                 *,
                 end_offset: int | None = None,
                 password: bytes | str | None = None,
                 page_compression: PageCompression | None = None) -> None:
        reader, self._owned = resolve_reader(source)
        try:
            self.cookfs = CookFS(reader,
                                 end_offset=end_offset,
                                 password=password,
                                 page_compression=page_compression)
        except BaseException:
            self.close()
            raise

    @property
    def is_encrypted(self) -> bool:
        """Whether the installer is password-protected."""
        return self.cookfs.is_encrypted

    @property
    def payload_info(self) -> PayloadInfo | None:
        """The parsed password header, or ``None`` when the installer is not encrypted."""
        return self.cookfs.payload_info

    def unlock(self, password: bytes | str) -> None:
        """
        Supply the password for an encrypted installer.

        Parameters
        ----------
        password : bytes | str
            The password to verify.
        """
        self.cookfs.unlock(password)

    def __enter__(self) -> Self:
        """
        Return the archive for use in a ``with`` block.

        Returns
        -------
        Self
            This archive.
        """
        return self

    def __exit__(self, *_: object) -> None:
        """Close the archive on leaving a ``with`` block."""
        self.close()

    def __iter__(self) -> Iterator[str]:
        """
        Iterate over the logical member paths.

        Returns
        -------
        Iterator[str]
            Iterator over the member paths.
        """
        return iter(self.namelist)

    @property
    def namelist(self) -> tuple[str, ...]:
        """
        The logical member paths, sorted.

        Every file member, with ``___bitrockBigFile`` parts merged away.
        """
        return self.cookfs.namelist

    def close(self) -> None:
        """Release the source if this archive opened it."""
        if self._owned is not None:
            self._owned.close()

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
        """
        return self.cookfs.read(path)

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
            The member's size in bytes.
        """
        return self.cookfs.get_size(path)
