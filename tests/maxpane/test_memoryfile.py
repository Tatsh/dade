from __future__ import annotations

import struct

import pytest

from dade.maxpane.memoryfile import (
    TAG_SIZES,
    BasicType,
    iter_values,
    read_chunk_header,
    read_int,
    read_string,
    read_vector3,
)


@pytest.mark.parametrize(('tag', 'payload', 'expected'), [
    (BasicType.INT8, b'\x7b', 123),
    (BasicType.INT8, b'\xff', -1),
    (BasicType.INT16, b'\x64\x5e', 24164),
    (BasicType.INT24, b'\x0f\xd0\x00', 53263),
    (BasicType.INT32, b'\x01\x02\x03\x04', 0x04030201),
    (BasicType.UINT8, b'\xff', 255),
    (BasicType.UINT16, b'\x00\x80', 32768),
])
def test_read_int(tag: int, payload: bytes, expected: int) -> None:
    value, end = read_int(bytes((tag,)) + payload, 0)
    assert value == expected
    assert end == 1 + len(payload)


def test_read_int_rejects_a_non_integer_tag() -> None:
    with pytest.raises(ValueError, match='Not an integer tag'):
        read_int(bytes((BasicType.ARRAY,)) + b'\x00', 0)


def test_read_vector3() -> None:
    data = bytes((BasicType.VECTOR3,)) + struct.pack('<3f', 1.5, -2.5, 3.5)
    assert read_vector3(data, 0) == ((1.5, -2.5, 3.5), 13)


def test_read_vector3_rejects_another_tag() -> None:
    with pytest.raises(ValueError, match='Not a vector tag'):
        read_vector3(bytes((BasicType.FLOAT,)) + bytes(4), 0)


def test_read_string() -> None:
    data = (bytes((BasicType.STRING, BasicType.INT8, 5)) + b'hello')
    assert read_string(data, 0) == ('hello', 8)


def test_read_string_with_a_wide_length() -> None:
    text = 'x' * 300
    data = bytes((BasicType.STRING, BasicType.INT16)) + (300).to_bytes(2, 'little') + text.encode()
    assert read_string(data, 0) == (text, 304)


def test_read_string_empty() -> None:
    assert read_string(bytes((BasicType.STRING, BasicType.INT8, 0)), 0) == ('', 3)


def test_read_string_rejects_another_tag() -> None:
    with pytest.raises(ValueError, match='Not a string tag'):
        read_string(bytes((BasicType.INT8, 1)), 0)


def test_iter_values_follows_a_string() -> None:
    data = (bytes((BasicType.STRING, BasicType.INT8, 3)) + b'abc' + bytes((BasicType.INT8, 9)))
    values = list(iter_values(data))
    assert [value.tag for value in values] == [BasicType.STRING, BasicType.INT8]
    assert values[0].payload == b'abc'
    assert values[0].end == 6
    assert values[1].payload == b'\x09'


def test_iter_values_stops_on_a_truncated_string() -> None:
    assert not list(iter_values(bytes((BasicType.STRING, BasicType.INT8, 40)) + b'short'))


def test_iter_values_stops_on_a_string_with_a_bad_length_tag() -> None:
    assert not list(iter_values(bytes((BasicType.STRING, 0xAA, 1, 1))))


def test_read_chunk_header() -> None:
    data = bytes((BasicType.CHUNK,)) + struct.pack('<3I', 7, 2, 128)
    assert read_chunk_header(data) == (7, 2, 128)


def test_read_chunk_header_rejects_another_tag() -> None:
    with pytest.raises(ValueError, match='Not a chunk tag'):
        read_chunk_header(bytes((BasicType.ARRAY,)))


def test_iter_values_walks_an_array() -> None:
    data = (bytes((BasicType.ARRAY,)) + bytes((BasicType.INT16,)) + b'\x02\x00' + bytes(
        (BasicType.VECTOR3,)) + struct.pack('<3f', 0.0, 1.0, 2.0) + bytes(
            (BasicType.VECTOR3,)) + struct.pack('<3f', 3.0, 4.0, 5.0))
    values = list(iter_values(data))
    assert [value.tag for value in values] == [
        BasicType.ARRAY, BasicType.INT16, BasicType.VECTOR3, BasicType.VECTOR3
    ]
    assert values[0].payload == b''


def test_iter_values_stops_at_an_unknown_tag() -> None:
    data = bytes((BasicType.INT8,)) + b'\x01' + b'\xaa' + b'rest'
    assert [value.offset for value in iter_values(data)] == [0]


def test_iter_values_stops_on_a_truncated_payload() -> None:
    assert not list(iter_values(bytes((BasicType.VECTOR3,)) + bytes(4)))


def test_iter_values_can_resume() -> None:
    data = b'\xaa' + bytes((BasicType.INT8,)) + b'\x05'
    assert [value.tag for value in iter_values(data, 1)] == [BasicType.INT8]


def test_tag_sizes_cover_every_fixed_width_tag() -> None:
    assert set(TAG_SIZES) == set(BasicType) - {BasicType.STRING}
