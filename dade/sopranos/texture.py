"""
Decode ``.TEX2`` texture banks to PNG.

A bank begins with a ``0x64`` magic, a reserved word, an image count, and then one absolute offset
per image. Each image begins with a ``0x65`` magic and carries its own dimensions, pixel format,
pixel-data offset, palette offset, and source path.

Pixels are stored linearly, but paletted images use the PlayStation 2 CLUT ordering and every alpha
value is on the console's ``0..128`` scale.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
import logging
import struct

from PIL import Image

from dade.common.exceptions import InvalidFormatError
from dade.common.image import double_ps2_alpha, ps2_clut_swizzle_index

from .typing import PixelFormat, TextureInfo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ('BANK_MAGIC', 'IMAGE_MAGIC', 'PALETTE_ENTRIES', 'convert', 'convert_geometry', 'decode',
           'iter_geometry_textures', 'iter_textures')

log = logging.getLogger(__name__)

BANK_MAGIC = 0x64
"""First word of a ``.TEX2`` bank.

:meta hide-value:
"""
IMAGE_MAGIC = 0x65
"""First word of each image inside a bank.

:meta hide-value:
"""
PALETTE_ENTRIES = 256
"""Number of RGBA entries in a paletted image's CLUT.

:meta hide-value:
"""

_FORMAT_PALETTED = 2
_FORMAT_RGB = 4
_FORMAT_RGBA = 5
_RGB_BYTES = 3
_PIXEL_FORMATS: dict[int, PixelFormat] = {_FORMAT_PALETTED: 2, _FORMAT_RGB: 4, _FORMAT_RGBA: 5}
_HEADER_SIZE = 12
_IMAGE_HEADER_SIZE = 0x2C
_SGP_IMAGES_AT = 0x80
_SGP_IMAGES_END_AT = 0x0C
_EGP_IMAGES_START_AT = 0x4C
_PALETTE_BYTES = PALETTE_ENTRIES * 4
_CLUT_ORDER = tuple(ps2_clut_swizzle_index(i) for i in range(PALETTE_ENTRIES))
_ALPHA_TABLE = bytes(double_ps2_alpha(i) for i in range(256))


def iter_textures(data: bytes) -> Iterator[TextureInfo]:
    """
    Yield a description of every image in a ``.TEX2`` bank.

    Parameters
    ----------
    data : bytes
        The whole bank.

    Yields
    ------
    TextureInfo
        One entry per image, in the order the bank lists them.

    Raises
    ------
    InvalidFormatError
        If the bank magic is wrong or an image header is malformed.
    """
    if len(data) < _HEADER_SIZE:
        msg = 'Texture bank is too small.'
        raise InvalidFormatError(msg)
    magic, _reserved, count = struct.unpack_from('<3I', data)
    if magic != BANK_MAGIC:
        msg = f'Texture bank has magic 0x{magic:x}, expected 0x{BANK_MAGIC:x}.'
        raise InvalidFormatError(msg)
    if _HEADER_SIZE + count * 4 > len(data):
        msg = (f'Texture bank declares {count} image(s) but is only {len(data)} bytes; the offset '
               f'table is truncated.')
        raise InvalidFormatError(msg)
    for offset in struct.unpack_from(f'<{count}I', data, _HEADER_SIZE):
        if not offset or offset + _IMAGE_HEADER_SIZE > len(data):
            msg = f'Texture bank has an out-of-range image offset 0x{offset:x}.'
            raise InvalidFormatError(msg)
        yield _read_image(data, offset)[0]


def _read_image(data: bytes, offset: int) -> tuple[TextureInfo, int]:
    """
    Read one image record.

    Parameters
    ----------
    data : bytes
        The buffer holding the record.
    offset : int
        Byte offset of the record.

    Returns
    -------
    tuple[TextureInfo, int]
        The image description and the record's total length in bytes.

    Raises
    ------
    InvalidFormatError
        If the record's magic or pixel format is not recognised.
    """
    image_magic, total, name_offset, name_hash = struct.unpack_from('<4I', data, offset)
    if image_magic != IMAGE_MAGIC:
        msg = f'Image at 0x{offset:x} has magic 0x{image_magic:x}.'
        raise InvalidFormatError(msg)
    width, height = struct.unpack_from('<2H', data, offset + 0x14)
    stored = data[offset + 0x1A]
    if (pixel_format := _PIXEL_FORMATS.get(stored)) is None:
        msg = f'Image at 0x{offset:x} has unsupported pixel format {stored}.'
        raise InvalidFormatError(msg)
    data_offset, palette_offset = struct.unpack_from('<2I', data, offset + 0x24)
    name_at = offset + name_offset
    return TextureInfo(data[name_at:data.index(b'\0', name_at)].decode(), width, height,
                       pixel_format, offset + data_offset,
                       offset + palette_offset if palette_offset else 0, name_hash), total


def iter_geometry_textures(data: bytes) -> Iterator[TextureInfo]:
    """
    Yield the images embedded in a ``.SGP2`` or ``.EGP2`` geometry blob.

    Both kinds store a run of bare image records rather than a bank with an offset table. A skinned
    ``.SGP2`` blob puts them at ``0x80`` and records their end in the header word at ``0x0C``; an
    environment ``.EGP2`` blob leaves that word zero and instead points at the run from ``0x4C``.
    Either way the run ends at the first word that is not an image magic.

    Parameters
    ----------
    data : bytes
        The whole geometry blob.

    Yields
    ------
    TextureInfo
        One entry per embedded image.
    """
    if len(data) < _SGP_IMAGES_AT:
        return
    if end := struct.unpack_from('<I', data, _SGP_IMAGES_END_AT)[0]:
        offset, limit = _SGP_IMAGES_AT, min(end, len(data))
    else:
        offset, limit = struct.unpack_from('<I', data, _EGP_IMAGES_START_AT)[0], len(data)
    while offset + _IMAGE_HEADER_SIZE <= limit:
        if struct.unpack_from('<I', data, offset)[0] != IMAGE_MAGIC:
            return
        info, total = _read_image(data, offset)
        if not total:
            return
        yield info
        offset += total


def decode(data: bytes, texture: TextureInfo) -> Image.Image:
    """
    Decode one image from a ``.TEX2`` bank.

    Rows are stored bottom-up, following the ``.tga`` sources the cooker read, so the result is
    flipped vertically to put the origin back at the top left.

    Parameters
    ----------
    data : bytes
        The whole bank.
    texture : TextureInfo
        The image to decode, as produced by :py:func:`iter_textures`.

    Returns
    -------
    Image.Image
        The image in ``RGBA`` mode with alpha rescaled to ``0..255``.

    Raises
    ------
    InvalidFormatError
        If the image's pixel data or palette runs past the end of the bank.
    """  # noqa: DOC502
    return _decode_stored(data, texture).transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def _decode_stored(data: bytes, texture: TextureInfo) -> Image.Image:
    """
    Decode one image without correcting its row order.

    Parameters
    ----------
    data : bytes
        The whole bank.
    texture : TextureInfo
        The image to decode.

    Returns
    -------
    Image.Image
        The image in ``RGBA`` mode, still in the stored bottom-up row order.

    Raises
    ------
    InvalidFormatError
        If the image's pixel data or palette runs past the end of the bank.
    """
    size = (texture.width, texture.height)
    if texture.pixel_format in {_FORMAT_RGB, _FORMAT_RGBA}:
        depth = 3 if texture.pixel_format == _FORMAT_RGB else 4
        end = texture.data_offset + texture.width * texture.height * depth
        if end > len(data):
            msg = f'Pixel data for `{texture.name}` runs past the end of the bank.'
            raise InvalidFormatError(msg)
        pixels = data[texture.data_offset:end]
        if depth == _RGB_BYTES:
            return Image.frombytes('RGB', size, pixels).convert('RGBA')
        image = Image.frombytes('RGBA', size, pixels)
        image.putalpha(image.getchannel('A').point(_ALPHA_TABLE))
        return image
    end = texture.data_offset + texture.width * texture.height
    palette_end = texture.palette_offset + _PALETTE_BYTES
    if end > len(data) or palette_end > len(data):
        msg = f'Pixel data or palette for `{texture.name}` runs past the end of the bank.'
        raise InvalidFormatError(msg)
    raw = data[texture.palette_offset:palette_end]
    palette = bytearray(_PALETTE_BYTES)
    for i, slot in enumerate(_CLUT_ORDER):
        palette[i * 4:i * 4 + 4] = raw[slot * 4:slot * 4 + 4]
    indexed = Image.frombytes('P', size, data[texture.data_offset:end])
    indexed.putpalette(bytes(palette), rawmode='RGBA')
    image = indexed.convert('RGBA')
    image.putalpha(image.getchannel('A').point(_ALPHA_TABLE))
    return image


def convert(path: Path, output_dir: Path) -> tuple[Path, ...]:
    """
    Decode every image in a ``.TEX2`` file and write PNGs beside each other.

    Each PNG is named after the stem of the image's recorded source path.

    Parameters
    ----------
    path : Path
        The ``.TEX2`` file to read.
    output_dir : Path
        Directory to write into. It is created if missing.

    Returns
    -------
    tuple[Path, ...]
        The PNG files written.
    """
    return _write_all(path.read_bytes(), output_dir, banked=True)


def convert_geometry(path: Path, output_dir: Path) -> tuple[Path, ...]:
    """
    Decode every image embedded in a ``.SGP2`` or ``.EGP2`` geometry blob to PNG.

    Parameters
    ----------
    path : Path
        The geometry blob to read.
    output_dir : Path
        Directory to write into. It is created if missing.

    Returns
    -------
    tuple[Path, ...]
        The PNG files written.
    """
    return _write_all(path.read_bytes(), output_dir, banked=False)


def _write_all(data: bytes, output_dir: Path, *, banked: bool) -> tuple[Path, ...]:
    """
    Decode every image in *data* and write PNGs into *output_dir*.

    Parameters
    ----------
    data : bytes
        The bank or geometry blob.
    output_dir : Path
        Directory to write into. It is created if missing.
    banked : bool
        Read a ``.TEX2`` offset table when true, otherwise walk bare image records.

    Returns
    -------
    tuple[Path, ...]
        The PNG files written.
    """
    textures = tuple(iter_textures(data) if banked else iter_geometry_textures(data))
    if textures:
        output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    seen: dict[str, int] = {}
    for texture in textures:
        stem = PurePosixPath(texture.name).stem
        # Names repeat across a level's meshes, so later duplicates get a numeric suffix.
        count = seen.get(stem, 0)
        seen[stem] = count + 1
        destination = output_dir / (f'{stem}.png' if not count else f'{stem}_{count}.png')
        decode(data, texture).save(destination)
        written.append(destination)
    return tuple(written)
