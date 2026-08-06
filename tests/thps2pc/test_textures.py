"""Tests for :mod:`destin.thps2pc.textures`."""
from __future__ import annotations

from destin.thps2pc import textures
from destin.thps2pc.test_utils import psx_lighting
import pytest


def test_parse_lighting_walks_past_the_chunk_list() -> None:
    data = psx_lighting(checksums=(0xABCDEF01,), chunks=((0x52454948, b'\x00' * 8),))
    assert textures.parse_lighting(data).checksums == (0xABCDEF01,)


def test_parse_lighting_reads_every_table(lighting_bytes: bytes) -> None:
    tables = textures.parse_lighting(lighting_bytes)
    assert tables.checksums == (0xA1B2C3D4, 0x11223344)
    assert set(tables.cluts_16) == {7}
    assert set(tables.cluts_256) == {9}
    assert len(tables.instances) == 3


def test_instances_resolve_their_checksum(lighting_bytes: bytes) -> None:
    tables = textures.parse_lighting(lighting_bytes)
    assert [i.checksum for i in tables.instances] == [0xA1B2C3D4, 0x11223344, 0xA1B2C3D4]


def test_instance_bit_depth(lighting_bytes: bytes) -> None:
    tables = textures.parse_lighting(lighting_bytes)
    assert tables.instances[0].is_4bpp
    assert not tables.instances[1].is_4bpp


@pytest.mark.parametrize(('value', 'expected'), [(0x0000, (255, 0, 255)), (0x7C1F, (255, 0, 255)),
                                                 (0x001F, (255, 0, 0)), (0x03E0, (0, 255, 0)),
                                                 (0x7C00, (0, 0, 255)), (0x7FFF, (255, 255, 255))])
def test_bgr555_to_rgb(value: int, expected: tuple[int, int, int]) -> None:
    assert textures.bgr555_to_rgb(value) == expected


def test_decode_instance_unpacks_4bpp(lighting_bytes: bytes) -> None:
    tables = textures.parse_lighting(lighting_bytes)
    pixels = textures.decode_instance(lighting_bytes, tables.instances[0], tables)
    assert pixels == bytes((0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 0, 255))


def test_decode_instance_unpacks_8bpp(lighting_bytes: bytes) -> None:
    tables = textures.parse_lighting(lighting_bytes)
    pixels = textures.decode_instance(lighting_bytes, tables.instances[1], tables)
    assert pixels == bytes((255, 255, 255, 255, 0, 255))


def test_decode_instance_returns_none_for_a_missing_palette(lighting_bytes: bytes) -> None:
    tables = textures.parse_lighting(lighting_bytes)
    assert textures.decode_instance(lighting_bytes, tables.instances[2], tables) is None


def test_iter_decoded_skips_unresolvable_instances(lighting_bytes: bytes) -> None:
    tables = textures.parse_lighting(lighting_bytes)
    decoded = list(textures.iter_decoded(lighting_bytes, tables))
    assert [instance.clut_id for instance, _ in decoded] == [7, 9]


def test_to_ppm_writes_a_binary_header() -> None:
    assert textures.to_ppm(b'\x01\x02\x03', 1, 1) == b'P6\n1 1\n255\n\x01\x02\x03'
