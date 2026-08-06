"""
EA RenderWare ``STRM`` resource-pack (``.rpk``) reader.

After RefPack decompression the container is a ``STRM`` chunk holding ``AGRP``
asset groups (each with ``ASET`` 32-byte descriptors), an ``STRS`` string table and
the asset payloads. The Xbox360/PS3/Wii builds are big-endian; the PS2 build is
little-endian, where every tag is byte-reversed (``MRTS``/``PRGA``/``TESA``/``SRTS``)
and sizes/fields are little-endian. The first four bytes select which.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
import re
import struct

from . import refpack
from .namehash import name_hash

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .typing import Endian

__all__ = ('Asset', 'PackInfo', 'extract', 'parse', 'read_rpk')

#: Asset payload magic to output file extension for the raw dump.
_MAGIC_EXT: Mapping[bytes, str] = {
    b'ANIM': 'anim',
    b'BUTT': 'butt',
    b'FntX': 'fntx',
    b'MIXR': 'mixr',
    b'NPM7': 'npm7',
    b'PAMC': 'pamc',
    b'PAMX': 'xmap',
    b'SKUK': 'sku',
    b'VANB': 'vanb',
}
_EMBEDDED: Mapping[bytes, str] = {
    b'\x89PNG': 'png',
    b'OTTO': 'ttf',
    b'RIFF': 'wav',
    b'true': 'ttf',
    b'ttcf': 'ttf',
}
# (magic, endian, {logical tag: on-disk bytes}); PS2 tags are the BE names reversed.
_BE: tuple[bytes, Endian, Mapping[str, bytes]] = (b'STRM', '>', {
    'AGRP': b'AGRP',
    'ASET': b'ASET',
    'STRS': b'STRS'
})
_LE: tuple[bytes, Endian, Mapping[str, bytes]] = (b'MRTS', '<', {
    'AGRP': b'PRGA',
    'ASET': b'TESA',
    'STRS': b'SRTS'
})
_TYPE_TOKEN_RE = re.compile(r'[A-Z]{2,5}\Z')
_MIN_CHUNK_SIZE = 8
"""Minimum size of a tagged chunk (its 4-byte tag plus 4-byte size).

:meta hide-value:
"""
_PRINTABLE_MIN = 0x30
"""Lowest byte value treated as a printable magic character (ASCII ``0``).

:meta hide-value:
"""
_PRINTABLE_MAX = 0x7A
"""Highest byte value treated as a printable magic character (ASCII ``z``).

:meta hide-value:
"""


class Asset(NamedTuple):
    """A single asset descriptor (``ASET``/``TESA`` record) within a pack."""

    name_hash: int
    """32-bit name hash, shared across platforms for the same logical asset."""
    type_id: int
    """Engine type identifier."""
    offset: int
    """Payload offset within the decompressed pack buffer."""
    size: int
    """Payload size in bytes."""
    extra: int
    """An auxiliary field whose meaning varies by type."""


class PackInfo(NamedTuple):
    """The parsed contents of a ``.rpk`` pack."""

    assets: tuple[Asset, ...]
    """All asset descriptors in pack order."""
    strings: tuple[str, ...]
    """The ``STRS`` string table (type tokens interleaved with paths)."""
    raw: bytes
    """The full decompressed pack buffer that ``offset``/``size`` index into."""
    endian: Endian
    """Byte order of the container (``'<'`` PS2, ``'>'`` otherwise)."""


def read_rpk(path: Path) -> bytes:
    """
    Read a ``.rpk`` file, RefPack-decompressing it when needed.

    Parameters
    ----------
    path : pathlib.Path
        The pack file.

    Returns
    -------
    bytes
        The decompressed container bytes.
    """
    raw = path.read_bytes()
    return refpack.decompress(raw)[0] if refpack.is_refpack(raw) else raw


def parse(path: Path) -> PackInfo:
    """
    Parse a ``.rpk`` pack into its asset descriptors and string table.

    Parameters
    ----------
    path : pathlib.Path
        The pack file.

    Returns
    -------
    PackInfo
        The parsed assets, strings, raw buffer and detected endianness.

    Raises
    ------
    ValueError
        If the container magic is neither ``STRM`` nor ``MRTS``.
    """
    buf = read_rpk(path)
    if buf[:4] == _BE[0]:
        _, endian, tags = _BE
    elif buf[:4] == _LE[0]:
        _, endian, tags = _LE
    else:
        msg = f'{path}: no STRM/MRTS (got {buf[:4]!r})'
        raise ValueError(msg)
    length = len(buf)
    assets: list[Asset] = []
    strings: tuple[str, ...] = ()
    i = 8  # Skip the STRM/MRTS header.
    while i + 8 <= length:
        tag, size = buf[i:i + 4], struct.unpack_from(endian + 'I', buf, i + 4)[0]
        if size < _MIN_CHUNK_SIZE or i + size > length + _MIN_CHUNK_SIZE:
            break
        if tag == tags['AGRP']:
            assets.extend(_iter_assets(buf, i, size, endian, tags['ASET']))
            i += size
        elif tag == tags['STRS']:
            strings = tuple(p.decode('latin1') for p in buf[i + 8:i + size].split(b'\x00') if p)
            i += size
        else:
            break  # Reached the asset-data region; stop the directory scan.
    return PackInfo(tuple(assets), strings, buf, endian)


def _iter_assets(buf: bytes, group: int, size: int, endian: Endian, aset_tag: bytes) -> list[Asset]:
    out: list[Asset] = []
    j, end = group + 8, group + size
    while j + 8 <= end:
        ct, cs = buf[j:j + 4], struct.unpack_from(endian + 'I', buf, j + 4)[0]
        if ct == aset_tag:
            f = struct.unpack_from(endian + '8I', buf, j + 8)
            out.append(Asset(f[0], f[1], f[4], f[5], f[6]))
        if cs < _MIN_CHUNK_SIZE:
            break
        j += cs
    return out


def _ext_for(magic: bytes, head: bytes) -> str:
    for sig, ext in _EMBEDDED.items():
        if head.startswith(sig):
            return ext
    if head[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if head[:2] == b'BM':
        return 'bmp'
    if magic in _MAGIC_EXT:
        return _MAGIC_EXT[magic]
    if all(_PRINTABLE_MIN <= b <= _PRINTABLE_MAX and chr(b).isalnum() for b in magic):
        return magic.decode('latin1').strip().lower() or 'bin'
    return 'bin'


def _tga_names(strings: tuple[str, ...]) -> list[str]:
    names, current = [], None
    for s in strings:
        if _TYPE_TOKEN_RE.match(s):
            current = s
        elif current == 'TGA' and ('\\' in s or '/' in s or '.' in s):
            names.append(Path(s.replace('\\', '/')).stem)
    return names


def _build_name_index(strings: tuple[str, ...]) -> dict[int, str]:
    """
    Map each asset ``name_hash`` to the real name stem from the ``STRS`` table.

    Every path/name-like string in the string table is hashed with the engine name hash
    (:py:func:`~destin.monopoly08.namehash.name_hash`, which matches the ``ASET``
    ``name_hash``), giving a robust hash-keyed name lookup instead of relying on the
    positional ``TGA`` ordering.

    Parameters
    ----------
    strings : tuple[str, ...]
        The ``STRS`` string table.

    Returns
    -------
    dict[int, str]
        A mapping of ``{name_hash: stem}``.
    """
    index: dict[int, str] = {}
    for s in strings:
        if '\\' not in s and '/' not in s and '.' not in s:
            continue
        stem = Path(s.replace('\\', '/')).stem
        if stem:
            index.setdefault(name_hash(stem), stem)
    return index


def extract(path: Path) -> tuple[Path, int]:
    """
    Extract every asset of a ``.rpk`` pack into a sibling ``<stem>/`` directory.

    Texture assets are named from the ``STRS`` ``TGA`` path list (in order); other
    assets fall back to ``asset<NNNN>_<hash>`` names. A ``_manifest.tsv`` is written.

    Parameters
    ----------
    path : pathlib.Path
        The pack file.

    Returns
    -------
    tuple[pathlib.Path, int]
        The output directory and the number of assets written.
    """
    info = parse(path)
    tga = _tga_names(info.strings)
    name_index = _build_name_index(info.strings)
    out_dir = path.with_suffix('')
    out_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    manifest = ['name\tmagic\toffset\tsize\tnameHash\ttypeId\n']
    tex_i = 0
    for idx, a in enumerate(info.assets):
        magic = info.raw[a.offset:a.offset + 4]
        ext = _ext_for(magic, info.raw[a.offset:a.offset + 8])
        resolved = name_index.get(a.name_hash)
        if resolved is not None:
            base = resolved  # robust: name matched by engine name hash
        elif magic == b'PAMX' and tex_i < len(tga):
            base = tga[tex_i]
            tex_i += 1
        else:
            base = f'asset{idx:04d}_{a.name_hash:08x}'
        name = f'{base}.{ext}'
        n = 1
        while name in used:
            name = f'{base}_{n}.{ext}'
            n += 1
        used.add(name)
        (out_dir / name).write_bytes(info.raw[a.offset:a.offset + a.size])
        mk = magic.hex() if not magic.isalpha() else magic.decode('latin1')
        manifest.append(f'{name}\t{mk}\t{a.offset}\t{a.size}\t{a.name_hash:08x}\t{a.type_id:08x}\n')
    (out_dir / '_manifest.tsv').write_text(''.join(manifest))
    return out_dir, len(info.assets)
