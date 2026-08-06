from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def make_ps2_icon() -> Callable[..., bytes]:
    """
    Build a PS2 3D icon (``.ico``/``.icn``).

    Returns
    -------
    collections.abc.Callable[..., bytes]
        A callable taking keyword ``vertices``, ``anim``, and ``magic`` values.
    """
    def build(*, vertices: int = 3, anim: int = 1, magic: int = 0x10000) -> bytes:
        stride = 8 * anim + 16
        out = bytearray(struct.pack('<4I', magic, anim, 0, 0) + struct.pack('<I', vertices))
        for i in range(vertices):
            vertex = bytearray(stride)
            struct.pack_into('<3h', vertex, 0, i * 100, i * 200, i * 300)
            struct.pack_into('<3h', vertex, 8 * anim, 0, 4096, 0)
            struct.pack_into('<2h', vertex, 8 * anim + 8, i * 512, i * 256)
            out += vertex
        return bytes(out) + bytes(range(256)) * (0x8000 // 256)

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
