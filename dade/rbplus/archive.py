"""
The downloadable asset archives.

The game fetches its textures as three ZIP archives, one per device class: ``iPad``, ``iPad2x``,
and ``iPhone@2x``. Each includes a little over two thousand entries under a single top-level
directory titled after itself.

They are encrypted with ZipCrypto under a password the executable stores in the clear,
``kArchivePassword`` in ``DownloadResourceManager.m``. That is the whole protection. The entries
themselves are ordinary PNGs once the archive is opened. Some are Apple-optimised and some are not,
and each is therefore examined rather than assumed.

Beside the textures sits a ``list`` entry, a second encrypted ZIP under the same password with one
entry titled ``lists``, the archive's index, one asset path per line. The two names are
``kManifestArchiveSuffix`` and ``kManifestListSuffix`` in the same file.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import io
import logging
import zipfile

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('ARCHIVE_PASSWORD', 'MANIFEST_ENTRY', 'MANIFEST_INNER_ENTRY', 'ArchiveError',
           'archive_root', 'entry_names', 'open_archive', 'read_manifest')

ARCHIVE_PASSWORD = b'mt972'
"""The ZipCrypto password every asset archive uses.

:meta hide-value:
"""
MANIFEST_ENTRY = 'list'
"""The entry, under the archive root, storing the nested manifest archive.

:meta hide-value:
"""
MANIFEST_INNER_ENTRY = 'lists'
"""The single entry inside the manifest archive.

:meta hide-value:
"""

log = logging.getLogger(__name__)


class ArchiveError(Exception):
    """Raised when an asset archive cannot be opened or read."""


def open_archive(path: Path, password: bytes = ARCHIVE_PASSWORD) -> zipfile.ZipFile:
    """
    Open an asset archive with its password already set.

    Parameters
    ----------
    path : pathlib.Path
        The archive.
    password : bytes
        The ZipCrypto password, defaulting to :py:data:`ARCHIVE_PASSWORD`.

    Returns
    -------
    zipfile.ZipFile
        The opened archive. Close it, or use it as a context manager.

    Raises
    ------
    ArchiveError
        If the file is not a ZIP archive.
    """
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        msg = f'`{path.name}` is not a ZIP archive.'
        raise ArchiveError(msg) from e
    archive.setpassword(password)
    return archive


def entry_names(archive: zipfile.ZipFile) -> Iterator[zipfile.ZipInfo]:
    """
    Every file entry in an archive, directories omitted.

    Parameters
    ----------
    archive : zipfile.ZipFile
        The opened archive.

    Yields
    ------
    zipfile.ZipInfo
        One entry.
    """
    for info in archive.infolist():
        if not info.is_dir():
            yield info


def archive_root(archive: zipfile.ZipFile) -> str:
    """
    Name the single top-level directory an archive's entries sit under.

    Parameters
    ----------
    archive : zipfile.ZipFile
        The opened archive.

    Returns
    -------
    str
        The directory name, or the empty string when the entries are not under a common one.
    """
    names = [name for name in archive.namelist() if name]
    # An entry with no separator sits at the top level itself, and there is therefore no common
    # directory to strip even when every other entry shares one.
    if not names or any('/' not in name for name in names):
        return ''
    roots = {name.split('/', 1)[0] for name in names}
    return roots.pop() if len(roots) == 1 else ''


def read_manifest(archive: zipfile.ZipFile, password: bytes = ARCHIVE_PASSWORD) -> tuple[str, ...]:
    """
    Read an archive's own index of asset paths.

    Parameters
    ----------
    archive : zipfile.ZipFile
        The opened archive.
    password : bytes
        The password the nested archive uses, the same as the outer archive's.

    Returns
    -------
    tuple[str, ...]
        One asset path per line, blank lines dropped. Empty when the archive has no manifest.

    Raises
    ------
    ArchiveError
        If the manifest is present but does not open.
    """
    root = archive_root(archive)
    name = f'{root}/{MANIFEST_ENTRY}' if root else MANIFEST_ENTRY
    try:
        nested = archive.read(name)
    except KeyError:
        log.debug('No `%s` entry; the archive has no manifest.', name)
        return ()
    try:
        with zipfile.ZipFile(io.BytesIO(nested)) as inner:
            inner.setpassword(password)
            text = inner.read(MANIFEST_INNER_ENTRY).decode()
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile) as e:
        msg = f'`{name}` is not a readable manifest archive.'
        raise ArchiveError(msg) from e
    return tuple(line for line in text.split('\n') if line)
