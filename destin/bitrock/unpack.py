"""The :py:func:`unpack` entry point."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .archive import InstallBuilderFile
from .exceptions import MemberNotFoundError
from .typing import ExtractedFile

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .typing import PageCompression, Reader

__all__ = ('unpack',)

_EXECUTABLE_MAGIC_NUMBERS = frozenset({
    b'\x7fELF',  # ELF: Linux, Solaris (SPARC and Intel), the BSDs, IRIX, and others.
    b'\xfe\xed\xfa\xce',  # 32-bit Mach-O.
    b'\xfe\xed\xfa\xcf',  # 64-bit Mach-O.
    b'\xce\xfa\xed\xfe',  # 32-bit Mach-O, byte-swapped.
    b'\xcf\xfa\xed\xfe',  # 64-bit Mach-O, byte-swapped.
    b'\xca\xfe\xba\xbe',  # Universal (fat) binary.
    b'\xbe\xba\xfe\xca',  # Universal (fat) binary, byte-swapped.
})
"""Four-byte magic numbers: ELF, Mach-O, and macOS universal binaries."""
_EXECUTABLE_MAGIC_PREFIXES = frozenset({
    b'#!',  # Shebang scripts.
    b'\x01\xdf',  # 32-bit XCOFF: AIX and IBM i (OS/400).
    b'\x01\xf7',  # 64-bit XCOFF: AIX.
    b'\x02\x0b',  # PA-RISC 1.0 SOM: HP-UX.
    b'\x02\x10',  # PA-RISC 1.1 SOM: HP-UX.
    b'\x02\x14',  # PA-RISC 2.0 SOM: HP-UX.
})
"""Two-byte magic prefixes: shebang scripts and the XCOFF (AIX, OS/400) and SOM (HP-UX) formats."""


def _is_executable(contents: bytes) -> bool:
    """
    Decide whether a member should be marked executable.

    InstallBuilder does not store Unix permission bits in the cookfs index, so the executable bit
    is inferred from the contents. Recognised formats cover the Unix platforms InstallBuilder
    targets: ELF (including ``.so`` shared objects), Mach-O and ``.dylib`` libraries, XCOFF (AIX
    and OS/400), PA-RISC SOM (HP-UX), and files beginning with a shebang.

    Parameters
    ----------
    contents : bytes
        The member's bytes.

    Returns
    -------
    bool
        Whether the member looks executable.
    """
    return (contents[:4] in _EXECUTABLE_MAGIC_NUMBERS or contents[:2] in _EXECUTABLE_MAGIC_PREFIXES)


def unpack(installer: str | Path | bytes | bytearray | memoryview | Reader,
           output_dir: str | Path,
           paths: Iterable[str] | None = None,
           *,
           password: bytes | str | None = None,
           page_compression: PageCompression | None = None,
           dry_run: bool = False) -> Iterator[ExtractedFile]:
    """
    Extract members from an InstallBuilder installer.

    Parameters
    ----------
    installer : str | :py:class:`~pathlib.Path` | bytes | bytearray | memoryview | Reader
        The installer to read: a filesystem path, an in-memory image, or a
        :py:class:`~destin.bitrock.typing.Reader`.
    output_dir : str | :py:class:`~pathlib.Path`
        Directory to extract into. Created if it does not exist (unless ``dry_run`` is set).
    paths : Iterable[str] | None
        Specific member paths to extract, as returned by
        :py:attr:`destin.bitrock.archive.InstallBuilderFile.namelist`. When ``None`` every member is
        extracted.
    password : bytes | str | None
        Password for an encrypted installer.
    page_compression : PageCompression | None
        Override the auto-detected compression algorithm for encrypted pages. ``None`` auto-detects.
    dry_run : bool
        When ``True``, compute and return the results without creating directories or writing
        files.

    Yields
    ------
    Iterator[ExtractedFile]
        One entry per extracted member, in the order processed.

    Raises
    ------
    MemberNotFoundError
        If a requested member does not exist.
    """
    destination = Path(output_dir)
    with InstallBuilderFile(installer, password=password,
                            page_compression=page_compression) as archive:
        available = frozenset(archive.namelist)
        selected = archive.namelist if paths is None else tuple(paths)
        if missing := [path for path in selected if path not in available]:
            msg = f'Requested members not found: {", ".join(sorted(missing))}.'
            raise MemberNotFoundError(msg)
        yield from (_extract_one(archive, member, destination, dry_run=dry_run)
                    for member in selected)


def _extract_one(archive: InstallBuilderFile, member: str, destination: Path, *,
                 dry_run: bool) -> ExtractedFile:
    """
    Extract a single member, honouring ``dry_run``.

    Parameters
    ----------
    archive : InstallBuilderFile
        The open archive.
    member : str
        Logical member path to extract.
    destination : :py:class:`~pathlib.Path`
        Root directory to write into.
    dry_run : bool
        When ``True``, no filesystem changes are made.

    Returns
    -------
    ExtractedFile
        A record describing what was (or would be) written.
    """
    contents = archive.read(member)
    executable = _is_executable(contents)
    if not dry_run:
        target = destination / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        target.chmod(0o755 if executable else 0o644)
    return ExtractedFile(path=member,
                         size=len(contents),
                         executable=executable,
                         written=not dry_run)
