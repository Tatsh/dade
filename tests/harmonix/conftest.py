"""Shared pytest configuration and synthetic asset builders for the ``harmonix`` tests."""
from __future__ import annotations

from typing import TYPE_CHECKING
import gzip
import struct
import zlib

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from dade.harmonix.typing import DataArrayNode

_SENTINEL = b'\xad\xde\xad\xde'
"""The Milo inter-object body terminator.

:meta hide-value:
"""
_BLOCK = 0x800
"""The FreQuency ARK data block size.

:meta hide-value:
"""


def _rstr(text: str) -> bytes:
    return struct.pack('<I', len(text)) + text.encode()


@pytest.fixture
def make_amp_ark() -> Callable[[Sequence[tuple[str, bytes]]], bytes]:
    """
    Build an Amplitude (magic-less, version-first) ARK archive.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[str, bytes]]], bytes]
        A callable turning ``(path, data)`` pairs into a complete archive.
    """
    def build(entries: Sequence[tuple[str, bytes]]) -> bytes:
        names: list[str] = []

        def intern(name: str) -> int:
            if name not in names:
                names.append(name)
            return names.index(name)

        buckets = []
        for path, _ in entries:
            dname, _, fname = path.rpartition('/')
            buckets.append((intern(fname), intern(dname) if dname else 0xFFFFFFFF))
        pool = bytearray()
        offsets = []
        for name in names:
            offsets.append(len(pool))
            pool += name.encode() + b'\0'
        n_buckets = len(names)
        dir_end = 8 + len(entries) * 20 + 4 + len(pool) + 4 + n_buckets * 4
        out = bytearray(struct.pack('<II', 2, len(entries)))
        pos = dir_end
        for (_, data), (file_bkt, dir_bkt) in zip(entries, buckets, strict=True):
            out += struct.pack('<5I', pos, file_bkt, dir_bkt, len(data), 0)
            pos += len(data)
        out += struct.pack('<I', len(pool)) + bytes(pool)
        out += struct.pack('<I', n_buckets) + struct.pack(f'<{n_buckets}I', *offsets)
        for _, data in entries:
            out += data
        return bytes(out)

    return build


@pytest.fixture
def make_freq_ark() -> Callable[[Sequence[tuple[str, bytes]]], bytes]:
    r"""
    Build a FreQuency (``ARK\0``) ARK archive.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[str, bytes]]], bytes]
        A callable turning ``(path, data)`` pairs into a complete archive.
    """
    def build(entries: Sequence[tuple[str, bytes]]) -> bytes:
        dirs: list[str] = []
        files: list[tuple[str, int]] = []
        for path, _ in entries:
            dname, _, fname = path.rpartition('/')
            if dname not in dirs:
                dirs.append(dname)
            files.append((fname, dirs.index(dname)))
        n_files, n_dirs = len(entries), len(dirs)
        frec_off = 0x100
        drec_off = frec_off + n_files * 24
        pool_off = drec_off + n_dirs * 8
        pool = bytearray()
        name_offs = []
        for fname, _ in files:
            name_offs.append(pool_off + len(pool))
            pool += fname.encode() + b'\0'
        dir_offs = []
        for dname in dirs:
            dir_offs.append(pool_off + len(pool))
            pool += dname.encode() + b'\0'
        data_off = -(-(pool_off + len(pool)) // _BLOCK) * _BLOCK
        out = bytearray(data_off)
        struct.pack_into('<10I', out, 0, 0x004B5241, 2, frec_off, n_files, drec_off, n_dirs,
                         pool_off, n_files + n_dirs, data_off, _BLOCK)
        pos = data_off
        for i, (_, data) in enumerate(entries):
            packed = ((pos % _BLOCK) << 16) | files[i][1]
            struct.pack_into('<6I', out, frec_off + i * 24, 0, name_offs[i], packed, pos // _BLOCK,
                             len(data), len(data))
            pos += len(data)
        for i, off in enumerate(dir_offs):
            struct.pack_into('<2I', out, drec_off + i * 8, 0, off)
        out[pool_off:pool_off + len(pool)] = pool
        for _, data in entries:
            out += data
        return bytes(out)

    return build


@pytest.fixture
def make_hmx_bitmap() -> Callable[..., bytes]:
    """
    Build a console-native HMX bitmap.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``width``, ``height``, and a keyword ``bpp`` and returning the bitmap.
    """
    def build(width: int = 4, height: int = 4, *, bpp: int = 8) -> bytes:
        header = bytes((0, bpp, 3, 1)) + struct.pack('<HH', width, height) + bytes(8)
        if bpp == 32:
            return header + bytes(i % 256 for i in range(width * height * 4))
        ncol = 1 << bpp
        palette = b''.join(
            bytes((i & 0xFF, (i * 3) & 0xFF, (i * 7) & 0xFF, 64)) for i in range(ncol))
        n_pixels = width * height if bpp == 8 else (width * height + 1) // 2
        return header + palette + bytes(i % ncol for i in range(n_pixels))

    return build


@pytest.fixture
def make_abm() -> Callable[..., bytes]:
    """
    Build a FreQuency ``ABitmap`` (``.abm``).

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``width``, ``height``, and keyword ``bpp`` and ``rle`` flags.
    """
    def build(width: int = 4, height: int = 4, *, bpp: int = 8, rle: bool = False) -> bytes:
        stride = width * bpp // 8
        if bpp == 32:
            pixels = bytes(i % 256 for i in range(width * height * 4))
            return (bytes(5) + bytes(1) + struct.pack('<HHH', width, height, stride) + bytes(4) +
                    struct.pack('<I', len(pixels)) + bytes(4) + pixels)
        target = stride * height
        raw = bytes(i % 256 for i in range(target))
        # Alternate literal runs (control bit set) with single-byte repeat runs.
        region = (b''.join(
            bytes((0x81 if i % 2 else 0x01, byte)) for i, byte in enumerate(raw)) if rle else raw)
        palette = b''.join(
            bytes((i & 0xFF, (i * 5) & 0xFF, (i * 9) & 0xFF, 255)) for i in range(256))
        return (bytes(5) + bytes(1) + struct.pack('<HHH', width, height, stride) + bytes(4) +
                struct.pack('<I', len(region)) + bytes(12) + palette + region)

    return build


@pytest.fixture
def make_dtb() -> Callable[..., bytes]:
    """
    Build a compiled version-2 Harmonix DataArray.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the root element list and a keyword ``symbols`` sequence.
    """
    def node(items: Sequence[DataArrayNode]) -> bytes:
        n_tag_words = (len(items) + 0xF) >> 4
        tags = [0] * n_tag_words
        payload = bytearray()
        for i, item in enumerate(items):
            if isinstance(item, str):
                tag = 1
                payload += struct.pack('<I', len(item)) + item.encode()
            elif isinstance(item, float):
                tag = 2
                payload += struct.pack('<f', item)
            elif isinstance(item, int):
                tag = 0
                payload += struct.pack('<i', item)
            else:
                tag = 3
                payload += node(item)
            tags[i >> 4] |= tag << ((i & 0xF) * 2)
        head = struct.pack('<HHHI', len(items), 0, 0, 0)
        return head + struct.pack(f'<{n_tag_words}I', *tags) + bytes(payload)

    def build(items: Sequence[DataArrayNode], *, symbols: Sequence[str] = ()) -> bytes:
        out = bytearray(b'\x02' + struct.pack('<I', len(symbols)))
        for symbol in symbols:
            out += _rstr(symbol)
        return bytes(out + node(items))

    return build


@pytest.fixture
def make_milo() -> Callable[..., bytes]:
    """
    Build a Milo/Rnd archive holding the given ``(type, name, body)`` objects.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking the objects and keyword ``version`` and ``magic`` values.
    """
    def build(objects: Sequence[tuple[str, str, bytes]],
              *,
              version: int = 10,
              magic: int = 0xCBBEDEAF) -> bytes:
        directory = bytearray(struct.pack('<II', version, len(objects)))
        for typ, name, _ in objects:
            if version == 6:
                directory += typ.encode() + b'\0' + name.encode() + b'\0\x01'
            else:
                directory += _rstr(typ) + _rstr(name)
        if version == 6:
            directory += _SENTINEL
        for _, _, body in objects:
            directory += body + _SENTINEL
        if version == 6:
            return bytes(directory)
        if magic == 0xCABEDEAF:
            return struct.pack('<4I', magic, 0x14, 1, len(directory)) + bytes(4) + bytes(directory)
        block = (zlib.compress(bytes(directory)) if magic == 0xCBBEDEAF else gzip.compress(
            bytes(directory)))
        return (struct.pack('<4I', magic, 0x14, 1, len(block)) + struct.pack('<I', len(block)) +
                block)

    return build


@pytest.fixture
def make_vag() -> Callable[..., bytes]:
    """
    Build a run of PS2 VAG-ADPCM frames.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking a frame count and keyword ``shift``, ``predictor``, and ``flag`` values.
    """
    def build(frames: int = 2, *, shift: int = 12, predictor: int = 1, flag: int = 1) -> bytes:
        out = bytearray()
        for i in range(frames):
            out += bytes(((predictor << 4) | shift, flag if i == frames - 1 else 0))
            out += bytes((i + n) % 256 for n in range(14))
        return bytes(out)

    return build


@pytest.fixture
def make_samp_bank() -> Callable[[Sequence[tuple[str, int, int]]], bytes]:
    """
    Build a ``SAMP`` sample-bank index from ``(name, rate, offset)`` descriptors.

    Returns
    -------
    collections.abc.Callable[[collections.abc.Sequence[tuple[str, int, int]]], bytes]
        A callable returning the complete ``.bnk`` contents.
    """
    def build(samples: Sequence[tuple[str, int, int]]) -> bytes:
        table = bytearray()
        names = bytearray()
        for name, rate, offset in samples:
            record = bytearray(22)
            struct.pack_into('<IIH', record, 0, 1, 1, rate)
            struct.pack_into('<I', record, 18, offset)
            table += record
            names += _rstr(name)
        return (b'SAMP' + struct.pack('<I',
                                      len(samples) * 22) + bytes(table) + b'SANM' + bytes(8) +
                bytes(names))

    return build


@pytest.fixture
def make_sd_bank() -> Callable[..., bytes]:
    """
    Build a FreQuency SCEI (``sceSdBank``) ``.hd`` header.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking ``(bd_offset, rate, flags)`` VAG records and a keyword ``bd_size``.
    """
    def build(vags: Sequence[tuple[int, int, int]], *, bd_size: int = 4096) -> bytes:
        out = bytearray(b'IECSsreV' + bytes(8))
        out += b'IECSdaeH' + bytes(8) + struct.pack('<I', bd_size) + bytes(12)
        len(out)
        out += b'IECSigaV' + bytes(4) + struct.pack('<I', len(vags))
        record_off = 16 + len(vags) * 4
        out += struct.pack(f'<{len(vags)}I', *(record_off + i * 8 for i in range(len(vags))))
        for bd_offset, rate, flags in vags:
            out += struct.pack('<IHH', bd_offset, rate, flags)
        return bytes(out)

    return build


@pytest.fixture
def make_v14_mesh() -> Callable[..., bytes]:
    """
    Build an Amplitude version-14 ``RndMesh`` body.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``material``, ``vertices``, and ``faces`` values.
    """
    def build(*,
              material: str = 'ship.mat',
              vertices: int = 3,
              faces: Sequence[tuple[int, int, int]] = ((0, 1, 2),),
              handles: Sequence[str] = (),
              transform_version: int = 0) -> bytes:
        out = bytearray(struct.pack('<II', 14, transform_version) + bytes(96))
        out += struct.pack('<I', len(handles))  # Child handle list.
        for handle in handles:
            out += _rstr(handle)
        if transform_version > 0:
            out += bytes(16)  # Constraint and pivot.
        if 2 <= transform_version <= 4:
            out += b'\0'
        out += struct.pack('<I', 0) + b'\0' + struct.pack('<I', 0)  # RndDrawable.
        out += struct.pack('<I', 0) + struct.pack('<I', 0)  # RndCollideable.
        out += bytes(8)
        out += _rstr(material) + _rstr('') + _rstr('')
        out += bytes(16)  # Bounds.
        out += _rstr('') + bytes(4) + b'\0'
        out += struct.pack('<I', vertices)
        for i in range(vertices):
            vertex = bytearray(56)
            struct.pack_into('<3f', vertex, 0, float(i), float(i) * 2, float(i) * 3)
            struct.pack_into('<3f', vertex, 20, 0.0, 1.0, 0.0)
            struct.pack_into('<2f', vertex, 48, i / 4, i / 8)
            out += vertex
        out += struct.pack('<I', len(faces))
        for face in faces:
            out += struct.pack('<3H', *face)
        return bytes(out)

    return build


@pytest.fixture
def make_v10_mesh() -> Callable[..., bytes]:
    """
    Build a FreQuency version-10 ``RndMesh`` body.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``vertices``, ``faces``, and a ``decoys`` flag.
    """
    def build(*,
              vertices: int = 3,
              faces: Sequence[tuple[int, int, int]] = ((0, 1, 2),),
              decoys: bool = False) -> bytes:
        out = bytearray(struct.pack('<II', 10, 0))
        if decoys:
            # A count whose vertex block holds non-finite positions, then one whose face count is
            # zero, then one whose face indices are out of range: each is rejected by the scan.
            out += struct.pack('<I', 3) + b'\xff' * (3 * 56) + struct.pack('<I', 1)
            out += struct.pack('<3H', 0, 1, 2) + bytes(2)
            out += struct.pack('<I', 3) + bytes(3 * 56) + struct.pack('<I', 0)
            out += struct.pack('<I', 3) + bytes(3 * 56) + struct.pack('<I', 1)
            out += struct.pack('<3H', 9, 9, 9) + bytes(2)
        out += struct.pack('<I', vertices)
        for i in range(vertices):
            vertex = bytearray(56)
            struct.pack_into('<3f', vertex, 0, float(i), float(i) * 2, float(i) * 3)
            struct.pack_into('<3f', vertex, 12, 1.0, 0.0, 0.0)
            struct.pack_into('<2f', vertex, 28, i / 4, i / 8)
            out += vertex
        out += struct.pack('<I', len(faces))
        for face in faces:
            out += struct.pack('<3H', *face)
        return bytes(out)

    return build
