from __future__ import annotations

from typing import TYPE_CHECKING
import struct

import pytest

from dade.maxpayne.character import InvalidCharacterError, read_animation, read_weights

if TYPE_CHECKING:
    from collections.abc import Callable

_CHUNK = 0x0C
_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)


def _chunk(identifier: int, version: int, body: bytes) -> bytes:
    return bytes((_CHUNK,)) + struct.pack('<3I', identifier, version, len(body) + 13) + body


@pytest.mark.parametrize('version', [0, 1])
def test_read_weights_reads_either_layout(make_weights: Callable[..., bytes], version: int) -> None:
    weights = read_weights(make_weights(version=version))
    assert weights.bones == ('Pelvis', 'Head')
    assert weights.meshes == ('body',)
    assert weights.influences[0] == ((0, 1.0),)
    assert weights.influences[1] == ((0, 0.25), (1, 0.75))
    assert weights.influences[2] == ((1, 1.0),)


def test_read_weights_leaves_an_unlisted_vertex_unbound(make_weights: Callable[..., bytes]) -> None:
    weights = read_weights(make_weights((((0, 1.0),), (), ((1, 1.0),))))
    assert weights.influences[1] == ()


def test_read_weights_reads_a_third_influence(make_weights: Callable[..., bytes]) -> None:
    weights = read_weights(make_weights((((0, 0.5), (1, 0.25), (0, 0.25)),)))
    assert len(weights.influences[0]) == 3


def test_read_weights_rejects_another_chunk() -> None:
    with pytest.raises(InvalidCharacterError, match='Not a skin weight chunk'):
        read_weights(_chunk(0x00010012, 0, b''))


def test_read_weights_rejects_a_stream_that_is_not_chunked() -> None:
    with pytest.raises(InvalidCharacterError, match='Not a chunk tag'):
        read_weights(b'\x00')


def test_read_weights_rejects_a_weight_that_is_not_a_float() -> None:
    # One rigid vertex whose weight is an integer tag.
    body = b'\x14\x01' + b'\x14\x00' + b'\x14\x00' + b'\x14\x01'
    with pytest.raises(InvalidCharacterError, match='Expected a float'):
        read_weights(_chunk(0x00010014, 0, body))


def test_read_weights_rejects_a_missing_array_marker() -> None:
    with pytest.raises(InvalidCharacterError, match='Expected an array'):
        read_weights(_chunk(0x00010014, 1, b'\x14\x00'))


def _small(value: int) -> bytes:
    return bytes((0x14, value))


def _text(value: str) -> bytes:
    return b'\x0d' + _small(len(value)) + value.encode()


def _array(values: bytes, count: int) -> bytes:
    return b'\x1c' + _small(count) + values


def test_read_weights_rejects_an_influence_range_past_the_arrays() -> None:
    # One vertex whose influences start at 5, beyond the single influence stored.
    body = (_array(_text('body'), 1) + _array(_text('Pelvis'), 1) + _array(_small(5), 1) +
            _array(_small(1), 1) + _array(_small(0), 1) +
            _array(b'\x09' + struct.pack('<f', 1.0), 1))
    with pytest.raises(InvalidCharacterError, match='runs past'):
        read_weights(_chunk(0x00010014, 1, body))


def test_read_weights_rejects_a_truncated_stream(make_weights: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidCharacterError):
        read_weights(make_weights()[:30])


def test_read_animation_reads_tracks(make_animation: Callable[..., bytes]) -> None:
    clip = read_animation(make_animation(rate=15, flag=False))
    assert clip.rate == 15
    assert clip.frames == 3
    assert not clip.flag
    assert [(t.bone, t.parent) for t in clip.tracks] == [('Pelvis', ''), ('Head', 'Pelvis')]
    assert clip.tracks[0].keys[1][0] == 2
    assert clip.tracks[0].keys[1][1][10] == pytest.approx(1.5)


def test_read_animation_takes_the_longest_track(make_animation: Callable[..., bytes]) -> None:
    clip = read_animation(
        make_animation((('Pelvis', '', 1, ((0, _IDENTITY),)),
                        ('Head', 'Pelvis', 240, ((0, _IDENTITY), (239, _IDENTITY))))))
    assert clip.frames == 240


def test_read_animation_skips_other_chunks(make_animation: Callable[..., bytes]) -> None:
    clip = read_animation(_chunk(0x00010099, 0, b'') + make_animation())
    assert len(clip.tracks) == 2


def test_read_animation_rejects_no_tracks() -> None:
    with pytest.raises(InvalidCharacterError, match='No animation tracks'):
        read_animation(b'')


def test_read_animation_rejects_a_chunk_smaller_than_its_header() -> None:
    data = bytes((_CHUNK,)) + struct.pack('<3I', 0x00010012, 5, 4)
    with pytest.raises(InvalidCharacterError, match='records 4 bytes'):
        read_animation(data)


def test_read_animation_rejects_a_track_without_its_header() -> None:
    with pytest.raises(InvalidCharacterError, match='opens with chunk'):
        read_animation(_chunk(0x00010012, 5, _chunk(0x00010099, 0, b'')))


def test_read_animation_rejects_a_key_that_is_not_a_transform() -> None:
    header = _chunk(0x00010013, 0, _text('Pelvis') + _small(30) + b'\x0e\x01')
    body = header + _text('') + b'\x0e\x01' + _small(1) + _small(1) + _small(0)
    body += b'\x16' + struct.pack('<3f', 0.0, 0.0, 0.0)
    with pytest.raises(InvalidCharacterError, match='Expected a transform'):
        read_animation(_chunk(0x00010012, 5, body))


def test_read_animation_rejects_a_truncated_stream(make_animation: Callable[..., bytes]) -> None:
    with pytest.raises(InvalidCharacterError):
        read_animation(make_animation()[:40])
