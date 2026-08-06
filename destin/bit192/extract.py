"""
Full Tone Sphere asset extraction.

Tone Sphere (Android) ships its data in a few containers across the APK and its OBB expansion. This
module resolves any of an ``.xapk`` bundle, a bare ``.apk``, or an ``.apk`` plus its ``.obb``, then:

- unpacks every ``.dz`` (Derbh) and ``.cz`` (XOR-wrapped Derbh) archive,
- decodes every IwResGroup ``.group.bin`` in place into a sibling folder of open formats, and
- wraps every headerless ``.raw`` PCM file as a sibling ``.wav``.

The OBB holds the full-size archives; the APK ships same-named stubs, so OBB entries override APK
ones. Derbh/IwResGroup handling comes from :mod:`marmalade`; the ``.cz`` layer and the ``.raw`` rate
are Tone-Sphere specifics provided by :mod:`bit192`.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import io
import logging
import zipfile

from destin.marmalade.convert import decode_group_to_dir
from destin.marmalade.derbh import unpack_to_dir
from destin.marmalade.resgroup import is_resgroup

from .audio import wrap_raw_file
from .cz import decrypt

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('extract',)

log = logging.getLogger(__name__)

_GROUP_SUFFIX = '.group.bin'
_ARCHIVE_SUFFIXES = ('.dz', '.cz')
_IMAGE_MAGICS = {b'\x89PNG': '.png', b'GIF8': '.gif'}


def _open_inputs(inputs: Sequence[str | Path]) -> tuple[zipfile.ZipFile, zipfile.ZipFile | None]:
    """
    Resolve the inputs to an APK zip and an optional OBB zip.

    Parameters
    ----------
    inputs : Sequence[str | pathlib.Path]
        An ``.xapk``/``.apkm``, or an ``.apk``, optionally with its ``.obb``.

    Returns
    -------
    tuple[zipfile.ZipFile, zipfile.ZipFile | None]
        The APK zip and the OBB zip (``None`` when only an APK was given).

    Raises
    ------
    ValueError
        If an input has an unrecognised extension or no APK is found.
    """
    apk: zipfile.ZipFile | None = None
    obb: zipfile.ZipFile | None = None
    for raw in inputs:
        path = Path(raw)
        low = path.suffix.lower()
        if low in {'.xapk', '.apkm'}:
            bundle = zipfile.ZipFile(path)
            apk_name = next((n for n in bundle.namelist() if n.lower().endswith('.apk')
                             and '/' not in n.strip('/') and 'config.' not in n.lower()), None)
            apk_name = apk_name or next(
                (n for n in bundle.namelist() if n.lower().endswith('.apk')), None)
            obb_name = next((n for n in bundle.namelist() if n.lower().endswith('.obb')), None)
            if apk_name:
                apk = zipfile.ZipFile(io.BytesIO(bundle.read(apk_name)))
            if obb_name:
                obb = zipfile.ZipFile(io.BytesIO(bundle.read(obb_name)))
        elif low == '.apk':
            apk = zipfile.ZipFile(path)
        elif low == '.obb':
            obb = zipfile.ZipFile(path)
        else:
            msg = f'Unrecognised input {path} (need .xapk, .apk or .obb).'
            raise ValueError(msg)
    if apk is None:
        msg = 'No APK was found in the given input(s).'
        raise ValueError(msg)
    return apk, obb


def _gather_archives(apk: zipfile.ZipFile,
                     obb: zipfile.ZipFile | None) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """
    Collect data archives and standalone groups from the APK assets and the OBB.

    Parameters
    ----------
    apk : zipfile.ZipFile
        The APK zip.
    obb : zipfile.ZipFile | None
        The OBB zip, if present.

    Returns
    -------
    tuple[dict[str, bytes], dict[str, bytes]]
        ``archives`` (basename to bytes for ``.dz``/``.cz``) and ``groups`` (basename to bytes for
        standalone ``.group.bin`` in the APK assets).
    """
    archives: dict[str, bytes] = {}
    groups: dict[str, bytes] = {}
    for n in apk.namelist():
        base = Path(n).name
        low = base.lower()
        if n.startswith('assets/') and low.endswith(_ARCHIVE_SUFFIXES):
            archives[base] = apk.read(n)
        elif n.startswith('assets/') and low.endswith(_GROUP_SUFFIX):
            groups[base] = apk.read(n)
    apk_only = set(archives)
    if obb is not None:
        obb_bases = set()
        for n in obb.namelist():
            base = Path(n).name
            if base.lower().endswith(_ARCHIVE_SUFFIXES):
                archives[base] = obb.read(n)
                obb_bases.add(base)
        log.debug('Gathered %d archive(s): %d from the OBB, %d APK-only.', len(archives),
                  len(obb_bases), len(apk_only - obb_bases))
    else:
        log.warning('No OBB given; APK archives are stubs (no full audio/art).')
    return archives, groups


def _unpack_archive(base: str, data: bytes, outdir: Path) -> list[Path]:
    """
    Unpack one ``.dz``/``.cz`` archive and post-process its tree.

    Parameters
    ----------
    base : str
        Archive file name (used for the output subfolder and to detect ``.cz``).
    data : bytes
        Archive bytes (decrypted here if it is a ``.cz``).
    outdir : pathlib.Path
        Extraction root.

    Returns
    -------
    list[pathlib.Path]
        Paths of any ``.group.bin`` files produced by this archive.
    """
    if base.lower().endswith('.cz'):
        data = decrypt(data)
        if data[:4] != b'DTRZ':
            log.warning('%s did not decrypt to a Derbh archive; skipping.', base)
            return []
    dest = outdir / base.rsplit('.', 1)[0]
    count = unpack_to_dir(data, dest)
    log.debug('Unpacked %s into %s (%d files).', base, dest, count)
    group_paths: list[Path] = []
    for fp in dest.rglob('*'):
        low = fp.name.lower()
        if low.endswith(_GROUP_SUFFIX):
            group_paths.append(fp)
        elif low.endswith('.raw'):
            wrap_raw_file(fp)
    return group_paths


def _decode_group_file(fp: Path, *, keep_group_bin: bool) -> None:
    """
    Decode one on-disk ``.group.bin`` into a sibling folder.

    Parameters
    ----------
    fp : pathlib.Path
        Path to the ``.group.bin`` file.
    keep_group_bin : bool
        If ``False``, delete the source ``.group.bin`` after decoding.
    """
    data = fp.read_bytes()
    if not is_resgroup(data):
        ext = _IMAGE_MAGICS.get(data[:4])
        if ext is not None:  # a plain image that merely carries a .group.bin name
            fp.replace(Path(str(fp)[:-len(_GROUP_SUFFIX)] + ext))
        return
    decode_group_to_dir(data, Path(str(fp)[:-len(_GROUP_SUFFIX)]))
    if not keep_group_bin:
        fp.unlink()


def extract(inputs: Sequence[str | Path],
            outdir: str | Path,
            *,
            keep_group_bin: bool = False) -> Path:
    """
    Extract and decode all Tone Sphere assets from *inputs* into *outdir*.

    Parameters
    ----------
    inputs : Sequence[str | pathlib.Path]
        An ``.xapk``/``.apkm``, or an ``.apk``, optionally with its ``.obb``.
    outdir : str or pathlib.Path
        Output directory (created if absent).
    keep_group_bin : bool
        Keep the raw ``.group.bin`` files alongside their decoded folders.

    Returns
    -------
    pathlib.Path
        The output directory.
    """
    root = Path(outdir)
    root.mkdir(parents=True, exist_ok=True)
    apk, obb = _open_inputs(inputs)
    archives, groups = _gather_archives(apk, obb)
    group_paths: list[Path] = []
    for base, data in sorted(archives.items()):
        group_paths.extend(_unpack_archive(base, data, root))
    for name, data in groups.items():
        stem = name[:-len(_GROUP_SUFFIX)] if name.lower().endswith(_GROUP_SUFFIX) else name
        decode_group_to_dir(data, root / stem)
    for fp in group_paths:
        _decode_group_file(fp, keep_group_bin=keep_group_bin)
    log.debug('Extraction complete: %s.', root)
    return root
