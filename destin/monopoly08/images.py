"""
EA "SHP*" image-container decoders for Monopoly 2008, consolidated.

This module is the single home for the four hard-won, separately verified texture
decoders for Monopoly 2008 across its console builds: Xbox 360 (PAMX/XMAP, GPU-tiled
DXT1/DXT4-5/DXN/A8R8G8B8), PS3 (SHPX, type-driven DXT1/DXT5/BGRA8888 via a DDS
wrapper), PS2 (SHPS, PSMT8/PSMT4 GS-deswizzle with variable-size CSM1 CLUTs), and Wii
(SHPG, big-endian GX CMPR plus paletted CI8/RGB5A3). Each was validated against the
PS3 SHPX of the same asset hashes; the decode algorithms here are copied faithfully
from the original standalone scripts and only reorganised. Note that the SHPS width-16
PAL4 path swizzles in a 16-wide block whose exact byte order could not be solved from
the few ground-truth samples, so it falls back to a linear read -- a known approximation
(correct for the near-uniform UI majority, approximate for the rare detailed one); the
Wii paletted outputs are likewise provisional in colour but geometrically correct.
"""

from __future__ import annotations

from pathlib import Path
import io
import struct

from PIL import Image
from destin.common.image import expand5, expand6, ps2_clut_swizzle_index
from destin.common.io import u16
from destin.common.utils import align_up
import numpy as np
import numpy.typing as npt

__all__ = ('EXTENSIONS', 'convert')

EXTENSIONS = frozenset({'.shpg', '.shps', '.shpx', '.xmap'})
"""Texture file extensions handled by :py:func:`convert`.

:meta hide-value:
"""

_MAX_SHPX_DIM = 8192
"""Largest accepted width or height for a PS3 SHPX image.

:meta hide-value:
"""
_MAX_SHP_DIM = 4096
"""Largest accepted width or height for a PS2 SHPS or Wii SHPG image.

:meta hide-value:
"""
_MIN_TILED_WIDTH = 32
"""Width below which PS2 palette indices are read linearly instead of untiled.

:meta hide-value:
"""
_CMPR_BLOCK_BYTES = 8
"""Size in bytes of one Wii CMPR (DXT1) sub-block.

:meta hide-value:
"""
_PAL_BYTES = 1024
"""Size in bytes of a 256-entry RGBA palette.

:meta hide-value:
"""
_SHPX_TYPE_BGRA8888 = 0x7D
"""SHPX entry type for uncompressed BGRA8888 data.

:meta hide-value:
"""
_SHPS_TYPE_PAL8 = 2
"""SHPS entry type for 8-bit paletted (PAL8) data.

:meta hide-value:
"""
_SHPG_TYPE_CMPR = 0x1E
"""SHPG entry type for GX CMPR (DXT1-like) data.

:meta hide-value:
"""
_SHPG_TYPE_PAL8 = 0x19
"""SHPG entry type for 8-bit paletted (CI8) data.

:meta hide-value:
"""

# --------------------------------------------------------------------------- #
# Xbox 360 PAMX / XMAP                                                         #
# --------------------------------------------------------------------------- #
# XMAP header (32 bytes, little-endian):
#     0x00 char[4] 'PAMX'
#     0x04 u32 version (3)
#     0x08 u32 data size (all mips, incl. tile padding)
#     0x0c u32 unknown (1)
#     0x10 u32 width
#     0x14 u32 height
#     0x18 u32 mip count
#     0x1c u32 format word: byte0 = [endian:2][GPUTEXTUREFORMAT:6]
# GPU formats seen: 0x12 DXT1, 0x14 DXT4/5, 0x06 8_8_8_8 (A8R8G8B8), 0x31 DXN.
# Data is GPU-tiled (Xbox 360) and endian-swapped (8in16 for DXT, 8in32 for ARGB).
# Decode = untile -> endian swap -> block/pixel decode -> RGBA.
_GPU_DXT1 = 0x12
_GPU_DXT4_5 = 0x14
_GPU_8888 = 0x06
_GPU_DXN = 0x31  # DXN / ATI2N (3Dc) two-channel normal map, 16 bytes/block.


def _tiled_x(offset: int, width: int, texel_pitch: int) -> int:
    aligned_width = align_up(width, 32)
    log_bpp = (texel_pitch >> 2) + ((texel_pitch >> 1) >> (texel_pitch >> 2))
    ob = offset << log_bpp
    ot = ((ob & ~4095) >> 3) + ((ob & 1792) >> 2) + (ob & 63)
    om = ot >> (7 + log_bpp)
    macro_x = (om % (aligned_width >> 5)) << 2
    tile = (((ot >> (5 + log_bpp)) & 2) + (ob >> 6)) & 3
    macro = (macro_x + tile) << 3
    micro = ((((ot >> 1) & ~15) + (ot & 15)) & ((texel_pitch << 3) - 1)) >> log_bpp
    return macro + micro


def _tiled_y(offset: int, width: int, texel_pitch: int) -> int:
    aligned_width = align_up(width, 32)
    log_bpp = (texel_pitch >> 2) + ((texel_pitch >> 1) >> (texel_pitch >> 2))
    ob = offset << log_bpp
    ot = ((ob & ~4095) >> 3) + ((ob & 1792) >> 2) + (ob & 63)
    om = ot >> (7 + log_bpp)
    macro_y = (om // (aligned_width >> 5)) << 2
    tile = ((ot >> (6 + log_bpp)) & 1) + ((ob & 2048) >> 10)
    macro = (macro_y + tile) << 3
    micro = (((ot & (((texel_pitch << 6) - 1) & ~31)) + ((ot & 15) << 1)) >> (3 + log_bpp)) & ~1
    return macro + micro + ((ot & 16) >> 4)


def _untile(data: bytes, blocks_w: int, blocks_h: int, elem_bytes: int) -> bytes:
    """
    Convert tiled data to linear (row-major) order.

    Verified empirically against known textures: sequential source blocks scatter to
    their tiled ``(x, y)`` destination slot.

    Parameters
    ----------
    data : bytes
        Tiled source bytes.
    blocks_w : int
        Width in elements (blocks).
    blocks_h : int
        Height in elements (blocks).
    elem_bytes : int
        Size of one element (block) in bytes.

    Returns
    -------
    bytes
        Linear row-major bytes ``blocks_w`` wide.
    """
    n = blocks_w * blocks_h * elem_bytes
    out = bytearray(n)
    for j in range(blocks_h):
        for i in range(blocks_w):
            lin = j * blocks_w + i
            x = _tiled_x(lin, blocks_w, elem_bytes)
            y = _tiled_y(lin, blocks_w, elem_bytes)
            d = (y * blocks_w + x) * elem_bytes
            s = lin * elem_bytes
            # Defensive only: the tiled mapping is a bijection over the 32-element-aligned grid
            # _untile_crop always passes, and that caller pads the data to exactly ``n`` bytes, so
            # neither bound can be exceeded.
            if d >= 0 and d + elem_bytes <= n and s + elem_bytes <= len(data):  # pragma: no branch
                out[d:d + elem_bytes] = data[s:s + elem_bytes]
    return bytes(out)


def _swap16(b: bytes) -> bytes:
    # byteswap() is untyped in the NumPy stubs, so bind its result to a typed name.
    swapped: npt.NDArray[np.uint16] = np.frombuffer(b, dtype='<u2').byteswap()
    return swapped.tobytes()


def _swap32(b: bytes) -> bytes:
    # byteswap() is untyped in the NumPy stubs, so bind its result to a typed name.
    swapped: npt.NDArray[np.uint32] = np.frombuffer(b, dtype='<u4').byteswap()
    return swapped.tobytes()


def _color565(c: int) -> tuple[int, int, int]:
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return expand5(r), expand6(g), expand5(b)


def _decode_dxt1(data: bytes, w: int, h: int) -> npt.NDArray[np.uint8]:
    out = np.zeros((h, w, 4), np.uint8)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    p = 0
    for by in range(bh):
        for bx in range(bw):
            c0, c1 = struct.unpack_from('<HH', data, p)
            bits = struct.unpack_from('<I', data, p + 4)[0]
            p += 8
            r0, g0, b0 = _color565(c0)
            r1, g1, b1 = _color565(c1)
            pal = [(r0, g0, b0, 255), (r1, g1, b1, 255), None, None]
            if c0 > c1:
                pal[2] = ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255)
                pal[3] = ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255)
            else:
                pal[2] = ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255)
                pal[3] = (0, 0, 0, 0)
            for i in range(16):
                px, py = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if px < w and py < h:
                    out[py, px] = pal[(bits >> (2 * i)) & 3]
    return out


def _dxt5_alpha_table(a0: int, a1: int) -> list[int]:
    # The eight-entry alpha ramp; a0 > a1 selects the six-interpolated variant.
    if a0 > a1:
        return [a0, a1] + [((7 - j) * a0 + j * a1) // 7 for j in range(1, 7)]
    return [a0, a1] + [((5 - j) * a0 + j * a1) // 5 for j in range(1, 5)] + [0, 255]


def _dxt5_color_palette(c0: int, c1: int) -> list[tuple[int, int, int]]:
    # The four-entry RGB palette from the two RGB565 endpoints (DXT5 4-colour mode).
    r0, g0, b0 = _color565(c0)
    r1, g1, b1 = _color565(c1)
    return [
        (r0, g0, b0),
        (r1, g1, b1),
        ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3),
        ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3),
    ]


def _decode_dxt5(data: bytes, w: int, h: int) -> npt.NDArray[np.uint8]:
    out = np.zeros((h, w, 4), np.uint8)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    p = 0
    for by in range(bh):
        for bx in range(bw):
            a0, a1 = data[p], data[p + 1]
            abits = int.from_bytes(data[p + 2:p + 8], 'little')
            c0, c1 = struct.unpack_from('<HH', data, p + 8)
            bits = struct.unpack_from('<I', data, p + 12)[0]
            p += 16
            at = _dxt5_alpha_table(a0, a1)
            pal = _dxt5_color_palette(c0, c1)
            for i in range(16):
                px, py = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if px < w and py < h:
                    out[py, px] = (*pal[(bits >> (2 * i)) & 3], at[(abits >> (3 * i)) & 7])
    return out


def _untile_crop(data: bytes, ew: int, eh: int, elem: int) -> bytes:
    """
    Untile to an aligned grid (32-element tiles), then crop to ``ew`` x ``eh`` elements.

    Parameters
    ----------
    data : bytes
        Tiled source bytes.
    ew : int
        Cropped width in elements.
    eh : int
        Cropped height in elements.
    elem : int
        Size of one element in bytes.

    Returns
    -------
    bytes
        Cropped linear row-major bytes ``ew`` elements wide.
    """
    awe = align_up(ew, 32)
    ahe = align_up(eh, 32)
    need = awe * ahe * elem
    tiled = data[:need] if len(data) >= need else data + b'\x00' * (need - len(data))
    aligned = _untile(tiled, awe, ahe, elem)  # Row-major, awe wide.
    out = bytearray(ew * eh * elem)
    row = ew * elem
    arow = awe * elem
    for j in range(eh):
        out[j * row:(j + 1) * row] = aligned[j * arow:j * arow + row]
    return bytes(out)


def _decode_alpha_block(block: bytes) -> list[int]:
    """
    Decode one 8-byte DXT5-style channel block to 16 values (4x4, row-major).

    Parameters
    ----------
    block : bytes
        The 8-byte channel block.

    Returns
    -------
    list[int]
        The 16 decoded channel values in row-major order.
    """
    a0, a1 = block[0], block[1]
    bits = int.from_bytes(block[2:8], 'little')
    if a0 > a1:
        at = [a0, a1] + [((7 - j) * a0 + j * a1) // 7 for j in range(1, 7)]
    else:
        at = [a0, a1] + [((5 - j) * a0 + j * a1) // 5 for j in range(1, 5)] + [0, 255]
    return [at[(bits >> (3 * i)) & 7] for i in range(16)]


def _decode_dxn(data: bytes, w: int, h: int) -> npt.NDArray[np.uint8]:
    """
    Decode DXN/ATI2N data, reconstructing the blue channel as a normal map.

    Each block is ``[red 8B][green 8B]``.

    Parameters
    ----------
    data : bytes
        Linear DXN block bytes.
    w : int
        Image width in pixels.
    h : int
        Image height in pixels.

    Returns
    -------
    numpy.typing.NDArray[numpy.uint8]
        Decoded ``h`` x ``w`` x 4 RGBA array.
    """
    out = np.zeros((h, w, 4), np.uint8)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    p = 0
    for by in range(bh):
        for bx in range(bw):
            red = _decode_alpha_block(data[p:p + 8])
            grn = _decode_alpha_block(data[p + 8:p + 16])
            p += 16
            for i in range(16):
                px, py = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if px < w and py < h:
                    r, g = red[i], grn[i]
                    nx, ny = r / 127.5 - 1.0, g / 127.5 - 1.0
                    nz = max(0.0, 1.0 - nx * nx - ny * ny) ** 0.5
                    out[py, px] = (r, g, int((nz + 1.0) * 127.5), 255)
    return out


def _decode_xmap(buf: bytes) -> tuple[npt.NDArray[np.uint8], dict[str, int]]:
    """
    Decode an XMAP byte buffer.

    Parameters
    ----------
    buf : bytes
        The whole XMAP file contents.

    Returns
    -------
    tuple[numpy.typing.NDArray[numpy.uint8], dict[str, int]]
        The decoded ``h`` x ``w`` x 4 RGBA array and an info dict with ``w``, ``h``,
        ``mips`` and ``fmt`` keys.

    Raises
    ------
    ValueError
        If the buffer does not start with the ``PAMX`` magic.
    NotImplementedError
        If the GPU texture format is not supported.
    """
    if buf[:4] != b'PAMX':
        msg = f'not PAMX ({buf[:4]!r})'
        raise ValueError(msg)
    _ver, _dsize, _unk, w, h, mips, fmtword = struct.unpack_from('<7I', buf, 4)
    fmt = fmtword & 0x3F
    data = buf[32:]
    if fmt in {_GPU_DXT1, _GPU_DXT4_5, _GPU_DXN}:
        elem = 8 if fmt == _GPU_DXT1 else 16
        bw, bh = (w + 3) // 4, (h + 3) // 4
        lin = _swap16(_untile_crop(data, bw, bh, elem))
        if fmt == _GPU_DXT1:
            rgba = _decode_dxt1(lin, w, h)
        elif fmt == _GPU_DXT4_5:
            rgba = _decode_dxt5(lin, w, h)
        else:
            rgba = _decode_dxn(lin, w, h)
    elif fmt == _GPU_8888:
        lin = _swap32(_untile_crop(data, w, h, 4))
        argb = np.frombuffer(lin[:w * h * 4], np.uint8).reshape(h, w, 4)
        # Stored ARGB (after 8in32 swap bytes are A, R, G, B) -> RGBA.
        rgba = argb[:, :, [1, 2, 3, 0]].copy()
    else:
        msg = f'GPU format 0x{fmt:02x}'
        raise NotImplementedError(msg)
    return rgba, {'w': w, 'h': h, 'mips': mips, 'fmt': fmt}


# --------------------------------------------------------------------------- #
# PS3 SHPX                                                                     #
# --------------------------------------------------------------------------- #
# SHPX is the PS3 member of EA's "SHP*" image family. The format is read straight
# from the entry header's image-type code:
#     0x00 "SHPX"   0x04 u32 size   0x08 u32 entry count   0x0C version tag
#     0x10 directory: { char[4] tag, u32 offset }   (offset -> entry header)
#     entry header (16 B) @ offset:
#         +0x00 u8  : bit7 = RefPack flag, bits0-6 = image type code
#         +0x04 u16 : width      +0x06 u16 : height
#     image data starts at offset+0x10 (largest mip first).
# Image type codes seen on PS3: 0x60 DXT1, 0x62 DXT5, 0x7d BGRA8888 (32bpp). DXT is
# decoded via a DDS wrapper (Pillow's C S3TC decoder); BGRA8888 is a direct reorder.
# Image-type code -> DXT fourcc, and DXT bytes per 4x4 block.
_DXT = {0x60: b'DXT1', 0x61: b'DXT3', 0x62: b'DXT5'}
_DXT_BPB = {0x60: 8, 0x61: 16, 0x62: 16}


def _make_dds(data: bytes, w: int, h: int, fourcc: bytes) -> bytes:
    fl = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    return (struct.pack('<4sIIIIIII', b'DDS ', 124, fl, h, w, len(data), 0, 1) + b'\x00' * 44 +
            struct.pack('<II4sIIIII', 32, 0x4, fourcc, 0, 0, 0, 0, 0) +
            struct.pack('<IIIII', 0x1000, 0, 0, 0, 0) + data)


def _decode_shpx(b: bytes) -> tuple[Image.Image, str, int, int]:
    """
    Decode SHPX bytes.

    Parameters
    ----------
    b : bytes
        The whole SHPX file contents.

    Returns
    -------
    tuple[PIL.Image.Image, str, int, int]
        The decoded RGBA image, the format name, the width and the height.

    Raises
    ------
    ValueError
        If the magic is wrong, the image data is RefPack-compressed, the dimensions
        are out of range, or the image type is unhandled.
    """
    if b[:4] != b'SHPX':
        msg = f'not SHPX ({b[:4]!r})'
        raise ValueError(msg)
    eo = struct.unpack_from('<I', b, 0x14)[0]  # Entry-header offset.
    type_byte = b[eo]
    if type_byte & 0x80:
        msg = 'RefPack-compressed image data (unhandled)'
        raise ValueError(msg)
    t = type_byte & 0x7F
    w = struct.unpack_from('<H', b, eo + 4)[0]
    h = struct.unpack_from('<H', b, eo + 6)[0]
    if not (0 < w <= _MAX_SHPX_DIM and 0 < h <= _MAX_SHPX_DIM):
        msg = f'bad dims {w}x{h}'
        raise ValueError(msg)
    do = eo + 0x10  # Image data start.
    if t in _DXT:
        base = (w // 4) * (h // 4) * _DXT_BPB[t]
        img = Image.open(io.BytesIO(_make_dds(b[do:do + base], w, h, _DXT[t])))
        return img.convert('RGBA'), _DXT[t].decode(), w, h
    if t == _SHPX_TYPE_BGRA8888:  # BGRA8888, uncompressed.
        a = np.frombuffer(b[do:do + w * h * 4], np.uint8).reshape(h, w, 4)
        rgba = a[:, :, [2, 1, 0, 3]]  # BGRA -> RGBA.
        return Image.fromarray(rgba, 'RGBA'), 'BGRA8888', w, h
    msg = f'unhandled image type 0x{t:02x} ({w}x{h})'
    raise ValueError(msg)


# --------------------------------------------------------------------------- #
# PS2 SHPS                                                                     #
# --------------------------------------------------------------------------- #
# SHPS is the PS2 member of EA's "SHP*" image family, storing palettised,
# GS-swizzled textures:
#     type 0x01  PAL4_RGBA8888  -- 4-bit indices, 16-colour RGBA8888 palette
#     type 0x02  PAL8_RGBA8888  -- 8-bit indices, 256-colour RGBA8888 palette
# Entry header @ 0x30 (little-endian): type byte (& 0x7F) at 0x30, u16 width @ 0x34,
# u16 height @ 0x36; the palette is a trailing attachment whose data starts 16 bytes
# after the header found at 0x30 + int24(@0x31). PAL8 indices are GS PSMT8-swizzled,
# the 256-colour CLUT is CSM1-swizzled. PAL4 indices are GS PSMT4 (deswizzled as a
# half-width PSMT8 byte image then remapped via _PSMT4_M); its 16-colour CLUT is
# stored straight. Palettes are R, G, B, A; PS2 alpha is 0-128 (0x80 opaque), scaled x2.

# PSMT4 within-block nibble map: pixel (py 0..15, px 0..31) -> (byte_index*2 + nibble)
# within the 256-byte (= 512-nibble) block. Recovered from ground truth; exact.
_PSMT4_M = np.array(
    [
        [
            0,
            16,
            2,
            18,
            4,
            20,
            6,
            22,
            72,
            88,
            74,
            90,
            76,
            92,
            78,
            94,
            8,
            24,
            10,
            26,
            12,
            28,
            14,
            30,
            64,
            80,
            66,
            82,
            68,
            84,
            70,
            86,
        ],
        [
            32,
            48,
            34,
            50,
            36,
            52,
            38,
            54,
            104,
            120,
            106,
            122,
            108,
            124,
            110,
            126,
            40,
            56,
            42,
            58,
            44,
            60,
            46,
            62,
            96,
            112,
            98,
            114,
            100,
            116,
            102,
            118,
        ],
        [
            5,
            21,
            7,
            23,
            1,
            17,
            3,
            19,
            77,
            93,
            79,
            95,
            73,
            89,
            75,
            91,
            13,
            29,
            15,
            31,
            9,
            25,
            11,
            27,
            69,
            85,
            71,
            87,
            65,
            81,
            67,
            83,
        ],
        [
            37,
            53,
            39,
            55,
            33,
            49,
            35,
            51,
            109,
            125,
            111,
            127,
            105,
            121,
            107,
            123,
            45,
            61,
            47,
            63,
            41,
            57,
            43,
            59,
            101,
            117,
            103,
            119,
            97,
            113,
            99,
            115,
        ],
        [
            140,
            156,
            142,
            158,
            136,
            152,
            138,
            154,
            196,
            212,
            198,
            214,
            192,
            208,
            194,
            210,
            132,
            148,
            134,
            150,
            128,
            144,
            130,
            146,
            204,
            220,
            206,
            222,
            200,
            216,
            202,
            218,
        ],
        [
            172,
            188,
            174,
            190,
            168,
            184,
            170,
            186,
            228,
            244,
            230,
            246,
            224,
            240,
            226,
            242,
            164,
            180,
            166,
            182,
            160,
            176,
            162,
            178,
            236,
            252,
            238,
            254,
            232,
            248,
            234,
            250,
        ],
        [
            137,
            153,
            139,
            155,
            141,
            157,
            143,
            159,
            193,
            209,
            195,
            211,
            197,
            213,
            199,
            215,
            129,
            145,
            131,
            147,
            133,
            149,
            135,
            151,
            201,
            217,
            203,
            219,
            205,
            221,
            207,
            223,
        ],
        [
            169,
            185,
            171,
            187,
            173,
            189,
            175,
            191,
            225,
            241,
            227,
            243,
            229,
            245,
            231,
            247,
            161,
            177,
            163,
            179,
            165,
            181,
            167,
            183,
            233,
            249,
            235,
            251,
            237,
            253,
            239,
            255,
        ],
        [
            256,
            272,
            258,
            274,
            260,
            276,
            262,
            278,
            328,
            344,
            330,
            346,
            332,
            348,
            334,
            350,
            264,
            280,
            266,
            282,
            268,
            284,
            270,
            286,
            320,
            336,
            322,
            338,
            324,
            340,
            326,
            342,
        ],
        [
            288,
            304,
            290,
            306,
            292,
            308,
            294,
            310,
            360,
            376,
            362,
            378,
            364,
            380,
            366,
            382,
            296,
            312,
            298,
            314,
            300,
            316,
            302,
            318,
            352,
            368,
            354,
            370,
            356,
            372,
            358,
            374,
        ],
        [
            261,
            277,
            263,
            279,
            257,
            273,
            259,
            275,
            333,
            349,
            335,
            351,
            329,
            345,
            331,
            347,
            269,
            285,
            271,
            287,
            265,
            281,
            267,
            283,
            325,
            341,
            327,
            343,
            321,
            337,
            323,
            339,
        ],
        [
            293,
            309,
            295,
            311,
            289,
            305,
            291,
            307,
            365,
            381,
            367,
            383,
            361,
            377,
            363,
            379,
            301,
            317,
            303,
            319,
            297,
            313,
            299,
            315,
            357,
            373,
            359,
            375,
            353,
            369,
            355,
            371,
        ],
        [
            396,
            412,
            398,
            414,
            392,
            408,
            394,
            410,
            452,
            468,
            454,
            470,
            448,
            464,
            450,
            466,
            388,
            404,
            390,
            406,
            384,
            400,
            386,
            402,
            460,
            476,
            462,
            478,
            456,
            472,
            458,
            474,
        ],
        [
            428,
            444,
            430,
            446,
            424,
            440,
            426,
            442,
            484,
            500,
            486,
            502,
            480,
            496,
            482,
            498,
            420,
            436,
            422,
            438,
            416,
            432,
            418,
            434,
            492,
            508,
            494,
            510,
            488,
            504,
            490,
            506,
        ],
        [
            393,
            409,
            395,
            411,
            397,
            413,
            399,
            415,
            449,
            465,
            451,
            467,
            453,
            469,
            455,
            471,
            385,
            401,
            387,
            403,
            389,
            405,
            391,
            407,
            457,
            473,
            459,
            475,
            461,
            477,
            463,
            479,
        ],
        [
            425,
            441,
            427,
            443,
            429,
            445,
            431,
            447,
            481,
            497,
            483,
            499,
            485,
            501,
            487,
            503,
            417,
            433,
            419,
            435,
            421,
            437,
            423,
            439,
            489,
            505,
            491,
            507,
            493,
            509,
            495,
            511,
        ],
    ],
    dtype=np.int64,
)

_addr8_cache: dict[tuple[int, int], npt.NDArray[np.int64]] = {}


def _psmt8_addr(w: int, h: int) -> npt.NDArray[np.int64]:
    """
    Build a vectorised GS PSMT8 deswizzle gather-index array for a ``(w, h)`` byte image.

    Parameters
    ----------
    w : int
        Image width in bytes.
    h : int
        Image height in bytes.

    Returns
    -------
    numpy.typing.NDArray[numpy.int64]
        Flat gather-index array of length ``w * h``.
    """
    key = (w, h)
    if key in _addr8_cache:
        return _addr8_cache[key]
    y = np.arange(h)[:, None]
    x = np.arange(w)[None, :]
    block = (y & ~0xF) * w + (x & ~0xF) * 2
    swap = (((y + 2) >> 2) & 1) * 4
    pos_y = (((y & ~3) >> 1) + (y & 1)) & 7
    col = pos_y * w * 2 + ((x + swap) & 7) * 4
    bsum = ((y >> 1) & 1) + ((x >> 2) & 2)
    addr = (block + col + bsum).reshape(-1)
    _addr8_cache[key] = addr
    return addr


def _idx_pal8(raw: npt.NDArray[np.uint8], w: int, h: int) -> npt.NDArray[np.uint8]:
    return raw[_psmt8_addr(w, h)]  # [w*h] indices.


_pal4_cache: dict[tuple[int, int], tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]] = {}


def _idx_pal4(raw: npt.NDArray[np.uint8], w: int, h: int) -> npt.NDArray[np.uint8]:
    """
    Deswizzle a PSMT4 index plane to ``[w*h]`` 4-bit indices.

    Width-16 PAL4 textures swizzle in a 16-wide block whose exact byte order could
    not be pinned down (only 5 ground-truth samples exist, insufficient to solve the
    256-permutation; the high-detail sample defeats every derivation). They are all
    small 16x{16,32,64} UI bits, so they fall back to a linear read -- correct for the
    near-uniform majority, approximate for the rare detailed one.

    Parameters
    ----------
    raw : numpy.typing.NDArray[numpy.uint8]
        Raw packed PSMT4 index bytes.
    w : int
        Image width in pixels.
    h : int
        Image height in pixels.

    Returns
    -------
    numpy.typing.NDArray[numpy.uint8]
        Flat array of ``w * h`` 4-bit palette indices.
    """
    if w < _MIN_TILED_WIDTH:
        flat = np.empty(raw.size * 2, np.uint8)
        flat[0::2] = raw & 0xF
        flat[1::2] = raw >> 4
        return flat[:w * h]
    key = (w, h)
    if key not in _pal4_cache:
        # Bytes deswizzled as half-width PSMT8.
        b_addr = _psmt8_addr(w // 2, h)  # Gather for B (h x w/2).
        yy = np.arange(h)[:, None]
        xx = np.arange(w)[None, :]
        cand = _PSMT4_M[yy % 16, xx % 32]  # [h, w] -> 0..511.
        bidx = cand // 2
        nib = (cand % 2).reshape(-1)
        # B row/col of the source byte.
        b_r = (yy // 16) * 16 + (bidx // 16)
        b_c = (xx // 32) * 16 + (bidx % 16)
        # B is laid out (h x w/2); B[r, c] = raw[b_addr[r*(w/2)+c]].
        raw_byte = b_addr.reshape(h, w // 2)[b_r, b_c].reshape(-1)
        _pal4_cache[key] = (raw_byte, nib)
    raw_byte, nib = _pal4_cache[key]
    vals = raw[raw_byte]
    return np.where(nib == 1, vals >> 4, vals & 0xF).astype(np.uint8)


def _csm1_unswizzle(pal: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """
    De-swizzle a PS2 CSM1 CLUT in place of storage order.

    Within each block of 32 entries, swap entries 8-15 with 16-23. Applied with a
    bounds guard so it is a no-op for <=16-colour palettes and only partial for the
    odd in-between counts (72/87/161/192) seen in this game.

    Parameters
    ----------
    pal : numpy.typing.NDArray[numpy.uint8]
        Palette entries in storage order.

    Returns
    -------
    numpy.typing.NDArray[numpy.uint8]
        Palette entries in display order.
    """
    n = len(pal)
    j = np.array([ps2_clut_swizzle_index(i) for i in range(n)])
    j = np.where(j < n, j, np.arange(n))
    reordered: npt.NDArray[np.uint8] = pal[j]
    return reordered


def _palette(b: bytes) -> npt.NDArray[np.uint8]:
    """
    Read the trailing palette attachment.

    Its entry count is stored in the attachment header (0x21 / int24 size / u16
    count) and is NOT always 256 -- this game uses 3/16/72/87/161/192/256-colour
    CLUTs.

    Parameters
    ----------
    b : bytes
        The whole SHPS file contents.

    Returns
    -------
    numpy.typing.NDArray[numpy.uint8]
        Palette as an ``n`` x 4 RGBA array in display order.
    """
    att = 0x30 + int.from_bytes(b[0x31:0x34], 'little')
    n = struct.unpack_from('<H', b, att + 4)[0] or 256
    pal = np.frombuffer(b[att + 16:att + 16 + n * 4], np.uint8)
    if len(pal) < n * 4:
        pal = np.concatenate([pal, np.zeros(n * 4 - len(pal), np.uint8)])
    wide = pal.reshape(n, 4).astype(np.uint16).copy()
    wide[:, 3] = np.clip(wide[:, 3] * 2, 0, 255)  # PS2 alpha 0-128 -> 0-255.
    return _csm1_unswizzle(wide.astype(np.uint8))


def _decode_shps(b: bytes) -> tuple[Image.Image, str, int, int]:
    """
    Decode SHPS bytes.

    Parameters
    ----------
    b : bytes
        The whole SHPS file contents.

    Returns
    -------
    tuple[PIL.Image.Image, str, int, int]
        The decoded RGBA image, the format name, the width and the height.

    Raises
    ------
    ValueError
        If the magic is wrong, the dimensions are out of range, or the image type is
        unhandled.
    """
    if b[:4] != b'SHPS':
        msg = f'not SHPS ({b[:4]!r})'
        raise ValueError(msg)
    t = b[0x30] & 0x7F
    w = struct.unpack_from('<H', b, 0x34)[0]
    h = struct.unpack_from('<H', b, 0x36)[0]
    if not (0 < w <= _MAX_SHP_DIM and 0 < h <= _MAX_SHP_DIM):
        msg = f'bad dims {w}x{h}'
        raise ValueError(msg)
    if t == _SHPS_TYPE_PAL8:  # PAL8_RGBA8888.
        raw = np.frombuffer(b[0x40:0x40 + w * h], np.uint8)
        idx = _idx_pal8(raw, w, h)
        fmt = 'PAL8'
    elif t == 1:  # PAL4_RGBA8888.
        raw = np.frombuffer(b[0x40:0x40 + w * h // 2], np.uint8)
        idx = _idx_pal4(raw, w, h)
        fmt = 'PAL4'
    else:
        msg = f'unhandled type 0x{t:02x} ({w}x{h})'
        raise ValueError(msg)
    pal = _palette(b)
    img = pal[np.clip(idx, 0, len(pal) - 1)].reshape(h, w, 4)
    return Image.fromarray(img, 'RGBA'), fmt, w, h


# --------------------------------------------------------------------------- #
# Wii SHPG                                                                     #
# --------------------------------------------------------------------------- #
# SHPG is the Wii/GameCube member of EA's "SHP*" image family. The wrapper is
# little-endian tool output but the Wii pixel/field data is big-endian GX:
#     0x00 char[4] "SHPG"   0x04 u32 LE size   0x08 u32 entries   0x0C version tag
#     0x10 directory: per entry { char[4] tag, u32 offset }
#     entry header (16 B) @ directory offset:
#         +0x00 u8    : bit7 = RefPack flag, bits0-6 = image type code
#         +0x01 int24 : relative offset to first attachment
#         +0x04 u16   : width (BE)   +0x06 u16 : height
#         +0x0E u16   : ShapeY (low 4 bits = mipmap count)
# This game's Wii image types (type byte & 0x7F): 0x19 PAL8_RGB5A3,
# 0x18 PAL4_RGB5A3 (palette stored 32-bit ARGB), 0x1E N64_CMPR (GameCube CMPR),
# 0x16 ARGB8888. N64_CMPR is decoded correctly (GX 8x8 tiles of four 4x4 DXT1
# sub-blocks, big-endian RGB565 endpoints, 2-bit index pairs reversed per byte ->
# rebuilt to linear DXT1). Paletted indices de-tile perfectly but the exact
# index<->TLUT-storage order for this game is not a standard swizzle, so paletted
# PNGs are written as provisional (correct geometry, approximate colour).
_TYPE_NAMES = {
    1: 'PAL4_RGBA8888',
    2: 'PAL8_RGBA8888',
    0x16: 'ARGB8888',
    0x18: 'PAL4',
    0x19: 'PAL8',
    0x1E: 'CMPR',
}


def _entry(b: bytes) -> tuple[int, int, int, int, int]:
    t = b[0x30] & 0x7F
    w, h = u16(b, 0x34, endian='>'), u16(b, 0x36, endian='>')
    nmip = u16(b, 0x3E, endian='>') & 0xF
    att = 0x30 + int.from_bytes(b[0x31:0x34], 'big')  # First attachment offset.
    return t, w, h, nmip, att


def _cmpr(data: bytes, w: int, h: int) -> Image.Image:
    bw, bh = w // 4, h // 4
    dxt = bytearray(bw * bh * 8)
    pos = 0
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            for sy in range(2):
                for sx in range(2):
                    blk = data[pos:pos + 8]
                    pos += 8
                    if len(blk) < _CMPR_BLOCK_BYTES:
                        continue
                    bx, by = (tx // 4) + sx, (ty // 4) + sy
                    di = (by * bw + bx) * 8
                    dxt[di] = blk[1]
                    dxt[di + 1] = blk[0]
                    dxt[di + 2] = blk[3]
                    dxt[di + 3] = blk[2]
                    for i in range(4):
                        c = blk[4 + i]
                        dxt[di + 4 + i] = (((c & 0x03) << 6)
                                           | ((c & 0x0C) << 2)
                                           | ((c & 0x30) >> 2)
                                           | ((c & 0xC0) >> 6))
    return Image.open(io.BytesIO(_make_dds(bytes(dxt), w, h, b'DXT1'))).convert('RGBA')


def _untile_ci8(d: npt.NDArray[np.uint8], w: int, h: int) -> npt.NDArray[np.uint8]:
    out = np.zeros((h, w), np.uint8)
    pos = 0
    for ty in range(0, h, 4):
        for tx in range(0, w, 8):
            out[ty:ty + 4, tx:tx + 8] = d[pos:pos + 32].reshape(4, 8)
            pos += 32
    return out.reshape(-1)


def _decode_shpg(b: bytes) -> tuple[Image.Image, str, int, int, bool]:
    """
    Decode SHPG bytes.

    Parameters
    ----------
    b : bytes
        The whole SHPG file contents.

    Returns
    -------
    tuple[PIL.Image.Image, str, int, int, bool]
        The decoded RGBA image, the format name, the width, the height and a flag
        that is ``True`` when the colour is provisional (geometry correct only).

    Raises
    ------
    ValueError
        If the magic is wrong, the dimensions are out of range, or the image type is
        unhandled.
    """
    if b[:4] != b'SHPG':
        msg = f'not SHPG ({b[:4]!r})'
        raise ValueError(msg)
    t, w, h, _nmip, att = _entry(b)
    if not (0 < w <= _MAX_SHP_DIM and 0 < h <= _MAX_SHP_DIM):
        msg = f'bad dims {w}x{h}'
        raise ValueError(msg)
    fmt = _TYPE_NAMES.get(t, f'0x{t:02x}')
    if t == _SHPG_TYPE_CMPR:  # CMPR -- fully correct.
        return _cmpr(b[0x40:0x40 + (w // 4) * (h // 4) * 8], w, h), 'CMPR', w, h, False
    if t in {0x19, 0x18}:  # PAL8 / PAL4 -- geometry correct, colour provisional.
        idx8 = np.frombuffer(b[0x40:0x40 + w * h], np.uint8)
        if t == _SHPG_TYPE_PAL8 and len(idx8) == w * h:
            ix = _untile_ci8(idx8, w, h)
            pal = np.frombuffer(b[att + 16:att + 16 + _PAL_BYTES], np.uint8)
            if len(pal) == _PAL_BYTES:
                pal = pal.reshape(256, 4)[:, [1, 2, 3, 0]]  # ARGB -> RGBA (approx).
                return Image.fromarray(pal[ix].reshape(h, w, 4), 'RGBA'), fmt, w, h, True
        # PAL4 or short data: fall back to a grayscale index map (geometry only).
        g = _untile_ci8(idx8[:w * h], w, h) if len(idx8) >= w * h else idx8
        return Image.fromarray(g[:w * h].reshape(h, w), 'L').convert('RGBA'), fmt, w, h, True
    msg = f'unhandled type {fmt} ({w}x{h})'
    raise ValueError(msg)


# --------------------------------------------------------------------------- #
# Public dispatch                                                             #
# --------------------------------------------------------------------------- #
def convert(path: str | Path) -> tuple[Path, str, int, int]:
    """
    Decode an EA SHP*/XMAP texture and write ``<path-without-ext>.png`` next to it.

    Dispatches by file extension (``.xmap``/``.shpx``/``.shps``/``.shpg``) to the
    matching decoder.

    Parameters
    ----------
    path : str | pathlib.Path
        Path to the source texture file.

    Returns
    -------
    tuple[pathlib.Path, str, int, int]
        The written PNG path, the format name, the width and the height.

    Raises
    ------
    ValueError
        If the file extension is not one of :py:data:`EXTENSIONS`, or the underlying
        decoder rejects the file.
    """
    src = Path(path)
    ext = src.suffix.lower()
    if ext not in EXTENSIONS:
        msg = f'unhandled texture extension {ext!r} for {str(src)!r}'
        raise ValueError(msg)
    out = src.with_suffix('.png')
    b = src.read_bytes()
    if ext == '.xmap':
        rgba, info = _decode_xmap(b)
        img = Image.fromarray(rgba, 'RGBA')
        fmt = f'0x{info["fmt"]:02x}'
        w, h = info['w'], info['h']
    elif ext == '.shpx':
        img, fmt, w, h = _decode_shpx(b)
    elif ext == '.shps':
        img, fmt, w, h = _decode_shps(b)
    else:  # .shpg
        img, fmt, w, h, _prov = _decode_shpg(b)
    img.save(out)
    return out, fmt, w, h
