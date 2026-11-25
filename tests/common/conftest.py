from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


@pytest.fixture
def clear_font_caches() -> Iterator[None]:
    """
    Clear the cached font lookups before and after a test that patches them.

    Yields
    ------
    None
        Control while the caches are empty.
    """
    from dade.common.fonts import japanese_font_path, load_font
    japanese_font_path.cache_clear()
    load_font.cache_clear()
    yield
    japanese_font_path.cache_clear()
    load_font.cache_clear()


@pytest.fixture
def make_ps2_icon() -> Callable[..., bytes]:
    """
    Build a PS2 3D icon (``.ico``/``.icn``).

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``vertices``, ``anim``, ``magic``, ``frames``, ``texture``, and
        ``texture_type`` values. ``frames`` are pairs of a shape and its keys of time and weight,
        and ``texture`` is the bytes after the animation, a raw texture by default.
    """
    def build(*,
              vertices: int = 3,
              anim: int = 1,
              magic: int = 0x10000,
              frames: tuple[tuple[int, tuple[tuple[float, float], ...]],
                            ...] = ((0, ((0.0, 1.0),)),),
              texture: bytes | None = None,
              texture_type: int = 7) -> bytes:
        stride = 8 * anim + 16
        out = bytearray(struct.pack('<3IfI', magic, anim, texture_type, 1.0, vertices))
        for i in range(vertices):
            vertex = bytearray(stride)
            for shape in range(anim):
                struct.pack_into('<3h', vertex, 8 * shape, i * 100, i * 200 + shape * 4096, i * 300)
            struct.pack_into('<3h', vertex, 8 * anim, 0, 4096, 0)
            struct.pack_into('<2h', vertex, 8 * anim + 8, i * 512, i * 256)
            struct.pack_into('<4B', vertex, 8 * anim + 12, 128, 64, 0, 128)
            out += vertex
        out += struct.pack('<2If2I', 1, 120, 1.0, 0, len(frames))
        for shape, keys in frames:
            out += struct.pack('<2I', shape, len(keys))
            out += b''.join(struct.pack('<2f', *key) for key in keys)
        return bytes(out) + (bytes(range(256)) * (0x8000 // 256) if texture is None else texture)

    return build


@pytest.fixture
def make_icon_sys() -> Callable[..., bytes]:
    """
    Build a PS2 ``icon.sys`` save-metadata file.

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``title`` and ``magic`` values.
    """
    def build(*, title: str = 'AMPLITUDE', magic: bytes = b'PS2D') -> bytes:
        out = bytearray(0x1C8)
        out[0:4] = magic
        struct.pack_into('<H', out, 6, 5)
        struct.pack_into('<I', out, 0xC, 32)
        encoded = title.encode('shift_jis')
        out[0xC0:0xC0 + len(encoded)] = encoded
        out[0x108:0x108 + 10] = b'normal.ico'
        out[0x148:0x148 + 8] = b'copy.ico'
        out[0x188:0x188 + 10] = b'delete.ico'
        return bytes(out)

    return build
