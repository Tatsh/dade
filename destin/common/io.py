"""Generic random-access byte-source readers shared by the game submodules."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
import mmap

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self

__all__ = ('BytesReader', 'MmapReader', 'Reader', 'resolve_reader')


@runtime_checkable
class Reader(Protocol):
    """A random-access source of bytes. Implementations perform whatever I/O they need."""
    @property
    def size(self) -> int:
        """Total number of bytes available."""
        ...

    def read(self, offset: int, length: int, /) -> bytes:
        """
        Return ``length`` bytes starting at ``offset``.

        Parameters
        ----------
        offset : int
            Zero-based start offset.
        length : int
            Number of bytes to return.

        Returns
        -------
        bytes
            The requested slice.
        """
        ...


class BytesReader:
    """
    A :py:class:`Reader` backed by an in-memory buffer.

    Parameters
    ----------
    data : bytes | bytearray | memoryview
        The whole image.
    """
    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self._data = memoryview(data)

    @property
    def size(self) -> int:
        """Total number of bytes available."""
        return len(self._data)

    def read(self, offset: int, length: int, /) -> bytes:
        """
        Return ``length`` bytes starting at ``offset``.

        Parameters
        ----------
        offset : int
            Zero-based start offset.
        length : int
            Number of bytes to return.

        Returns
        -------
        bytes
            The requested slice.
        """
        return bytes(self._data[offset:offset + length])


class MmapReader:
    """
    A :py:class:`Reader` backed by a memory-mapped file.

    Only the pages actually touched are faulted in, so reading a single member does not read the
    whole file. Call :py:meth:`close`, or use the reader (or its owning archive) as a context
    manager, to release the mapping.

    Parameters
    ----------
    path : str | :py:class:`~pathlib.Path`
        Path to the file.
    """
    def __init__(self, path: str | Path) -> None:
        self._file = Path(path).open('rb')  # noqa: SIM115
        try:
            self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        except (ValueError, OSError):
            self._file.close()
            raise

    def __enter__(self) -> Self:
        """
        Return the reader for use in a ``with`` block.

        Returns
        -------
        Self
            This reader.
        """
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        """Close the reader on leaving a ``with`` block."""
        self.close()

    @property
    def size(self) -> int:
        """Total number of bytes available."""
        return len(self._mmap)

    def read(self, offset: int, length: int, /) -> bytes:
        """
        Return ``length`` bytes starting at ``offset``.

        Parameters
        ----------
        offset : int
            Zero-based start offset.
        length : int
            Number of bytes to return.

        Returns
        -------
        bytes
            The requested slice.
        """
        return self._mmap[offset:offset + length]

    def close(self) -> None:
        """Release the memory map and the underlying file handle."""
        self._mmap.close()
        self._file.close()


def resolve_reader(
    source: str | Path | bytes | bytearray | memoryview | Reader,
) -> tuple[Reader, MmapReader | None]:
    """
    Turn a caller-supplied source into a :py:class:`Reader`.

    Parameters
    ----------
    source : str | :py:class:`~pathlib.Path` | bytes | bytearray | memoryview | Reader
        A filesystem path to open and map, an in-memory image, or a ready-made reader.

    Returns
    -------
    tuple[Reader, MmapReader | None]
        The resolved reader and the resource this call opened and now owns, or ``None`` when the
        caller supplied the bytes or reader and nothing needs closing.
    """
    match source:
        case str() | Path():
            reader = MmapReader(source)
            return reader, reader
        case bytes() | bytearray() | memoryview():
            return BytesReader(source), None
        case _:
            return source, None
