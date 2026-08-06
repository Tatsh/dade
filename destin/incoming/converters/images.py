"""Image converters: PPM and Dreamcast PVR to PNG."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import logging
import subprocess as sp

from PIL import Image
from incoming_extractor.pvrpack import iter_pack_textures
from incoming_extractor.tools import find_spvr2png

from ._base import ConversionError

__all__ = ('ppm_to_png', 'pvr_pack_to_files', 'pvr_pack_to_png', 'spvr2png_converter')

log = logging.getLogger(__name__)


def pvr_pack_to_files(source: Path, dest_dir: Path) -> tuple[Path, ...]:
    """
    Unpack an Incoming Dreamcast ``*_T.PVR`` texture pack into individual ``.pvr`` files.

    This pack container is Dreamcast-specific. Files are written to a directory named after the pack
    stem inside *dest_dir*.

    Parameters
    ----------
    source : Path
        The source ``*_T.PVR`` pack file.
    dest_dir : Path
        The directory the per-pack directory is created in.

    Returns
    -------
    tuple[Path, ...]
        The written ``.pvr`` paths, in pack order.

    Raises
    ------
    ConversionError
        If the pack cannot be parsed.
    """
    try:
        textures = tuple(iter_pack_textures(source.read_bytes()))
    except ValueError as e:
        msg = f'Failed to parse pack `{source}`: {e}'
        raise ConversionError(msg) from e
    pack_dir = dest_dir / source.stem
    pack_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for texture in textures:
        name = f'{source.stem}_{texture.position:03d}_{texture.width}x{texture.height}.pvr'
        path = pack_dir / name
        path.write_bytes(texture.data)
        written.append(path)
    return tuple(written)


def ppm_to_png(source: Path, dest_dir: Path) -> Path:
    """
    Convert a NetPBM ``.ppm`` image to PNG.

    Parameters
    ----------
    source : Path
        The source ``.ppm`` file.
    dest_dir : Path
        The directory the PNG is written to.

    Returns
    -------
    Path
        The written PNG path.

    Raises
    ------
    ConversionError
        If the image cannot be read or written.
    """
    destination = dest_dir / f'{source.stem}.png'
    try:
        with Image.open(source) as image:
            image.save(destination, format='PNG')
    except OSError as e:
        msg = f'Failed to convert `{source}`: {e}'
        raise ConversionError(msg) from e
    return destination


def _run_spvr2png(source: Path, destination: Path) -> None:
    spvr2png = find_spvr2png()
    try:
        sp.run([str(spvr2png), '-s', str(source), '-d',
                str(destination)],
               check=True,
               capture_output=True)
    except sp.CalledProcessError as e:
        msg = f'spvr2png failed on `{source}`: {e.stderr.decode(errors="replace").strip()}'
        raise ConversionError(msg) from e


def spvr2png_converter(source: Path, dest_dir: Path) -> Path:
    """
    Convert a single standard Dreamcast ``.PVR`` image to PNG.

    Parameters
    ----------
    source : Path
        The source ``.PVR`` file.
    dest_dir : Path
        The directory the PNG is written to.

    Returns
    -------
    Path
        The written PNG path.
    """
    destination = dest_dir / f'{source.stem}.png'
    _run_spvr2png(source, destination)
    return destination


def pvr_pack_to_png(source: Path, dest_dir: Path) -> tuple[Path, ...]:
    """
    Unpack an Incoming ``*_T.PVR`` texture pack and convert every texture to PNG.

    The PNGs are written to a directory named after the pack stem inside *dest_dir*.

    Parameters
    ----------
    source : Path
        The source ``*_T.PVR`` pack file.
    dest_dir : Path
        The directory the per-pack PNG directory is created in.

    Returns
    -------
    tuple[Path, ...]
        The written PNG paths, in pack order.

    Raises
    ------
    ConversionError
        If the pack cannot be parsed or a texture fails to convert.
    """
    try:
        textures = tuple(iter_pack_textures(source.read_bytes()))
    except ValueError as e:
        msg = f'Failed to parse pack `{source}`: {e}'
        raise ConversionError(msg) from e
    pack_dir = dest_dir / source.stem
    pack_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as raw_dir:
        names = []
        for texture in textures:
            name = f'{source.stem}_{texture.position:03d}_{texture.width}x{texture.height}'
            (Path(raw_dir) / f'{name}.pvr').write_bytes(texture.data)
            names.append(name)
        _run_spvr2png(Path(raw_dir), pack_dir)
    return tuple(pack_dir / f'{name}.png' for name in names if (pack_dir / f'{name}.png').is_file())
