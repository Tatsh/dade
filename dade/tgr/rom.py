"""
The releases of the Top Gear Rally cartridge, its compressed assets, and the tables of the program.

A compressed asset is self-describing. An 8-byte header gives the length of the asset in the
cartridge and the length of its data once inflated, and zlib streams follow, each after its length
and padded to an even length. Assets sit after the loaded image of the program, and every even
offset there is tried. A candidate counts only when its whole chain inflates to the length its
header gives.
"""
from __future__ import annotations

from typing import NamedTuple
import hashlib
import re
import zlib

from dade.common.exceptions import InvalidFormatError

__all__ = ('RELEASES', 'Asset', 'Release', 'decompress', 'identify', 'normalize', 'read_name',
           'scan')

_HEADER_SIZE = 8
_CHUNK_HEADER_SIZE = 4
_NAME = b'TOP GEAR RALLY'
_NAME_OFFSET = 0x20
_GAME_CODE_OFFSET = 0x3B
_RAM_BASE = 0x80200000
_ROM_BASE = 0x1000
_ZLIB_HEADER = re.compile(rb'\x78[\x01\x5e\x9c\xda]')
_NAME_LIMIT = 64


class Release(NamedTuple):
    """One release of the cartridge."""

    region: str
    """Short name, ``us``, ``jp``, or ``eu``."""
    sha1: str
    """SHA-1 of the unmodified big-endian image."""
    asset_start: int
    """Offset of the first asset, where the loaded image of the program ends."""
    car_catalog: int
    """Offset of the table of the 13 cars, 0x60 bytes each."""
    track_table: int
    """Offset of the table of the tracks, 0x17C bytes each."""


RELEASES = {
    'NGRE': Release('us', 'bfc51f086ebdb78904dc24ad0c3a2d946e26d022', 0xAD400, 0x8BE0C, 0x71854),
    'NTRJ': Release('jp', 'e0415b87c5a5b69ac581e79137406bdaa79b354a', 0xADB30, 0x8DAEC, 0x732F4),
    'NTRP': Release('eu', '9fae5d98fe3464f00d59034690df90118646eb95', 0xAF0F0, 0x8E0BC, 0x73834)
}
"""Each release by the game code of its header.

:meta hide-value:
"""


class Asset(NamedTuple):
    """A compressed asset of the cartridge."""

    offset: int
    """Offset of the asset in the cartridge."""
    end: int
    """Offset of the byte after the asset, before its padding."""
    data: bytes
    """The inflated data."""


def normalize(image: bytes) -> bytes:
    """
    Put a cartridge image in big-endian (``.z64``) order.

    Parameters
    ----------
    image : bytes
        An image in ``.z64``, ``.v64``, or ``.n64`` order.

    Returns
    -------
    bytes
        The image in ``.z64`` order.

    Raises
    ------
    InvalidFormatError
        If the first word is not the magic of a cartridge in any order.
    """
    match image[:4]:
        case b'\x80\x37\x12\x40':
            return image
        case b'\x37\x80\x40\x12':
            swapped = bytearray(image)
            swapped[0::2], swapped[1::2] = image[1::2], image[0::2]
            return bytes(swapped)
        case b'\x40\x12\x37\x80':
            swapped = bytearray(image)
            for index in range(4):
                swapped[index::4] = image[3 - index::4]
            return bytes(swapped)
        case _:
            msg = 'Not a Nintendo 64 cartridge image.'
            raise InvalidFormatError(msg)


def identify(image: bytes) -> Release:
    """
    Identify the release of a big-endian image.

    Parameters
    ----------
    image : bytes
        The image, from :py:func:`normalize`.

    Returns
    -------
    Release
        The release.

    Raises
    ------
    InvalidFormatError
        If the image is not an unmodified release of Top Gear Rally.
    """
    if image[_NAME_OFFSET:_NAME_OFFSET + len(_NAME)] != _NAME:
        msg = 'Not a Top Gear Rally cartridge.'
        raise InvalidFormatError(msg)
    code = image[_GAME_CODE_OFFSET:_GAME_CODE_OFFSET + 4].decode('latin-1')
    if (release := RELEASES.get(code)) is None:
        msg = f'Unknown game code `{code}`.'
        raise InvalidFormatError(msg)
    digest = hashlib.sha1(image, usedforsecurity=False).hexdigest()
    if digest != release.sha1:
        msg = f'SHA-1 {digest} does not match the {release.region} release ({release.sha1}).'
        raise InvalidFormatError(msg)
    return release


def decompress(image: bytes, offset: int) -> Asset:
    """
    Inflate the compressed asset at an offset.

    Parameters
    ----------
    image : bytes
        The cartridge.
    offset : int
        Offset of the asset.

    Returns
    -------
    Asset
        The asset.

    Raises
    ------
    InvalidFormatError
        If the chain of zlib streams is malformed or inflates to the wrong length.
    """
    total = int.from_bytes(image[offset:offset + 4], 'big')
    size = int.from_bytes(image[offset + 4:offset + 8], 'big')
    end = offset + total
    if total < _HEADER_SIZE + _CHUNK_HEADER_SIZE or end > len(image) or size == 0:
        msg = f'No asset at {offset:#x}.'
        raise InvalidFormatError(msg)
    out = bytearray()
    position = offset + _HEADER_SIZE
    while position < end:
        length = int.from_bytes(image[position:position + 4], 'big')
        position += _CHUNK_HEADER_SIZE
        stream = zlib.decompressobj()
        try:
            out += stream.decompress(image[position:position + length])
        except zlib.error as e:
            msg = f'A chunk of the asset at {offset:#x} is malformed.'
            raise InvalidFormatError(msg) from e
        if length == 0 or not stream.eof or stream.unused_data:
            msg = f'A chunk of the asset at {offset:#x} is malformed.'
            raise InvalidFormatError(msg)
        position += length + (length & 1)
    if len(out) != size:
        msg = f'The asset at {offset:#x} inflates to {len(out)} bytes, not {size}.'
        raise InvalidFormatError(msg)
    return Asset(offset, end, bytes(out))


def scan(image: bytes, start: int) -> list[Asset]:
    """
    Find every compressed asset after an offset.

    Parameters
    ----------
    image : bytes
        The cartridge.
    start : int
        Offset of the asset area.

    Returns
    -------
    list[Asset]
        The assets in cartridge order.
    """
    assets: list[Asset] = []
    for match in _ZLIB_HEADER.finditer(image, start + _HEADER_SIZE + _CHUNK_HEADER_SIZE):
        offset = match.start() - _HEADER_SIZE - _CHUNK_HEADER_SIZE
        if offset % 2 or (assets and offset < assets[-1].end):
            continue
        try:
            assets.append(decompress(image, offset))
        except InvalidFormatError:
            continue
    return assets


def read_name(image: bytes, address: int) -> str:
    """
    Read a string of the program by its address.

    Parameters
    ----------
    image : bytes
        The cartridge.
    address : int
        The address of the string in memory.

    Returns
    -------
    str
        The string.
    """
    offset = address - _RAM_BASE + _ROM_BASE
    return image[offset:offset + _NAME_LIMIT].split(b'\0', 1)[0].decode('latin-1')
