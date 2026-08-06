"""
Location and invocation of the ImageMagick helpers.

Nothing here runs at import time, so the rest of the package can be imported and every decoder
exercised without ImageMagick installed. A renderer only needs it when the requested output is
not already a PPM.

ImageMagick 7 replaced the ``convert`` and ``montage`` binaries with subcommands of ``magick``,
so both layouts are accepted.
"""
from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING
import logging
import subprocess as sp
import tempfile

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ('ImageMagickNotFoundError', 'convert', 'montage', 'resolve', 'write_image')

log = logging.getLogger(__name__)

_PPM_SUFFIX = '.ppm'


class ImageMagickNotFoundError(Exception):
    """Raised when neither the requested ImageMagick binary nor ``magick`` can be located."""


def resolve(tool: str, override: Path | None = None) -> tuple[str, ...]:
    """
    Build the argument prefix that invokes an ImageMagick tool.

    Parameters
    ----------
    tool : str
        Either ``'convert'`` or ``'montage'``.
    override : Path | None
        An explicit path that takes precedence over anything found on ``PATH``.

    Returns
    -------
    tuple[str, ...]
        The command and any subcommand needed to invoke the tool.

    Raises
    ------
    ImageMagickNotFoundError
        If the tool cannot be located.
    """
    if override is not None:
        if not override.is_file():
            msg = f'Specified path for `{tool}` does not exist: {override}.'
            raise ImageMagickNotFoundError(msg)
        return (str(override),)
    if (found := which(tool)) is not None:
        return (found,)
    if (magick := which('magick')) is not None:
        return (magick,) if tool == 'convert' else (magick, tool)
    msg = (f'Could not find `{tool}` or `magick`. Install ImageMagick, put it on PATH, or pass '
           f'`--{tool}-path`.')
    raise ImageMagickNotFoundError(msg)


def convert(args: Sequence[str], override: Path | None = None) -> None:
    """
    Run ImageMagick's ``convert``.

    Parameters
    ----------
    args : Sequence[str]
        Arguments following the command itself.
    override : Path | None
        An explicit path to the binary. A non-zero exit propagates as
        :py:class:`subprocess.CalledProcessError`.
    """
    command = [*resolve('convert', override), *args]
    log.debug('Running %s.', ' '.join(command))
    sp.run(command, check=True)


def montage(args: Sequence[str], override: Path | None = None) -> None:
    """
    Run ImageMagick's ``montage``.

    Parameters
    ----------
    args : Sequence[str]
        Arguments following the command itself.
    override : Path | None
        An explicit path to the binary. A non-zero exit propagates as
        :py:class:`subprocess.CalledProcessError`.
    """
    command = [*resolve('montage', override), *args]
    log.debug('Running %s.', ' '.join(command))
    sp.run(command, check=True)


def write_image(ppm: bytes,
                dest: Path,
                override: Path | None = None,
                extra_args: Iterable[str] = ()) -> None:
    """
    Write a PPM image to a destination, converting it when the destination is not a PPM.

    When ``dest`` already ends in ``.ppm`` and no extra arguments are given the bytes are written
    directly and ImageMagick is never invoked.

    Parameters
    ----------
    ppm : bytes
        A complete binary PPM image.
    dest : Path
        Where to write the final image. Its parent is created if missing.
    override : Path | None
        An explicit path to the ``convert`` binary.
    extra_args : Iterable[str]
        Extra arguments inserted between the input and output paths, such as a scale operation. A
        failed conversion propagates as :py:class:`subprocess.CalledProcessError`.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = list(extra_args)
    if dest.suffix.lower() == _PPM_SUFFIX and not args:
        dest.write_bytes(ppm)
        return
    with tempfile.NamedTemporaryFile(suffix=_PPM_SUFFIX, dir=dest.parent, delete=False) as handle:
        handle.write(ppm)
        temp = Path(handle.name)
    try:
        convert([str(temp), *args, str(dest)], override)
    finally:
        temp.unlink(missing_ok=True)
