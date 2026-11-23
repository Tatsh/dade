"""Tests for Mario Kart World BNTX decoding."""
from __future__ import annotations

from io import BytesIO
from typing import cast
import struct

from PIL import Image
import pytest

from dade.mkw.texture import decode_texture, texture_count, texture_name


def _archive(channel: int,
             payload: bytes = b'\x00',
             *,
             width: int = 1,
             height: int = 1,
             block_height_log2: int = 0) -> bytes:
    archive = bytearray(max(0x600, 0x500 + len(payload)))
    archive[:4] = b'BNTX'
    struct.pack_into('<I', archive, 0x24, 1)
    struct.pack_into('<Q', archive, 0x28, 0x100)
    struct.pack_into('<Q', archive, 0x100, 0x120)
    archive[0x120:0x124] = b'BRTI'
    struct.pack_into('<I', archive, 0x13C, channel << 8)
    struct.pack_into('<II', archive, 0x144, width, height)
    struct.pack_into('<I', archive, 0x154, block_height_log2)
    struct.pack_into('<I', archive, 0x170, len(payload))
    struct.pack_into('<Q', archive, 0x180, 0x400)
    struct.pack_into('<Q', archive, 0x3C0, 0x500)
    struct.pack_into('<H', archive, 0x400, 4)
    archive[0x402:0x406] = b'test'
    archive[0x500:0x500 + len(payload)] = payload
    return bytes(archive)


def _pixel(data: bytes) -> tuple[int, int, int, int]:
    with Image.open(BytesIO(decode_texture(data))) as image:
        return cast('tuple[int, int, int, int]', image.getpixel((0, 0)))


def test_texture_metadata_and_index_errors() -> None:
    data = _archive(0x0B, bytes((1, 2, 3, 4)))
    assert texture_count(data) == 1
    assert texture_name(data, 0) == 'test'
    with pytest.raises(ValueError, match='texture index'):
        decode_texture(data, 1)
    with pytest.raises(ValueError, match='texture index'):
        decode_texture(data, -1)


@pytest.mark.parametrize('data', [b'', b'BAD!' + bytes(0x300), b'BNTX' + bytes(20)])
def test_texture_rejects_invalid_header(data: bytes) -> None:
    with pytest.raises(ValueError, match='Invalid BNTX file'):
        texture_count(data)


def test_texture_rejects_invalid_table_and_entry() -> None:
    archive = bytearray(_archive(0x0B, bytes(4)))
    struct.pack_into('<Q', archive, 0x28, len(archive) - 4)
    with pytest.raises(ValueError, match='texture table'):
        decode_texture(bytes(archive))
    archive = bytearray(_archive(0x0B, bytes(4)))
    archive[0x120:0x124] = b'NOPE'
    with pytest.raises(ValueError, match='no BRTI'):
        decode_texture(bytes(archive))


@pytest.mark.parametrize(
    ('channel', 'payload', 'expected'),
    [(0x02, b'\x7f', (127, 127, 127, 255)), (0x09, bytes((20, 200)), (20, 20, 20, 255)),
     (0x0A, struct.pack('<H', 32768), (127, 127, 127, 255)),
     (0x12, struct.pack('<HH', 65535, 32768), (255, 127, 0, 255)),
     (0x0B, bytes((11, 22, 33, 44)), (11, 22, 33, 44)),
     (0x0C, bytes((11, 22, 33, 44)), (33, 22, 11, 44)),
     (0x15, struct.pack('<HHHH', 65535, 0, 32768, 257), (255, 0, 127, 1)),
     (0x19, struct.pack('<ffff', 1.5, -0.5, float('nan'), 0.5), (255, 0, 0, 127))])
def test_uncompressed_pixel_formats(channel: int, payload: bytes, expected: tuple[int, int, int,
                                                                                  int]) -> None:
    assert _pixel(_archive(channel, payload)) == expected


@pytest.mark.parametrize(('field', 'value'), [(0x144, 0), (0x144, 16385), (0x148, 0),
                                              (0x148, 16385), (0x170, 0x1000), (0x154, 6)])
def test_texture_rejects_invalid_bounds(field: int, value: int) -> None:
    archive = bytearray(_archive(0x0B, bytes(4)))
    struct.pack_into('<I', archive, field, value)
    with pytest.raises(ValueError, match='image bounds'):
        decode_texture(bytes(archive))


def test_texture_rejects_unsupported_channel() -> None:
    with pytest.raises(ValueError, match='Unsupported BNTX channel 0x01'):
        decode_texture(_archive(0x01))


def test_texture_rejects_truncated_swizzled_blocks() -> None:
    with pytest.raises(ValueError, match='image data is truncated'):
        decode_texture(_archive(0x0B, b'\x01', width=2))


@pytest.mark.parametrize('channel', [0x1A, 0x1C, 0x1D, 0x1E, 0x1F, 0x20])
def test_block_compressed_formats(channel: int, monkeypatch: pytest.MonkeyPatch) -> None:
    from dade.mkw import texture

    observed: list[tuple[bytes, int, int]] = []

    def decode(blocks: bytes, width: int, height: int) -> bytes:
        observed.append((blocks, width, height))
        return bytes((9, 8, 7, 255)) * 16

    monkeypatch.setitem(vars(texture)['_DECODERS'], channel, decode)
    payload = bytes(range(8 if channel in {0x1A, 0x1D} else 16))
    assert _pixel(_archive(channel, payload, width=4, height=4)) == (7, 8, 9, 255)
    assert observed == [(payload, 4, 4)]


def test_compressed_texture_uses_bgra_output(monkeypatch: pytest.MonkeyPatch) -> None:
    archive = bytearray(0x600)
    archive[:4] = b'BNTX'
    struct.pack_into('<I', archive, 0x24, 1)
    struct.pack_into('<Q', archive, 0x28, 0x100)
    struct.pack_into('<Q', archive, 0x100, 0x120)
    archive[0x120:0x124] = b'BRTI'
    struct.pack_into('<I', archive, 0x13C, 0x2D00)
    struct.pack_into('<II', archive, 0x144, 4, 4)
    struct.pack_into('<I', archive, 0x170, 16)
    struct.pack_into('<Q', archive, 0x3C0, 0x500)
    monkeypatch.setattr('dade.mkw.texture.texture2ddecoder.decode_astc', lambda *_: bytes(
        (10, 20, 30, 255)) * 16)

    with Image.open(BytesIO(decode_texture(bytes(archive)))) as image:
        assert image.getpixel((0, 0)) == (30, 20, 10, 255)


def test_texture_uses_recorded_block_height(monkeypatch: pytest.MonkeyPatch) -> None:
    archive = bytearray(0xD00)
    archive[:4] = b'BNTX'
    struct.pack_into('<I', archive, 0x24, 1)
    struct.pack_into('<Q', archive, 0x28, 0x100)
    struct.pack_into('<Q', archive, 0x100, 0x120)
    archive[0x120:0x124] = b'BRTI'
    struct.pack_into('<I', archive, 0x13C, 0x2D00)
    struct.pack_into('<II', archive, 0x144, 20, 36)
    struct.pack_into('<I', archive, 0x154, 1)
    struct.pack_into('<I', archive, 0x170, 0x800)
    struct.pack_into('<Q', archive, 0x3C0, 0x500)
    archive[0x700:0x710] = b'\xAB' * 16
    archive[0x900:0x910] = b'\xCD' * 16
    decoded = []

    def record_blocks(blocks: bytes, *_: int) -> bytes:
        decoded.append(blocks)
        return bytes((10, 20, 30, 255)) * (20 * 36)

    monkeypatch.setattr('dade.mkw.texture.texture2ddecoder.decode_astc', record_blocks)
    decode_texture(bytes(archive))
    assert decoded[0][8 * 5 * 16:8 * 5 * 16 + 16] == b'\xAB' * 16
    assert decoded[0][4 * 16:5 * 16] == b'\xCD' * 16
