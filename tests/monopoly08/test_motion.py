from __future__ import annotations

from typing import TYPE_CHECKING
import math
import struct

import pytest

from dade.monopoly08.motion import (
    MOTION_TICK_RATE,
    bank_character,
    parse_bank,
    parse_skeleton,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_HALF = math.sqrt(0.5)
_IDENTITY = (1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0)
_TAGS = ((0, 0b11), (4, 0b10), (8, 0b01), (12, 0b00))


def _codes(*values: int) -> str:
    bits = ''
    for value in values:
        width, tag = next((w, t) for w, t in _TAGS if value < 1 << w or w == 12)
        bits += f'{tag:02b}' + (f'{value:0{width}b}' if width else '')
    return bits


def _pack_bits(bits: str) -> bytes:
    bits += '0' * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


def _motion(make_ska: Callable[..., bytes], frame_table: bytes) -> bytes:
    frame0 = _codes(1, 2, 3, 0, 0x10, 0x100, 0x40, 0, 0, 0, 0)
    frame1 = _codes(*([0] * 11))
    vlc = _pack_bits(frame0) + _pack_bits(frame1)
    return make_ska((0xA0, 0x01, 0x110, 0x12, 0x12, 0x12, 0x0A, 0x48, 0x404, 0x400, 0x20),
                    base=struct.pack('>4h3H3H3H3H4h4h', 0, 0, 0, 0, 0x4010, 0, 0, 0, 0, 0x4020, 0,
                                     0x4030, 0, 0, 0x100, 0x1000, 0, 0, 0, 4096, 0, 0, 0, 4096),
                    frame_floats=struct.pack('>6f', 7, 8, 9, 7, 8, 9),
                    frame_rotations=struct.pack('>2H4h2H4h', 0x800, 0x1000, 0, 4096, 0, 0, 0, 0, 0,
                                                4096, 0, 0),
                    frame_table=frame_table,
                    masks={
                        'rotation': (0x01003219,),
                        'trans8': (0xE4,),
                        'trans16': (0x4,)
                    },
                    counts={
                        'float_bones': 1,
                        'rotation_bytes_per_frame': 12,
                        'rotation_masks': 8,
                        'trans8_bones': 4,
                        'trans8_per_frame': 6,
                        'trans16_bones': 2,
                        'trans16_per_frame': 4
                    },
                    static_rotations=struct.pack('>4h3H', 0, 0, 0, 4096, 0x4000, 0, 0),
                    static_translations=struct.pack('>6f', 1, 2, 3, 4, 5, 6),
                    trans8_base=struct.pack('>12f', 1, 1, 1, *([0] * 9)),
                    trans8_data=bytes((128, 0, 255, 64, 32, 16, 0, 0, 0, 0, 0, 0)),
                    trans16_base=struct.pack('>6f', 0, 0, 0, 5, 0, 0),
                    trans16_data=struct.pack('>8H', 1024, 2048, 3072, 512, 0, 0, 0, 0),
                    vlc=vlc)


@pytest.mark.parametrize('frame_table', [struct.pack('>2H', 0, 8), struct.pack('>Hh', 4, 4)])
def test_parse_bank_decodes_every_path(make_ska: Callable[..., bytes],
                                       make_bank: Callable[..., bytes], frame_table: bytes) -> None:
    ska = _motion(make_ska, frame_table)
    bank = parse_bank(make_bank(0x1234, [(2, 0, ska)], [('idle', 0, 4.0, 0x02010000, 0x16000001)]))
    assert bank.character == 0x1234
    (clip,) = bank.clips
    assert clip.name == 'idle'
    assert clip.frame_time == pytest.approx(4.0 / MOTION_TICK_RATE)
    first, second = clip.frames
    expected = [
        ((0, 0, 0, 1), None),
        ((0, 0, -_HALF, _HALF), (1, 2, 3)),
        ((0.5, 0, 0, 1), (1.125, 1, 1 + 255 / 1024)),
        ((0, 0, -_HALF, _HALF), (0.0625, 0, 0)),
        ((-_HALF, 0, 0, _HALF), (0, 0.03125, 0)),
        ((0, -_HALF, 0, _HALF), (0, 0, 0.015625)),
        ((0, 0, 0, 1), (1, 2, 3)),
        ((0, 1, 0, 0), (5.5, 0, 0)),
        ((0.125, 0, 0, 1), (7, 8, 9)),
        ((0, 0, 0, 1), (4, 5, 6)),
        ((0, 0, 0, 1), None),
    ]
    for key, (rotation, translation) in zip(first, expected, strict=True):
        assert key.rotation == pytest.approx(rotation, abs=1e-6)
        if translation is None:
            assert key.translation is None
        else:
            assert key.translation == pytest.approx(translation)
    assert second[3].rotation == pytest.approx(
        (0, 0, -math.sin(math.pi / 4 + 2 * math.pi * 0x10 / 65536 / 2),
         math.cos(math.pi / 4 + 2 * math.pi * 0x10 / 65536 / 2)))
    assert second[2].rotation == pytest.approx((0, 0, 0, 0))
    assert second[7].rotation == pytest.approx((0, 1, 0, 0))
    assert second[8].rotation == pytest.approx((0, 0, 0, 1))
    assert second[2].translation == pytest.approx((1, 1, 1))


def test_parse_bank_names_motions_without_a_state(make_ska: Callable[..., bytes],
                                                  make_bank: Callable[..., bytes]) -> None:
    ska = make_ska((0x20,))
    bank = parse_bank(
        make_bank(7, [(1, 0, ska), (1, 0, ska), (1, 0, ska)],
                  [('other', 0, 4.0, 0x05000000, 0x16000001),
                   ('tree', 1, 4.0, 0x02010000, 0x17000001)]))
    assert [clip.name for clip in bank.clips] == ['motion_00', 'motion_01', 'motion_02']
    assert bank.clips[0].frame_time == pytest.approx(2.0 / MOTION_TICK_RATE)
    assert bank.clips[0].frames[0][0].rotation == (0.0, 0.0, 0.0, 1.0)


def test_parse_bank_rejects_other_codecs(make_ska: Callable[..., bytes],
                                         make_bank: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='codec 4'):
        parse_bank(make_bank(1, [(1, 4, make_ska((0x20,)))], []))


def test_parse_bank_rejects_the_older_layout(make_bank: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='older SKA'):
        parse_bank(make_bank(1, [(1, 0, bytes(0xD0))], []))


def test_bank_character(make_bank: Callable[..., bytes]) -> None:
    assert bank_character(make_bank(0xD604BCA9, [], [])) == 0xD604BCA9


def test_parse_skeleton(make_skeleton: Callable[..., bytes]) -> None:
    moved = (*_IDENTITY[:12], 0, -1.5, 0, 1)
    skeleton = parse_skeleton(make_skeleton(0x55, (-1, 0), (_IDENTITY, moved)))
    assert skeleton.character == 0x55
    assert skeleton.parents == (-1, 0)
    assert skeleton.inverse_binds == (_IDENTITY, moved)


def test_parse_skeleton_rejects_a_truncated_table(make_skeleton: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='does not fit'):
        parse_skeleton(make_skeleton(1, (-1,), (_IDENTITY,))[:-8])


def test_parse_skeleton_rejects_an_empty_table(make_skeleton: Callable[..., bytes]) -> None:
    with pytest.raises(ValueError, match='0 bones'):
        parse_skeleton(make_skeleton(1, (), ()))
