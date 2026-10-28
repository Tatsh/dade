"""Extraction of every asset of a Top Gear Rally cartridge."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import re

from .model import (
    is_car,
    is_part_model,
    is_track,
    paint_car,
    read_car,
    read_part_model,
    read_track,
    stream_track_textures,
)
from .output import ffmpeg, write_model, write_png, write_sky
from .rom import identify, normalize, read_name, scan
from .texture import FMT_I, FMT_IA, FMT_RGBA, SIZ_4B, SIZ_16B, TextureKey, decode

if TYPE_CHECKING:
    from pathlib import Path

    from .model import Part
    from .rom import Asset, Release

__all__ = ('MENU_IMAGES', 'extract_rom')

log = logging.getLogger(__name__)

MENU_IMAGES = {
    0x1C07C0: ('menu-background', FMT_I, SIZ_4B, 320, 240),
    0x0DADE0: ('menu-title', FMT_IA, SIZ_16B, 280, 34),
    0x1C77A0: ('menu-arrow-left', FMT_RGBA, SIZ_16B, 24, 24),
    0x1C79B0: ('menu-arrow-right', FMT_RGBA, SIZ_16B, 24, 24)
}
"""Images of the menus in the North American release, by cartridge offset.

:meta hide-value:
"""
_XM_MAGIC = b'Extended Module: '
_XM_NAME = slice(17, 37)
_CAR_STRIDE = 0x60
_CAR_COUNT = 13
_TRACK_STRIDE = 0x17C
_TRACKS = (0, 1, 2, 3, 4, 10)
_SKY_HEADER = 0x20
_UNSAFE = re.compile(r'[^0-9A-Za-z]+')


def _slug(name: str) -> str:
    return _UNSAFE.sub('-', name).strip('-').lower()


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], 'big')


def _names(image: bytes, release: Release) -> dict[int, tuple[str, str]]:
    names = {}
    for index in range(_CAR_COUNT):
        at = release.car_catalog + index * _CAR_STRIDE
        names[_u32(image, at + 0x14)] = ('cars', _slug(read_name(image, _u32(image, at))))
    for index in _TRACKS:
        at = release.track_table + index * _TRACK_STRIDE
        name = _slug(read_name(image, _u32(image, at)))
        names[_u32(image, at + 0x14)] = ('tracks', name)
        for field, time in ((0x1C, 'day'), (0x24, 'night')):
            names.setdefault(_u32(image, at + field) + _SKY_HEADER, ('sky', f'{name}-{time}'))
    return names


def _write_track(image: bytes, asset: Asset, path: Path) -> None:
    memory = stream_track_textures(asset.data, image[asset.end:])
    parts = read_track(memory)
    sky: list[Part] = [part for part in parts if part.name == 'sky']
    write_model(path, memory, [part for part in parts if part.name != 'sky'])
    if sky:
        write_model(path.with_name(f'{path.stem}-sky.glb'), memory, sky)


def _write_music(asset: Asset, directory: Path, ffmpeg_path: Path | None) -> None:
    name = _slug(asset.data[_XM_NAME].decode('latin-1'))
    path = directory / f'{asset.offset:06x}{"-" + name if name else ""}.xm'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(asset.data)
    if ffmpeg_path is not None:
        ffmpeg(ffmpeg_path, path, path.with_suffix('.wav'))


def extract_rom(source: Path, out: Path, ffmpeg_path: Path | None = None) -> dict[str, int]:
    """
    Convert every asset of a cartridge.

    Cars, tracks, and the models of the menus become GLB with their textures beside them as PNG,
    the music is written as the FastTracker 2 modules it ships as and rendered to WAV, the images
    of the menus become PNG, and every other asset is written inflated.

    Parameters
    ----------
    source : Path
        The cartridge image, in any byte order.
    out : Path
        Output directory. A directory for the release is made in it.
    ffmpeg_path : Path | None
        The ``ffmpeg`` binary to render the music with, or :py:obj:`None` to skip rendering.

    Returns
    -------
    dict[str, int]
        The number of files of each kind written.

    Raises
    ------
    InvalidFormatError
        If the source is not an unmodified cartridge image of Top Gear Rally.
    """  # ruff: ignore[docstring-extraneous-exception]
    image = normalize(source.read_bytes())
    release = identify(image)
    root = out / release.region
    names = _names(image, release)
    counts = dict.fromkeys(('cars', 'tracks', 'models', 'music', 'images', 'other'), 0)
    log.info('Scanning the %s release.', release.region)
    for asset in scan(image, release.asset_start):
        kind, name = names.get(asset.offset, ('', f'{asset.offset:06x}'))
        if kind == 'cars' or (not kind and is_car(asset.data)):
            memory = paint_car(asset.data)
            write_model(root / 'cars' / f'{name}.glb', memory, read_car(memory))
            counts['cars'] += 1
        elif kind == 'tracks' or (not kind and is_track(asset.data)):
            _write_track(image, asset, root / 'tracks' / f'{name}.glb')
            counts['tracks'] += 1
        elif kind == 'sky':
            write_sky(root / 'sky' / f'{name}.png', image[asset.offset - _SKY_HEADER:asset.offset],
                      asset.data)
            counts['images'] += 1
        elif asset.data.startswith(_XM_MAGIC):
            _write_music(asset, root / 'music', ffmpeg_path)
            counts['music'] += 1
        elif is_part_model(asset.data) and (parts := read_part_model(asset.data)):
            write_model(root / 'models' / f'{name}.glb', asset.data, parts)
            counts['models'] += 1
        elif release.region == 'us' and asset.offset in MENU_IMAGES:
            label, fmt, siz, width, height = MENU_IMAGES[asset.offset]
            rgba = decode(asset.data,
                          TextureKey(0, -1, fmt, siz, width, height, 0),
                          swapped_rows=False)
            write_png(root / 'images' / f'{label}.png', width, height, rgba)
            counts['images'] += 1
        else:
            path = root / 'other' / f'{name}.bin'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(asset.data)
            counts['other'] += 1
    log.info('Wrote %s.', ', '.join(f'{v} {k}' for k, v in counts.items()))
    return counts
