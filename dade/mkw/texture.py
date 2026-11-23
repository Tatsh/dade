"""Decode Switch 2 BNTX textures used by Mario Kart World."""
from __future__ import annotations

from io import BytesIO
import math
import struct

from PIL import Image
import numpy as np
import texture2ddecoder

__all__ = ('decode_texture', 'texture_count', 'texture_name')

# Swizzle and native tiling are adapted from MIT-licensed ns2-assets by dougchansan.
_SWIZZLE = (0x12100200, 0x13110301, 0x16140604, 0x17150705, 0x1A180A08, 0x1B190B09, 0x1E1C0E0C,
            0x1F1D0F0D)
_ASTC = ((4, 4), (5, 4), (5, 5), (6, 5), (6, 6), (8, 5), (8, 6), (8, 8), (10, 5), (10, 6), (10, 8),
         (10, 10), (12, 10), (12, 12))
_ASTC_FIRST = 0x2D
_ASTC_LAST = 0x3A
_BNTX_HEADER_SIZE = 0x200
_MAX_DIMENSION = 16384
_MAX_BLOCK_HEIGHT_LOG2 = 5
_R8 = 0x02
_RG8 = 0x09
_R16 = 0x0A
_RG16 = 0x12
_RGBA16 = 0x15
_RGBA32 = 0x19
_RGBA8 = 0x0B
_BGRA8 = 0x0C
_DECODERS = {
    0x1A: texture2ddecoder.decode_bc1,
    0x1C: texture2ddecoder.decode_bc3,
    0x1D: texture2ddecoder.decode_bc4,
    0x1E: texture2ddecoder.decode_bc5,
    0x1F: texture2ddecoder.decode_bc6,
    0x20: texture2ddecoder.decode_bc7
}


def _swizzle_offset(x: int, y: int) -> int:
    position = (y & 7) * 64 + (x & 63)
    index = position >> 4
    offset = ((_SWIZZLE[index // 4] >> ((index % 4) * 8)) & 255) * 16 + (position & 15)
    difference = ((offset >> 5) ^ (offset >> 6)) & 1
    return offset ^ (difference << 5) ^ (difference << 6)


def _deswizzle(raw: bytes, row_bytes: int, rows: int, block_height: int) -> bytes:
    output = bytearray(row_bytes * rows)
    gob_columns = math.ceil(row_bytes / 64)
    for y in range(rows):
        for x in range(0, row_bytes, 16):
            gob_row = y // (8 * block_height)
            gob_column = x // 64
            gob_within_block = (y // 8) % block_height
            gob = ((gob_row * gob_columns + gob_column) * block_height + gob_within_block) * 512
            offset = gob + _swizzle_offset(x, y)
            width = min(16, row_bytes - x)
            if offset + width > len(raw):
                message = 'BNTX image data is truncated.'
                raise ValueError(message)
            output[y * row_bytes + x:y * row_bytes + x + width] = raw[offset:offset + width]
    return bytes(output)


def texture_count(data: bytes) -> int:
    """
    Read the number of textures in a BNTX archive.

    Parameters
    ----------
    data : bytes
        Decompressed BNTX file.

    Returns
    -------
    int
        Number of textures.

    Raises
    ------
    ValueError
        The input is not a BNTX file.
    """
    if data[:4] != b'BNTX' or len(data) < _BNTX_HEADER_SIZE:
        message = 'Invalid BNTX file.'
        raise ValueError(message)
    return int(struct.unpack_from('<I', data, 0x24)[0])


def texture_name(data: bytes, index: int) -> str:
    """
    Read the indexed BNTX texture name.

    Parameters
    ----------
    data : bytes
        Decompressed BNTX file.
    index : int
        Texture index.

    Returns
    -------
    str
        Texture name.
    """
    texture = _texture_offset(data, index)
    pointer = struct.unpack_from('<Q', data, texture + 0x60)[0]
    length = struct.unpack_from('<H', data, pointer)[0]
    return data[pointer + 2:pointer + 2 + length].decode('utf-8', 'replace')


def _texture_offset(data: bytes, index: int) -> int:
    if not 0 <= index < texture_count(data):
        message = 'Invalid BNTX texture index.'
        raise ValueError(message)
    table = struct.unpack_from('<Q', data, 0x28)[0]
    if table + 8 * (index + 1) > len(data):
        message = 'Invalid BNTX texture table.'
        raise ValueError(message)
    texture = int(struct.unpack_from('<Q', data, table + 8 * index)[0])
    if data[texture:texture + 4] != b'BRTI':
        message = 'BNTX has no BRTI texture.'
        raise ValueError(message)
    return texture


def decode_texture(data: bytes, index: int = 0) -> bytes:
    """
    Decode the first BNTX texture and return PNG bytes.

    Parameters
    ----------
    data : bytes
        Decompressed BNTX file.
    index : int
        Texture index within the archive.

    Returns
    -------
    bytes
        PNG image.

    Raises
    ------
    ValueError
        The file is malformed or uses an unsupported texture format.
    """
    texture = _texture_offset(data, index)
    channel = struct.unpack_from('<I', data, texture + 0x1C)[0] >> 8
    width, height = struct.unpack_from('<II', data, texture + 0x24)
    size = struct.unpack_from('<I', data, texture + 0x50)[0]
    offset = struct.unpack_from('<Q', data, texture + 0x2A0)[0]
    block_height_log2 = struct.unpack_from('<I', data, texture + 0x34)[0] & 0xF
    if (not 0 < width <= _MAX_DIMENSION or not 0 < height <= _MAX_DIMENSION
            or offset + size > len(data) or block_height_log2 > _MAX_BLOCK_HEIGHT_LOG2):
        message = 'Invalid BNTX image bounds.'
        raise ValueError(message)
    if _ASTC_FIRST <= channel <= _ASTC_LAST:
        block_width, block_height = _ASTC[channel - _ASTC_FIRST]
        block_bytes = 16
    elif channel in {0x1F, 0x20, 0x1C, 0x1E}:
        block_width = block_height = 4
        block_bytes = 16
    elif channel in {0x1A, 0x1D}:
        block_width = block_height = 4
        block_bytes = 8
    elif channel in {_R8, _RG8, _R16, _RG16, _RGBA8, _BGRA8, _RGBA16, _RGBA32}:
        block_width = block_height = 1
        block_bytes = {
            _R8: 1,
            _RG8: 2,
            _R16: 2,
            _RG16: 4,
            _RGBA8: 4,
            _BGRA8: 4,
            _RGBA16: 8,
            _RGBA32: 16
        }[channel]
    else:
        message = f'Unsupported BNTX channel 0x{channel:02x}.'
        raise ValueError(message)
    row_bytes = math.ceil(width / block_width) * block_bytes
    rows = math.ceil(height / block_height)
    blocks = _deswizzle(data[offset:offset + size], row_bytes, rows, 1 << block_height_log2)
    rgba: bytes | np.ndarray
    if _ASTC_FIRST <= channel <= _ASTC_LAST:
        rgba = texture2ddecoder.decode_astc(blocks, width, height, block_width, block_height)
    elif channel in _DECODERS:
        rgba = _DECODERS[channel](blocks, width, height)
    elif channel == _R16:
        gray = np.frombuffer(blocks, dtype='<u2').reshape(height, width) // 257
        rgba = np.stack((gray, gray, gray, np.full_like(gray, 255)), axis=2).astype('uint8')
    elif channel == _RG16:
        channels = (np.frombuffer(blocks, dtype='<u2').reshape(height, width, 2) //
                    257).astype('uint8')
        rgba = np.concatenate((channels, np.zeros(
            (height, width, 1), dtype='uint8'), np.full((height, width, 1), 255, dtype='uint8')),
                              axis=2)
    elif channel == _RGBA16:
        rgba = (np.frombuffer(blocks, dtype='<u2').reshape(height, width, 4) // 257).astype('uint8')
    elif channel == _RGBA32:
        floats = np.frombuffer(blocks, dtype='<f4').reshape(height, width, 4)
        rgba = (np.clip(np.nan_to_num(floats), 0, 1) * 255).astype('uint8')
    elif channel == _R8:
        gray = np.frombuffer(blocks, dtype='uint8').reshape(height, width)
        rgba = np.stack((gray, gray, gray, np.full_like(gray, 255)), axis=2)
    elif channel == _RG8:
        gray = np.frombuffer(blocks, dtype='uint8').reshape(height, width, 2)[:, :, 0]
        rgba = np.stack((gray, gray, gray, np.full_like(gray, 255)), axis=2)
    else:
        rgba = np.frombuffer(blocks, dtype='uint8').reshape(height, width, 4)
        if channel == _BGRA8:
            rgba = rgba[:, :, [2, 1, 0, 3]]
    image = (Image.frombytes('RGBA', (width, height), rgba, 'raw', 'BGRA') if isinstance(
        rgba, bytes) else Image.fromarray(rgba, 'RGBA'))
    result = BytesIO()
    image.save(result, format='PNG')
    return result.getvalue()
