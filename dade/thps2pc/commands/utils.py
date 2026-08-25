"""Shared helpers for the ``dade thps2pc`` commands."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import subprocess as sp

import bascom
import click

from dade.thps2pc.imagemagick import ImageMagickNotFoundError, montage, write_image
from dade.thps2pc.psx import Scene

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

__all__ = ('canvas_options', 'convert_path_option', 'debug_option', 'read_scene', 'run_montage',
           'save_image')

_IMAGE_ERRORS = (ImageMagickNotFoundError, OSError, sp.CalledProcessError)

debug_option = bascom.debug_option({'dade.common': {}, 'dade.thps2pc': {}})
"""Attach ``-d/--debug`` to a command and route it through :py:func:`bascom.setup_logging`.

:meta hide-value:
"""


def convert_path_option(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Attach ``--convert-path`` to a command that may shell out to ImageMagick.

    Parameters
    ----------
    func : Callable[..., Any]
        The Click callback to decorate.

    Returns
    -------
    Callable[..., Any]
        A new Click callback that adds ``--convert-path``.
    """
    return click.option('--convert-path',
                        type=click.Path(exists=True, dir_okay=False, path_type=Path),
                        help='Path to the ImageMagick convert binary.')(func)


def canvas_options(width: int, height: int, padding: int) -> Callable[..., Any]:
    """
    Build a decorator adding the canvas geometry options with the given defaults.

    Parameters
    ----------
    width : int
        Default canvas width in pixels.
    height : int
        Default canvas height in pixels.
    padding : int
        Default margin in pixels.

    Returns
    -------
    Callable[..., Any]
        A decorator that adds ``--width``, ``--height``, and ``--padding``.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func = click.option('--padding',
                            default=padding,
                            show_default=True,
                            help='Margin in pixels to leave on every side.')(func)
        func = click.option('--height',
                            default=height,
                            show_default=True,
                            help='Canvas height in pixels.')(func)
        return click.option('--width',
                            default=width,
                            show_default=True,
                            help='Canvas width in pixels.')(func)

    return decorator


def save_image(ppm: bytes,
               dest: Path,
               convert_path: Path | None = None,
               extra_args: Iterable[str] = ()) -> None:
    """
    Write an image, reporting a conversion failure as a Click abort.

    Parameters
    ----------
    ppm : bytes
        A complete binary PPM image.
    dest : Path
        Where to write the final image.
    convert_path : Path | None
        An explicit path to the ImageMagick ``convert`` binary.
    extra_args : Iterable[str]
        Extra arguments inserted between the input and output paths.

    Raises
    ------
    click.Abort
        If ImageMagick is missing or the conversion fails.
    """
    try:
        write_image(ppm, dest, convert_path, extra_args)
    except _IMAGE_ERRORS as e:
        click.echo(f'Could not write {dest}: {e}', err=True)
        raise click.Abort from e


def run_montage(args: Sequence[str], dest: Path, montage_path: Path | None = None) -> None:
    """
    Build a contact sheet, reporting a failure as a Click abort.

    Parameters
    ----------
    args : Sequence[str]
        Arguments passed to ``montage``.
    dest : Path
        The sheet being built, used in the error message.
    montage_path : Path | None
        An explicit path to the ImageMagick ``montage`` binary.

    Raises
    ------
    click.Abort
        If ImageMagick is missing or the montage fails.
    """
    try:
        montage(args, montage_path)
    except _IMAGE_ERRORS as e:
        click.echo(f'Could not build {dest}: {e}', err=True)
        raise click.Abort from e


def read_scene(path: Path) -> Scene:
    """
    Read and parse a ``.PSX`` scene, reporting a parse failure as a Click abort.

    Parameters
    ----------
    path : Path
        The scene file to read.

    Returns
    -------
    Scene
        The parsed scene.

    Raises
    ------
    click.Abort
        If the file cannot be parsed as a scene.
    """
    try:
        return Scene.parse(path.read_bytes())
    except ValueError as e:
        click.echo(f'{path}: {e}', err=True)
        raise click.Abort from e
