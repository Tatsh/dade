"""Generic random-access byte-source readers shared by the game submodules."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
import mmap
import struct

if TYPE_CHECKING:
    from types import TracebackType
    from typing import BinaryIO

    from typing_extensions import Self

    from .typing import Endian

__all__ = ('BytesReader', 'MmapReader', 'Reader', 'copy_region', 'f32', 'i16', 'i32',
           'read_cstring', 'read_cstring_at', 'resolve_reader', 'u8', 'u16', 'u32')


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


def u8(data: bytes | bytearray | memoryview, offset: int = 0) -> int:
    """
    Read an unsigned 8-bit integer.

    Parameters
    ----------
    data : bytes | bytearray | memoryview
        Buffer to read from.
    offset : int
        Byte offset of the value.

    Returns
    -------
    int
        The value at ``offset``.
    """
    return data[offset]


def u16(data: bytes | bytearray | memoryview, offset: int = 0, *, endian: Endian = '<') -> int:
    """
    Read an unsigned 16-bit integer.

    Parameters
    ----------
    data : bytes | bytearray | memoryview
        Buffer to read from.
    offset : int
        Byte offset of the value.
    endian : Endian
        Byte order.

    Returns
    -------
    int
        The value at ``offset``.
    """
    return int(struct.unpack_from(f'{endian}H', data, offset)[0])


def u32(data: bytes | bytearray | memoryview, offset: int = 0, *, endian: Endian = '<') -> int:
    """
    Read an unsigned 32-bit integer.

    Parameters
    ----------
    data : bytes | bytearray | memoryview
        Buffer to read from.
    offset : int
        Byte offset of the value.
    endian : Endian
        Byte order.

    Returns
    -------
    int
        The value at ``offset``.
    """
    return int(struct.unpack_from(f'{endian}I', data, offset)[0])


def i16(data: bytes | bytearray | memoryview, offset: int = 0, *, endian: Endian = '<') -> int:
    """
    Read a signed 16-bit integer.

    Parameters
    ----------
    data : bytes | bytearray | memoryview
        Buffer to read from.
    offset : int
        Byte offset of the value.
    endian : Endian
        Byte order.

    Returns
    -------
    int
        The value at ``offset``.
    """
    return int(struct.unpack_from(f'{endian}h', data, offset)[0])


def i32(data: bytes | bytearray | memoryview, offset: int = 0, *, endian: Endian = '<') -> int:
    """
    Read a signed 32-bit integer.

    Parameters
    ----------
    data : bytes | bytearray | memoryview
        Buffer to read from.
    offset : int
        Byte offset of the value.
    endian : Endian
        Byte order.

    Returns
    -------
    int
        The value at ``offset``.
    """
    return int(struct.unpack_from(f'{endian}i', data, offset)[0])


def f32(data: bytes | bytearray | memoryview, offset: int = 0, *, endian: Endian = '<') -> float:
    """
    Read an IEEE 754 32-bit float.

    Parameters
    ----------
    data : bytes | bytearray | memoryview
        Buffer to read from.
    offset : int
        Byte offset of the value.
    endian : Endian
        Byte order.

    Returns
    -------
    float
        The value at ``offset``.
    """
    return float(struct.unpack_from(f'{endian}f', data, offset)[0])


def read_cstring(data: bytes | bytearray, offset: int = 0, *, encoding: str = 'latin-1') -> str:
    """
    Decode the NUL-terminated string starting at ``offset``.

    The string runs from ``offset`` to the next NUL byte; if there is no NUL byte, it runs to the
    end of ``data``.

    Parameters
    ----------
    data : bytes | bytearray
        Buffer to read from.
    offset : int
        Byte offset at which the string starts.
    encoding : str
        Codec used to decode the bytes.

    Returns
    -------
    str
        The decoded string.
    """
    end = data.find(b'\x00', offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode(encoding)


def read_cstring_at(data: bytes | bytearray,
                    offset: int = 0,
                    *,
                    encoding: str = 'latin-1') -> tuple[str, int]:
    """
    Decode a NUL-terminated string and report the offset just past its terminator.

    The string runs from ``offset`` to the next NUL byte; if there is no NUL byte, it runs to the
    end of ``data`` and the returned offset is ``len(data)``.

    Parameters
    ----------
    data : bytes | bytearray
        Buffer to read from.
    offset : int
        Byte offset at which the string starts.
    encoding : str
        Codec used to decode the bytes.

    Returns
    -------
    tuple[str, int]
        The decoded string and the offset just past the terminating NUL.
    """
    end = data.find(b'\x00', offset)
    if end < 0:
        return data[offset:].decode(encoding), len(data)
    return data[offset:end].decode(encoding), end + 1


def copy_region(src: BinaryIO,
                offset: int,
                size: int,
                dst: Path,
                *,
                chunk: int = 1 << 20,
                strict: bool = False) -> int:
    """
    Copy a byte range from an open binary file into a new file.

    Parameters
    ----------
    src : BinaryIO
        Source file object; it is sought to ``offset`` before copying begins.
    offset : int
        Absolute byte offset to start copying from.
    size : int
        Number of bytes to copy.
    dst : pathlib.Path
        Destination path, overwritten if it already exists.
    chunk : int
        Maximum number of bytes to read per iteration.
    strict : bool
        When ``True``, raise :py:exc:`EOFError` if the source ends before ``size`` bytes have been
        copied; when ``False``, stop early and return the number of bytes copied.

    Returns
    -------
    int
        The number of bytes written.

    Raises
    ------
    EOFError
        If ``strict`` is ``True`` and the source ends before ``size`` bytes are copied.
    """
    src.seek(offset)
    remaining = size
    written = 0
    with dst.open('wb') as out:
        while remaining:
            if not (data := src.read(min(remaining, chunk))):
                if strict:
                    msg = f'{dst}: short read'
                    raise EOFError(msg)
                break
            out.write(data)
            written += len(data)
            remaining -= len(data)
    return written
