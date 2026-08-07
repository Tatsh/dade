"""
Decode the games' bitmaps to PNG.

Two console-native formats are decoded by content: Amplitude's HMX bitmap (``.bmp``) and
FreQuency's ``ABitmap`` (``.abm``, ``C:/FREQ/src/rndartt/abitmap.h``). Anything else Pillow can
open (e.g. a standard Windows BMP) is converted by Pillow directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import logging
import os
import re
import shutil
import struct

from PIL import Image
from destin.common.image import double_ps2_alpha, ps2_clut_swizzle_index
from destin.common.io import u16, u32
from destin.common.png import write_rgba

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('EXTENSIONS', 'convert', 'decode_freq_abm', 'decode_hmx_bitmap', 'link_references',
           'parse_freq_tex_reference', 'parse_tex_reference')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.abm', '.bmp', '.bmp_dark'})
"""File extensions handled by :py:func:`convert`.

:meta hide-value:
"""

_REF_EXTS = ('.bmp', '.tex')
"""Extensions of the texture-reference proxy objects handled by :py:func:`link_references`.

:meta hide-value:
"""
_TEX_PROXY_MAX_SIZE = 4096  # Reference proxies are tiny headers; real bitmaps are far larger.
_TEX_REF_RE = re.compile(rb'([\x20-\x7e]{2,}\.(?:bmp|tex|tga))\x00*$')
_FREQ_TEX_VERSION = 4  # FreQuency Rnd::Tex descriptor version.
_FREQ_TEX_BPPS = frozenset({4, 8, 16, 32})
_FREQ_TEX_MAX_DIM = 4096
_FREQ_TEX_NAME_OFFSET = 16  # After u32 version, width, height, bpp.
_FREQ_PNG_SUFFIX = '_bmp'  # The named ABitmap decodes to "<stem>_bmp.png".
_PRINTABLE = range(0x20, 0x7f)  # Printable ASCII range.

_HMX_MIN_SIZE = 16
_HMX_TYPE = 3  # byte[2] of an HMX bitmap header.
_BPP_8 = 8
_BPP_32 = 32
_MAX_DIM = 4096


def decode_hmx_bitmap(data: bytes) -> tuple[int, int, bytes] | None:
    """
    Decode a console-native HMX bitmap.

    The header is ``u8 0 | u8 bpp | u8 3 | u8 numMips | u16 width | u16 height | ...``, then a
    palette (``2**bpp`` RGBA entries, alpha in ``0..128``) for paletted depths, then level-0
    pixels. PS2 8bpp palettes are CLUT-unswizzled and the alpha is scaled to ``0..255``.

    Parameters
    ----------
    data : bytes
        The bitmap file contents.

    Returns
    -------
    tuple[int, int, bytes] | None
        ``(width, height, rgba)`` (top-down RGBA), or ``None`` if not an HMX bitmap.
    """
    if len(data) < _HMX_MIN_SIZE or data[0] != 0 or data[2] != _HMX_TYPE:
        return None
    bpp, w, h = data[1], u16(data, 4), u16(data, 6)
    if bpp not in {4, 8, 32} or not w or not h:
        return None
    off = 16
    if bpp in {4, 8}:
        ncol = 1 << bpp
        if off + ncol * 4 > len(data):
            return None
        pal = [
            bytes((data[off + i * 4], data[off + i * 4 + 1], data[off + i * 4 + 2],
                   double_ps2_alpha(data[off + i * 4 + 3]))) for i in range(ncol)
        ]
        off += ncol * 4
        if bpp == _BPP_8:
            tab = [pal[ps2_clut_swizzle_index(i)] for i in range(256)]
            rgba = b''.join([tab[p] for p in data[off:off + w * h]])
        else:
            pair = [pal[b & 0xF] + pal[b >> 4] for b in range(256)]
            rgba = b''.join([pair[b] for b in data[off:off + (w * h + 1) // 2]])[:w * h * 4]
        return (w, h, rgba) if len(rgba) == w * h * 4 else None
    px = bytearray(data[off:off + w * h * 4])  # 32bpp direct RGBA.
    if len(px) != w * h * 4:
        return None
    for i in range(3, len(px), 4):
        px[i] = double_ps2_alpha(px[i])
    return w, h, bytes(px)


_ABM_HDR_PALETTED = 32  # u32 0 | u16 0 | u16 w | u16 h | u16 stride | ... | u32 pixelSize@16 | ...
_ABM_HDR_DIRECT = 24
_ABM_PALETTE = 256 * 4  # 256 RGBA entries.


def _abm_unpack_rle(region: bytes, target: int) -> bytes:
    # Run/literal codec: ctrl < 0x80 -> run of `ctrl` copies of the next byte; ctrl >= 0x80 ->
    # literal run of the next ``ctrl & 0x7f`` bytes. Decodes to exactly ``target`` bytes (the
    # stored stream is padded to an even length, so one trailing byte may go unread).
    out = bytearray()
    i, n = 0, len(region)
    while len(out) < target and i < n:
        ctrl = region[i]
        i += 1
        if ctrl & 0x80:
            count = ctrl & 0x7F
            out += region[i:i + count]
            i += count
        elif i < n:
            out += bytes((region[i],)) * ctrl
            i += 1
    return bytes(out[:target])


def decode_freq_abm(data: bytes) -> tuple[int, int, bytes] | None:
    """
    Decode a FreQuency ``ABitmap`` (``.abm``).

    The header is ``u32 0 | u8 0 | u8 fmt | u16 width | u16 height | u16 stride | u32 0 |
    u32 pixelSize@0x10 | ...``. Bits-per-pixel is ``stride * 8 // width``. For 4/8 bpp the 32-byte
    header is followed by a 256-entry RGBA palette and ``pixelSize`` bytes of pixels (stored raw
    when ``pixelSize == stride * height``, otherwise run/literal RLE (see
    :py:func:`_abm_unpack_rle`).
    For 32 bpp the header is 24 bytes and the pixels are raw RGBA with no palette. Alpha is full
    range (unlike Amplitude HMX), the channel order is RGBA, and the palette is linear (no PS2 CLUT
    swizzle).

    Parameters
    ----------
    data : bytes
        The ``.abm`` file contents.

    Returns
    -------
    tuple[int, int, bytes] | None
        ``(width, height, rgba)`` (top-down RGBA), or ``None`` if not a valid ABitmap.
    """
    if len(data) < _ABM_HDR_DIRECT or data[:5] != b'\x00\x00\x00\x00\x00':
        return None
    width, height, stride = struct.unpack_from('<HHH', data, 6)
    size = struct.unpack_from('<I', data, 16)[0]
    if not (0 < width <= _MAX_DIM and 0 < height <= _MAX_DIM) or not stride:
        return None
    bpp = stride * 8 // width
    if bpp == _BPP_32 and len(data) - size == _ABM_HDR_DIRECT and size == width * height * 4:
        px = data[_ABM_HDR_DIRECT:_ABM_HDR_DIRECT + size]
        return (width, height, px) if len(px) == width * height * 4 else None
    if bpp not in {4, 8} or len(data) - size != _ABM_HDR_PALETTED + _ABM_PALETTE:
        return None
    pal_off = _ABM_HDR_PALETTED
    pal = [data[pal_off + i * 4:pal_off + i * 4 + 4] for i in range(256)]
    target = stride * height
    region = data[pal_off + _ABM_PALETTE:pal_off + _ABM_PALETTE + size]
    pixels = region if size == target else _abm_unpack_rle(region, target)
    if len(pixels) != target:
        return None
    rgba = bytearray(width * height * 4)
    if bpp == _BPP_8:
        tab = [pal[ps2_clut_swizzle_index(i)] for i in range(256)]  # PS2 8bpp CLUT is swizzled.
        for i, idx in enumerate(pixels):
            rgba[i * 4:i * 4 + 4] = tab[idx]
    else:  # 4 bpp: two pixels per byte, low nibble first.
        o = 0
        for byte in pixels:
            rgba[o:o + 4] = pal[byte & 0x0F]
            rgba[o + 4:o + 8] = pal[byte >> 4]
            o += 8
    return width, height, bytes(rgba[:width * height * 4])


def convert(path: Path) -> Path | None:
    """
    Convert a bitmap to a sibling ``.png`` and delete the original.

    Console-native formats (HMX ``.bmp``, FreQuency ``.abm``) are decoded here; any other file
    Pillow recognises (e.g. a standard Windows BMP) is converted by Pillow directly.

    Parameters
    ----------
    path : pathlib.Path
        The bitmap file.

    Returns
    -------
    pathlib.Path | None
        The written PNG path, or ``None`` if the file was not a decodable bitmap.
    """
    data = path.read_bytes()
    png = path.with_suffix('.png')
    hmx = decode_hmx_bitmap(data)
    decoded = hmx or decode_freq_abm(data)
    if decoded is not None:
        width, height, rgba = decoded
        write_rgba(png, width, height, rgba)
        log.debug('Bitmap `%s`: %s %dx%d -> `%s`', path.name, 'HMX' if hmx else 'ABitmap', width,
                  height, png.name)
        path.unlink()
        return png
    try:  # Standard image (e.g. a Windows BMP) -- let Pillow decode it.
        with Image.open(path) as im:
            im.load()
            width, height = im.size
            im.save(png)
    except (OSError, ValueError) as e:
        log.debug('Bitmap `%s`: not a decodable bitmap (%s)', path.name, e)
        return None
    log.debug('Bitmap `%s`: Pillow %dx%d -> `%s`', path.name, width, height, png.name)
    path.unlink()
    return png


def parse_tex_reference(data: bytes) -> str | None:
    """
    Return the texture filename a ``RndTex`` reference proxy points to, or ``None``.

    Many ``.bmp``/``.tex`` objects are not bitmaps at all but tiny proxies -- a small header
    followed by the name of the real texture in a shared pool (e.g. ``image/bg_fog.bmp``). Such a
    proxy ends with that name plus NUL padding and is far too small to hold pixels.

    Parameters
    ----------
    data : bytes
        The object file contents.

    Returns
    -------
    str | None
        The referenced texture path, or ``None`` if the data is not a reference proxy.
    """
    if not data or len(data) > _TEX_PROXY_MAX_SIZE:
        return None
    match = _TEX_REF_RE.search(data)
    return match.group(1).decode('latin-1') if match else None


def parse_freq_tex_reference(data: bytes) -> str | None:
    """
    Return the bitmap a FreQuency ``Rnd::Tex`` (``.bmp``) descriptor points to, or ``None``.

    A FreQuency ``.bmp`` holds no pixels: it is ``u32 version (4) | u32 width | u32 height |
    u32 bpp | NUL-terminated bitmap name | ...``. The named bitmap's pixels live in an external
    ABitmap that this package decodes to ``<name>_bmp.png`` (see :py:func:`link_references`).

    Parameters
    ----------
    data : bytes
        The ``.bmp`` descriptor contents.

    Returns
    -------
    str | None
        The referenced bitmap name (e.g. ``'circ_shuttle.bmp'``), or ``None`` if the data is not a
        FreQuency texture descriptor carrying a non-empty name.
    """
    if len(data) < _FREQ_TEX_NAME_OFFSET + 2 or u32(data, 0) != _FREQ_TEX_VERSION:
        return None
    width, height, bpp = u32(data, 4), u32(data, 8), u32(data, 12)
    if not (0 < width <= _FREQ_TEX_MAX_DIM and 0 < height <= _FREQ_TEX_MAX_DIM
            and bpp in _FREQ_TEX_BPPS):
        return None
    end = data.find(b'\x00', _FREQ_TEX_NAME_OFFSET)
    if end <= _FREQ_TEX_NAME_OFFSET:
        return None
    name = data[_FREQ_TEX_NAME_OFFSET:end]
    if not all(c in _PRINTABLE for c in name) or not name.lower().endswith((b'.bmp', b'.tex')):
        return None
    return name.decode('latin-1')


def _reference_png_stem(data: bytes) -> str | None:
    # The PNG stem a texture proxy resolves to: FreQuency Rnd::Tex names an external ABitmap
    # decoded to "<stem>_bmp.png"; an Amplitude proxy names the texture directly.
    freq = parse_freq_tex_reference(data)
    if freq is not None:
        base = Path(freq.replace('\\', '/').replace(' ', '_')).stem.lower()
        return f'{base}{_FREQ_PNG_SUFFIX}'
    amp = parse_tex_reference(data)
    if amp is not None:
        return Path(amp.replace('\\', '/').replace(' ', '_')).stem.lower()
    return None


def _nearest_png(proxy: Path, candidates: Sequence[Path]) -> Path:
    proxy_parts = proxy.parts

    def score(candidate: Path) -> tuple[int, int]:
        parts = candidate.parts
        limit = min(len(proxy_parts), len(parts))
        shared = next((i for i in range(limit) if proxy_parts[i] != parts[i]), limit)
        return shared, -len(parts)  # Most path components shared, then the shallowest.

    return max(candidates, key=score)


def link_references(root: Path, *, copy: bool | None = None) -> int:
    """
    Resolve texture-reference proxies to the real PNG (post-extraction pass).

    For every ``.bmp``/``.tex`` proxy (see :py:func:`parse_tex_reference`) that has no PNG of its
    own, the real ``<name>.png`` is located anywhere under ``root`` and materialised in its place:
    a symlink on POSIX, a copy on Windows. The proxy is then deleted, since it only points at the
    real texture. When several textures share the name, the one nearest the proxy in the directory
    tree is chosen. The pass is idempotent: a proxy left beside a symlink by an earlier run is
    cleaned up on the next.

    Parameters
    ----------
    root : pathlib.Path
        The extraction root.
    copy : bool | None
        Copy the target instead of symlinking. When ``None``, copies on Windows and symlinks
        elsewhere.

    Returns
    -------
    int
        The number of references resolved (proxies replaced by a link or copy and removed).
    """
    if copy is None:
        copy = os.name == 'nt'
    png_by_stem: dict[str, list[Path]] = {}
    for png in root.rglob('*.png'):
        if not png.is_symlink():  # Index only real PNGs so proxies never chain to one another.
            png_by_stem.setdefault(png.stem.lower(), []).append(png)
    resolved = 0
    for proxy in root.rglob('*'):
        if proxy.suffix.lower() not in _REF_EXTS or proxy.is_symlink() or not proxy.is_file():
            continue
        dst = proxy.with_suffix('.png')
        if dst.is_symlink():  # Already materialised on a prior pass; drop the redundant proxy.
            proxy.unlink()
            resolved += 1
            continue
        if dst.exists():  # A real PNG (e.g. a decoded bitmap) already holds the slot.
            continue
        stem = _reference_png_stem(proxy.read_bytes())
        if stem is None:
            continue
        candidates = [png for png in png_by_stem.get(stem, ()) if png != dst]
        if not candidates:
            continue
        target = _nearest_png(proxy, candidates)
        if copy:
            shutil.copy2(target, dst)
        else:
            dst.symlink_to(os.path.relpath(target, proxy.parent))
        proxy.unlink()  # The proxy is only a pointer; the materialised PNG replaces it.
        resolved += 1
        log.debug('Resolved texture reference `%s` -> `%s`.', proxy.name, target.relative_to(root))
    return resolved
