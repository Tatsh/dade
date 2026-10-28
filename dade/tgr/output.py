"""Writers shared by the cartridge and the disc: models with their textures, and audio."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import subprocess as sp

from PIL import Image

from .model import build_glb, orientations, textures
from .texture import FMT_CI, SIZ_4B, TextureKey, decode

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .model import Part

__all__ = ('ffmpeg', 'write_model', 'write_png', 'write_sky')

log = logging.getLogger(__name__)

_SKY_PALETTE = 0x20
_SKY_WIDTH = 32
_SKY_HEIGHT = 128


def write_png(path: Path,
              width: int,
              height: int,
              rgba: bytes,
              orientation: tuple[int, bool] = (0, False)) -> None:
    """
    Write an RGBA image as PNG, turned upright.

    Parameters
    ----------
    path : Path
        Destination.
    width : int
        Width in pixels.
    height : int
        Height in pixels.
    rgba : bytes
        The pixels.
    orientation : tuple[int, bool]
        Quarter turns clockwise, and whether to mirror left to right first.
    """
    quarter, mirrored = orientation
    image = Image.frombytes('RGBA', (width, height), rgba)
    if mirrored:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if quarter:
        image = image.rotate(-90 * quarter, expand=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def write_sky(path: Path, palette: bytes, texels: bytes) -> None:
    """
    Write the sky a car reflects as PNG, the sky at the top.

    The sky is a 32 by 128 strip of 4-bit texels. The game derives the coordinates from the normals
    of the body, a face pointing up reading the bottom of the strip, and the strip is therefore
    stored with the ground at the top.

    Parameters
    ----------
    path : Path
        Destination.
    palette : bytes
        The 16 colours.
    texels : bytes
        The texels.
    """
    key = TextureKey(_SKY_PALETTE, 0, FMT_CI, SIZ_4B, _SKY_WIDTH, _SKY_HEIGHT, 0)
    write_png(path, _SKY_WIDTH, _SKY_HEIGHT, decode(palette[:_SKY_PALETTE] + texels, key),
              (2, True))


def write_model(path: Path, memory: bytes | bytearray, parts: Sequence[Part]) -> int:
    """
    Write parts as a GLB, and each texture they sample beside it as an upright PNG.

    The textures go to a directory named after the GLB without its suffix.

    Parameters
    ----------
    path : Path
        Destination of the GLB.
    memory : bytes | bytearray
        The memory the parts were read from.
    parts : collections.abc.Sequence[Part]
        The parts.

    Returns
    -------
    int
        The number of textures written.
    """
    images = textures(memory, parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_glb(path.stem, parts, images))
    turns = orientations(parts)
    for key, rgba in images.items():
        write_png(
            path.with_suffix('') / f'{key.address:06x}.png', key.width, key.height, rgba,
            turns.get(key, (0, False)))
    log.debug('Wrote `%s` with %d textures.', path, len(images))
    return len(images)


def ffmpeg(executable: Path, source: Path, destination: Path, *arguments: str) -> None:
    """
    Convert a file with FFmpeg.

    Parameters
    ----------
    executable : Path
        The ``ffmpeg`` binary.
    source : Path
        The input.
    destination : Path
        The output, whose suffix picks the format.
    arguments : str
        Options placed before the input.

    Raises
    ------
    subprocess.CalledProcessError
        If FFmpeg exits with a non-zero status.
    """  # ruff: ignore[docstring-extraneous-exception]
    destination.parent.mkdir(parents=True, exist_ok=True)
    sp.run((str(executable), '-hide_banner', '-loglevel', 'error', '-y', *arguments, '-i',
            str(source), str(destination)),
           check=True)
