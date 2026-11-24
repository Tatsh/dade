"""Tests for Mario Kart World skeletal animations."""
from __future__ import annotations

import struct

import pytest

from dade.mkw.animation import CHANNELS, read_animations, read_material_animations, sample_curve


def _name(data: bytearray, pointer: int, name: str) -> None:
    struct.pack_into(f'<H{len(name)}s', data, pointer, len(name), name.encode())


def _curve(data: bytearray, curve: int, frames: int, keys: int, flags: int, count: int,
           target: int) -> None:
    struct.pack_into('<QQHHI5f', data, curve, frames, keys, flags, count, target, 0.0, 10.0, 1.0,
                     2.0, 3.0)


def _archive() -> bytearray:
    data = bytearray(0x600)
    data[:4] = b'FRES'
    struct.pack_into('<Q', data, 0x58, 0x100)
    struct.pack_into('<H', data, 0xE2, 2)
    for animation, flags, name, bones, frame_count in ((0x100, 0x1000, 0x520, 0x200, 30),
                                                       (0x150, 0, 0x530, 0x240, -1)):
        data[animation:animation + 4] = b'FSKA'
        struct.pack_into('<IQ', data, animation + 4, flags, name)
        struct.pack_into('<Q', data, animation + 0x28, bones)
        struct.pack_into('<i', data, animation + 0x40, frame_count)
        struct.pack_into('<H', data, animation + 0x4C, 1)
    struct.pack_into('<QQQ', data, 0x200, 0x540, 0x300, 0x400)
    struct.pack_into('<I', data, 0x228, 0x38)
    data[0x22E] = 3
    struct.pack_into('<QQQ', data, 0x240, 0x550, 0, 0x440)
    struct.pack_into('<I', data, 0x268, 0x20)
    struct.pack_into('<3f4f3f', data, 0x400, 1.0, 1.0, 1.0, 0.1, 0.2, 0.3, 0.0, 4.0, 5.0, 6.0)
    struct.pack_into('<3f', data, 0x440, 7.0, 8.0, 9.0)
    _curve(data, 0x300, 0x500, 0x508, 0x10, 2, 0x10)
    struct.pack_into('<2f2f', data, 0x500, 0.0, 10.0, 1.5, 2.5)
    _curve(data, 0x330, 0x510, 0x514, 0x05, 2, 0x2C)
    struct.pack_into('<2h2h', data, 0x510, 64, 320, -3, 7)
    _curve(data, 0x360, 0x518, 0x51E, 0x3F, 2, 0x30)
    struct.pack_into('<2B', data, 0x518, 1, 5)
    struct.pack_into('<2b', data, 0x51E, -1, 2)
    for pointer, label in ((0x520, 'Run'), (0x530, 'Idle'), (0x540, 'Root'), (0x550, 'Hip')):
        _name(data, pointer, label)
    return data


def test_read_animations_reports_clips() -> None:
    run, idle = read_animations(bytes(_archive()))
    assert run['name'] == 'Run'
    assert run['flags'] == '0x1000'
    assert run['frame_count'] == 30
    assert run['rotation'] == 'euler-xyz'
    bone = run['bones'][0]
    assert bone['name'] == 'Root'
    assert bone['flags'] == '0x00000038'
    assert bone['base'] == {
        'rotation': [0.1, 0.2, 0.3, 0.0],
        'scale': [1.0, 1.0, 1.0],
        'translation': [4.0, 5.0, 6.0]
    }
    assert idle['name'] == 'Idle'
    assert idle['frame_count'] == -1
    assert idle['rotation'] == 'quaternion'
    assert idle['bones'] == [{
        'base': {
            'translation': [7.0, 8.0, 9.0]
        },
        'curves': [],
        'flags': '0x00000020',
        'name': 'Hip'
    }]


def test_read_animations_decodes_curve_types() -> None:
    curves = read_animations(bytes(_archive()))[0]['bones'][0]['curves']
    assert curves[0] == {
        'channel': 'translate.x',
        'curve_type': 'linear',
        'end_frame': 10.0,
        'fields': [1.0, 2.0, 3.0],
        'flags': '0x0010',
        'frame_type': 'float32',
        'frames': [0.0, 10.0],
        'key_type': 'float32',
        'keys_raw': [1.5, 2.5],
        'start_frame': 0.0
    }
    assert curves[1]['channel'] == 'rotate.w'
    assert curves[1]['curve_type'] == 'cubic'
    assert curves[1]['frame_type'] == 'fixed10.5'
    assert curves[1]['frames'] == [2.0, 10.0]
    assert curves[1]['key_type'] == 'int16'
    assert curves[1]['keys_raw'] == [-3, 7]
    assert curves[2]['channel'] == 'offset-0x30'
    assert curves[2]['curve_type'] == 'unknown'
    assert curves[2]['frame_type'] == 'uint8'
    assert curves[2]['frames'] == [1.0, 5.0]
    assert curves[2]['key_type'] == 'int8'
    assert curves[2]['keys_raw'] == [-1, 2]


@pytest.mark.parametrize(('flags', 'expected'), [(0x00, 'cubic'), (0x10, 'linear'), (0x20, 'baked'),
                                                 (0x40, 'step-int'), (0x50, 'baked-int'),
                                                 (0x60, 'step-bool'), (0x70, 'baked-bool')])
def test_read_animations_curve_type_names(flags: int, expected: str) -> None:
    data = _archive()
    struct.pack_into('<H', data, 0x310, flags)
    assert read_animations(bytes(data))[0]['bones'][0]['curves'][0]['curve_type'] == expected


@pytest.mark.parametrize(('target', 'channel'), list(CHANNELS.items()))
def test_read_animations_maps_channels(target: int, channel: str) -> None:
    data = _archive()
    struct.pack_into('<I', data, 0x314, target)
    assert read_animations(bytes(data))[0]['bones'][0]['curves'][0]['channel'] == channel


def test_read_animations_empty_archive() -> None:
    data = _archive()
    struct.pack_into('<H', data, 0xE2, 0)
    assert read_animations(bytes(data)) == []


def test_read_animations_rejects_invalid_archive() -> None:
    with pytest.raises(ValueError, match='Invalid BFRES archive'):
        read_animations(b'BNTX' + bytes(0x100))


def test_read_animations_rejects_invalid_skeletal_animation() -> None:
    data = _archive()
    data[0x150:0x154] = b'FMAA'
    with pytest.raises(ValueError, match='Invalid BFRES skeletal animation'):
        read_animations(bytes(data))


def _hermite_archive(flags: int, keys: bytes) -> bytes:
    data = _archive()
    struct.pack_into('<Q', data, 0x338, 0x5C0)
    struct.pack_into('<H', data, 0x340, flags)
    struct.pack_into('<2f', data, 0x5C0, 0.5, -1.0)
    data[0x5C8:0x5C8 + len(keys)] = keys
    return bytes(data)


@pytest.mark.parametrize(('flags', 'keys', 'last'),
                         [(0x4005, struct.pack('<4H', 10, 4, 0xFFFF, 2), 131073.0),
                          (0x4009, struct.pack('<4B', 10, 4, 0xFF, 2), 513.0)])
def test_read_animations_decodes_hermite_keys(flags: int, keys: bytes, last: float) -> None:
    curve = read_animations(_hermite_archive(flags, keys))[0]['bones'][0]['curves'][1]
    assert curve['curve_type'] == 'cubic'
    assert curve['frames'] == [2.0, 10.0]
    assert 'keys_raw' not in curve
    assert curve['keys'] == [{
        'frame': 2.0,
        'slope': 1.0,
        'value': 23.0
    }, {
        'frame': 10.0,
        'slope': 0.0,
        'value': last
    }]


@pytest.mark.parametrize(('flags', 'first'), [(0x4001, [0.5, -1.0]), (0x4015, [0, 16128])])
def test_read_animations_keeps_raw_keys_outside_hermite_path(flags: int,
                                                             first: list[float]) -> None:
    curve = read_animations(_hermite_archive(flags, bytes(8)))[0]['bones'][0]['curves'][1]
    assert 'keys' not in curve
    assert curve['keys_raw'][:2] == first


HERMITE = [{'frame': 2.0, 'slope': 2.0, 'value': 1.0}, {'frame': 6.0, 'slope': -1.0, 'value': 3.0}]


@pytest.mark.parametrize(('frame', 'expected'), [(-1.0, 1.0), (2.0, 1.0), (3.0, 2.625), (4.0, 3.5),
                                                 (6.0, 3.0), (100.0, 3.0)])
def test_sample_curve_evaluates_hermite_and_clamps(frame: float, expected: float) -> None:
    assert sample_curve(HERMITE, frame) == pytest.approx(expected)


def test_sample_curve_steps_at_repeated_frame() -> None:
    keys = [{
        'frame': 0.0,
        'slope': 0.0,
        'value': 0.0
    }, {
        'frame': 5.0,
        'slope': 0.0,
        'value': 1.0
    }, {
        'frame': 5.0,
        'slope': 0.0,
        'value': 4.0
    }, {
        'frame': 10.0,
        'slope': 0.0,
        'value': 6.0
    }]
    assert sample_curve(keys, 5.0) == pytest.approx(1.0)
    assert sample_curve(keys, 5.000001) == pytest.approx(4.0)
    assert sample_curve(keys, 7.5) == pytest.approx(5.0)
    assert sample_curve(keys, 10.0) == pytest.approx(6.0)


def test_sample_curve_single_or_coincident_keys_hold_last_value() -> None:
    keys = [{'frame': 3.0, 'slope': 1.0, 'value': 2.0}, {'frame': 3.0, 'slope': 0.0, 'value': 7.0}]
    assert sample_curve(keys[:1], 9.0) == pytest.approx(2.0)
    assert sample_curve(keys, 2.0) == pytest.approx(2.0)
    assert sample_curve(keys, 4.0) == pytest.approx(7.0)


def _material_archive() -> bytearray:
    data = bytearray(0x800)
    data[:4] = b'FRES'
    struct.pack_into('<Q', data, 0x68, 0x100)
    struct.pack_into('<H', data, 0xE4, 2)
    for clip, name, materials, textures, count, frames in ((0x100, 0x700, 0x200, 0x2C0, 2, 3),
                                                           (0x170, 0x710, 0x240, 0, 0, 720)):
        data[clip:clip + 4] = b'FMAA'
        struct.pack_into('<Q', data, clip + 8, name)
        struct.pack_into('<Q', data, clip + 0x28, materials)
        struct.pack_into('<Q', data, clip + 0x38, textures)
        struct.pack_into('<i', data, clip + 0x58, frames)
        struct.pack_into('<H', data, clip + 0x62, 1)
        struct.pack_into('<H', data, clip + 0x6C, count)
    struct.pack_into('<QQQQ', data, 0x200, 0x720, 0, 0x300, 0x400)
    struct.pack_into('<4H', data, 0x232, 0, 3, 0, 2)
    struct.pack_into('<QQQQ', data, 0x240, 0x720, 0x380, 0, 0x460)
    struct.pack_into('<4H', data, 0x272, 1, 0, 0, 1)
    struct.pack_into('<QQ', data, 0x2C0, 0x740, 0x750)
    struct.pack_into('<Qh', data, 0x300, 0x760, 0)
    struct.pack_into('<Qh', data, 0x310, 0x768, -1)
    struct.pack_into('<Qh', data, 0x320, 0x770, 1)
    struct.pack_into('<Q', data, 0x380, 0x778)
    struct.pack_into('<QQHHI5f', data, 0x400, 0x600, 0x608, 0x4A, 3, 0, 0.0, 3.0, 0.0, 1 / 128, 0.0)
    struct.pack_into('<3B', data, 0x600, 0, 3, 5)
    struct.pack_into('<3B', data, 0x608, 0, 0x80, 0xFF)
    struct.pack_into('<QQHHI5f', data, 0x430, 0x610, 0x618, 0x0A, 2, 0x10, 0.0, 3.0, 0.0, 1.0, 0.0)
    struct.pack_into('<QQHHI5f', data, 0x460, 0x620, 0x628, 0x0A, 2, 0x14, 0.0, 720.0, 0.0, 0.5,
                     -1.0)
    struct.pack_into('<2B', data, 0x620, 0, 90)
    struct.pack_into('<4b', data, 0x628, 1, -2, 3, -4)
    for pointer, label in ((0x700, 'Blink'), (0x710, 'Look'), (0x720, 'Mt_Eye'),
                           (0x740, 'Tex_A.00'), (0x750, 'Tex_A.03'), (0x760, '_a0'), (0x768, '_n0'),
                           (0x770, 'mix0'), (0x778, 'tex_srt0')):
        _name(data, pointer, label)
    return data


def test_read_material_animations_decodes_texture_patterns() -> None:
    blink, look = read_material_animations(bytes(_material_archive()))
    assert blink['name'] == 'Blink'
    assert blink['frame_count'] == 3
    assert blink['textures'] == ['Tex_A.00', 'Tex_A.03']
    material = blink['materials'][0]
    assert material['name'] == 'Mt_Eye'
    assert material['shader_parameters'] == []
    assert material['texture_patterns'] == [{
        'keys': [{
            'frame': 0.0,
            'texture': 'Tex_A.00'
        }, {
            'frame': 3.0,
            'texture': 'Tex_A.03'
        }, {
            'frame': 5.0,
            'texture': None
        }],
        'sampler': '_a0'
    }, {
        'sampler': '_n0'
    }, {
        'sampler': 'mix0'
    }]
    assert [curve['curve_type'] for curve in material['curves']] == ['step-int', 'cubic']
    assert look['textures'] == []
    shader = look['materials'][0]
    assert shader['shader_parameters'] == ['tex_srt0']
    assert shader['texture_patterns'] == []
    assert shader['curves'][0]['channel'] == 'translate.y'
    assert shader['curves'][0]['frames'] == [0.0, 90.0]
    assert shader['curves'][0]['keys_raw'][:4] == [1, -2, 3, -4]


def test_read_material_animations_empty_archive() -> None:
    data = _material_archive()
    struct.pack_into('<H', data, 0xE4, 0)
    assert read_material_animations(bytes(data)) == []


def test_read_material_animations_rejects_invalid_archive() -> None:
    with pytest.raises(ValueError, match='Invalid BFRES archive'):
        read_material_animations(b'BNTX' + bytes(0x100))


def test_read_material_animations_rejects_invalid_record() -> None:
    data = _material_archive()
    data[0x170:0x174] = b'FSKA'
    with pytest.raises(ValueError, match='Invalid BFRES material animation'):
        read_material_animations(bytes(data))
