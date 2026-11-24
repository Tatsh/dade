"""
Skeletal animations (``FSKA``) of Mario Kart World BFRES v10 archives, as plain data.

A clip lists bone animations by bone name. Each bone animation has a base pose, the scale,
rotation, and translation a channel takes when no curve drives it, and curves for the channels that
move. A curve records the frames of its keys and the channel it drives as an offset into the bone
transform the game evaluates (scale X, Y, and Z at 0x04 to 0x0C, translation at 0x10 to 0x18, and
rotation at 0x20 to 0x2C).

A cubic curve with bit ``0x4000`` of its flags set stores cubic Hermite keys. Its key array opens
with two 32-bit floats, the scale and the offset of a slope, and then gives each key a value and a
slope as unsigned integers of the key type. A value is the integer times the second number recorded
after the end frame plus the third, and a slope, in units per frame, is the integer times the first
float plus the second. Two keys at the same frame give the incoming and the outgoing slope at the
frame. The decoding was verified by comparing the first key of every curve with the base value of
its channel. Keys of any other kind are reported as stored.

Material animations (``FMAA``) drive the textures and shader parameters of materials. A texture
pattern swaps the texture a sampler reads (the blinking eyes of a driver, for example), and is
written as the texture shown from each key frame on. Its step curve gives the index into the clip's
texture list as the key, read unsigned, times the second number recorded after the end frame, plus
the third. Every curve of a material animation is also reported under ``curves``, decoded as the
curves of a skeletal animation are.
"""
from __future__ import annotations

from typing import Any
import bisect
import itertools
import struct

__all__ = ('CHANNELS', 'read_animations', 'read_material_animations', 'sample_curve')

CHANNELS = {
    0x04: 'scale.x',
    0x08: 'scale.y',
    0x0C: 'scale.z',
    0x10: 'translate.x',
    0x14: 'translate.y',
    0x18: 'translate.z',
    0x20: 'rotate.x',
    0x24: 'rotate.y',
    0x28: 'rotate.z',
    0x2C: 'rotate.w'
}
"""Channel of each curve target offset.

:meta hide-value:
"""
_ANIMATIONS = 0x58
_ANIMATION_COUNT = 0xE2
_ANIMATION_SIZE = 0x50
_BONE_SIZE = 0x38
_CURVE_SIZE = 0x30
_EULER = 0x1000
_BASE_SCALE = 0x08
_BASE_ROTATE = 0x10
_BASE_TRANSLATE = 0x20
_QUANTISED = 0x4000
_SLOPE_HEADER = 8
_FRAME_TYPES = ('float32', 'fixed10.5', 'uint8')
_KEY_TYPES = ('float32', 'int16', 'int8')
_CURVE_TYPES = {
    0: 'cubic',
    1: 'linear',
    2: 'baked',
    4: 'step-int',
    5: 'baked-int',
    6: 'step-bool',
    7: 'baked-bool'
}
_FRAME_FORMATS = (('<f', 4, 1.0), ('<h', 2, 32.0), ('<B', 1, 1.0))
_KEY_FORMATS = (('<f', 4), ('<h', 2), ('<b', 1))


def _u16(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<H', data, offset)[0])


def _u32(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<I', data, offset)[0])


def _u64(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<Q', data, offset)[0])


def _string(data: bytes, pointer: int) -> str:
    return data[pointer + 2:pointer + 2 + _u16(data, pointer)].decode('utf-8', 'replace')


def _base(data: bytes, pointer: int, flags: int) -> dict[str, list[float]]:
    base: dict[str, list[float]] = {}
    position = pointer
    for bit, name, width in ((_BASE_SCALE, 'scale', 3), (_BASE_ROTATE, 'rotation', 4),
                             (_BASE_TRANSLATE, 'translation', 3)):
        if flags & bit:
            base[name] = [round(v, 7) for v in struct.unpack_from(f'<{width}f', data, position)]
            position += width * 4
    return base


def _hermite_keys(data: bytes, pointer: int, frames: list[float], key_type: int,
                  value_scale: tuple[float, float]) -> list[dict[str, float]]:
    slope_scale, slope_offset = struct.unpack_from('<2f', data, pointer)
    pair, width = ('<2H', 2) if key_type == 1 else ('<2B', 1)
    keys = []
    for index, frame in enumerate(frames):
        value, slope = struct.unpack_from(pair, data, pointer + _SLOPE_HEADER + index * 2 * width)
        keys.append({
            'frame': frame,
            'slope': round(slope * slope_scale + slope_offset, 9),
            'value': round(value * value_scale[0] + value_scale[1], 9)
        })
    return keys


def _curve(data: bytes, curve: int, key_end: int) -> dict[str, Any]:
    flags, count, target = struct.unpack_from('<HHI', data, curve + 0x10)
    start, end, field_a, field_b, field_c = struct.unpack_from('<5f', data, curve + 0x18)
    frame_format, frame_width, frame_divisor = _FRAME_FORMATS[min(flags & 3, 2)]
    key_format, key_width = _KEY_FORMATS[min((flags >> 2) & 3, 2)]
    frames_pointer, keys_pointer = _u64(data, curve), _u64(data, curve + 8)
    frames = [
        struct.unpack_from(frame_format, data, frames_pointer + index * frame_width)[0] /
        frame_divisor for index in range(count)
    ]
    curve_type = (flags >> 4) & 7
    key_type = min((flags >> 2) & 3, 2)
    result: dict[str, Any] = {
        'channel': CHANNELS.get(target, f'offset-{target:#x}'),
        'curve_type': _CURVE_TYPES.get(curve_type, 'unknown'),
        'end_frame': end,
        'fields': [field_a, field_b, field_c],
        'flags': f'{flags:#06x}',
        'frame_type': _FRAME_TYPES[min(flags & 3, 2)],
        'frames': frames,
        'key_type': _KEY_TYPES[key_type],
        'start_frame': start
    }
    if curve_type == 0 and flags & _QUANTISED and key_type:
        result['keys'] = _hermite_keys(data, keys_pointer, frames, key_type, (field_b, field_c))
        return result
    key_count = max(0, key_end - keys_pointer) // key_width
    result['keys_raw'] = [
        struct.unpack_from(key_format, data, keys_pointer + index * key_width)[0]
        for index in range(key_count)
    ]
    return result


def read_animations(data: bytes) -> list[dict[str, Any]]:
    """
    Read every skeletal animation of an archive.

    Parameters
    ----------
    data : bytes
        Decompressed BFRES archive.

    Returns
    -------
    list[dict[str, Any]]
        One entry for each clip, ready to be written as JSON.

    Raises
    ------
    ValueError
        The input is not a BFRES archive, or a skeletal animation record does not open with
        ``FSKA``.
    """
    if data[:4] != b'FRES':
        message = 'Invalid BFRES archive.'
        raise ValueError(message)
    array, count = _u64(data, _ANIMATIONS), _u16(data, _ANIMATION_COUNT)
    if not count:
        return []
    clips: list[tuple[int, int, list[tuple[int, int, int]]]] = []
    pointers: set[int] = {len(data)}
    for index in range(count):
        animation = array + index * _ANIMATION_SIZE
        if data[animation:animation + 4] != b'FSKA':
            message = 'Invalid BFRES skeletal animation.'
            raise ValueError(message)
        bones = _u64(data, animation + 0x28)
        records = []
        for bone_index in range(_u16(data, animation + 0x4C)):
            bone = bones + bone_index * _BONE_SIZE
            curves = _u64(data, bone + 8)
            records.append((bone, curves, data[bone + 0x2E]))
            pointers.update((bone, _u64(data, bone), _u64(data, bone + 0x10)))
            for curve_index in range(data[bone + 0x2E]):
                curve = curves + curve_index * _CURVE_SIZE
                pointers.update((curve, _u64(data, curve), _u64(data, curve + 8)))
        pointers.update((animation, _u64(data, animation + 8), bones))
        clips.append((animation, bones, records))
    ordered = sorted(pointers)

    def following(pointer: int) -> int:
        return ordered[bisect.bisect_right(ordered, pointer)]

    result = []
    for animation, _, records in clips:
        flags = _u32(data, animation + 4)
        bones_out = []
        for bone, curves, curve_count in records:
            bone_flags = _u32(data, bone + 0x28)
            bones_out.append({
                'base': _base(data, _u64(data, bone + 0x10), bone_flags),
                'curves': [
                    _curve(data, curves + index * _CURVE_SIZE,
                           following(_u64(data, curves + index * _CURVE_SIZE + 8)))
                    for index in range(curve_count)
                ],
                'flags': f'{bone_flags:#010x}',
                'name': _string(data, _u64(data, bone))
            })
        result.append({
            'bones': bones_out,
            'flags': f'{flags:#06x}',
            'frame_count': struct.unpack_from('<i', data, animation + 0x40)[0],
            'name': _string(data, _u64(data, animation + 8)),
            'rotation': 'euler-xyz' if flags & _EULER else 'quaternion'
        })
    return result


_MATERIAL_ANIMATIONS = 0x68
_MATERIAL_ANIMATION_COUNT = 0xE4
_MATERIAL_CLIP_SIZE = 0x70
_MATERIAL_SIZE = 0x40
_PATTERN_SIZE = 0x10
_PARAMETER_SIZE = 0x18
_STEP_INT = 4


def _texture_pattern(data: bytes, curve: int, textures: list[str]) -> list[dict[str, Any]]:
    flags, count = struct.unpack_from('<HH', data, curve + 0x10)
    scale, offset = struct.unpack_from('<2f', data, curve + 0x24)
    frame_format, frame_width, frame_divisor = _FRAME_FORMATS[min(flags & 3, 2)]
    key_format, key_width = (('<I', 4), ('<H', 2), ('<B', 1))[min((flags >> 2) & 3, 2)]
    keys = []
    for index in range(count):
        frame = struct.unpack_from(frame_format, data,
                                   _u64(data, curve) + index * frame_width)[0] / frame_divisor
        key = struct.unpack_from(key_format, data, _u64(data, curve + 8) + index * key_width)[0]
        texture = round(offset + key * scale)
        keys.append({
            'frame': frame,
            'texture': textures[texture] if 0 <= texture < len(textures) else None
        })
    return keys


def _material(data: bytes, material: int, textures: list[str],
              ordered: list[int]) -> dict[str, Any]:
    parameters, patterns = _u64(data, material + 8), _u64(data, material + 0x10)
    curves = _u64(data, material + 0x18)
    parameter_count, pattern_count, _, curve_count = struct.unpack_from(
        '<4H', data, material + 0x32)
    texture_patterns = []
    for pattern_index in range(pattern_count):
        pattern = patterns + pattern_index * _PATTERN_SIZE
        curve_index = struct.unpack_from('<h', data, pattern + 8)[0]
        curve = curves + curve_index * _CURVE_SIZE
        entry: dict[str, Any] = {'sampler': _string(data, _u64(data, pattern))}
        if curve_index >= 0 and (_u16(data, curve + 0x10) >> 4) & 7 == _STEP_INT:
            entry['keys'] = _texture_pattern(data, curve, textures)
        texture_patterns.append(entry)
    return {
        'curves': [
            _curve(
                data, curves + position * _CURVE_SIZE, ordered[bisect.bisect_right(
                    ordered, _u64(data, curves + position * _CURVE_SIZE + 8))])
            for position in range(curve_count)
        ],
        'name': _string(data, _u64(data, material)),
        'shader_parameters': [
            _string(data, _u64(data, parameters + position * _PARAMETER_SIZE))
            for position in range(parameter_count)
        ],
        'texture_patterns': texture_patterns
    }


def read_material_animations(data: bytes) -> list[dict[str, Any]]:
    """
    Read every material animation of an archive.

    Parameters
    ----------
    data : bytes
        Decompressed BFRES archive.

    Returns
    -------
    list[dict[str, Any]]
        One entry for each clip, ready to be written as JSON.

    Raises
    ------
    ValueError
        The input is not a BFRES archive, or a material animation record does not open with
        ``FMAA``.
    """
    if data[:4] != b'FRES':
        message = 'Invalid BFRES archive.'
        raise ValueError(message)
    array, count = _u64(data, _MATERIAL_ANIMATIONS), _u16(data, _MATERIAL_ANIMATION_COUNT)
    pointers: set[int] = {len(data)}
    for index in range(count):
        clip = array + index * _MATERIAL_CLIP_SIZE
        if data[clip:clip + 4] != b'FMAA':
            message = 'Invalid BFRES material animation.'
            raise ValueError(message)
        for material_index in range(_u16(data, clip + 0x62)):
            material = _u64(data, clip + 0x28) + material_index * _MATERIAL_SIZE
            curves = _u64(data, material + 0x18)
            pointers.update((clip, material, curves))
            for position in range(_u16(data, material + 0x38)):
                curve = curves + position * _CURVE_SIZE
                pointers.update((_u64(data, curve), _u64(data, curve + 8)))
    ordered = sorted(pointers)
    result = []
    for index in range(count):
        clip = array + index * _MATERIAL_CLIP_SIZE
        texture_list = _u64(data, clip + 0x38)
        textures = [
            _string(data, _u64(data, texture_list + position * 8))
            for position in range(_u16(data, clip + 0x6C))
        ] if texture_list else []
        materials = [
            _material(data,
                      _u64(data, clip + 0x28) + material_index * _MATERIAL_SIZE, textures, ordered)
            for material_index in range(_u16(data, clip + 0x62))
        ]
        result.append({
            'frame_count': struct.unpack_from('<i', data, clip + 0x58)[0],
            'materials': materials,
            'name': _string(data, _u64(data, clip + 8)),
            'textures': textures
        })
    return result


def sample_curve(keys: list[dict[str, float]], frame: float) -> float:
    """
    Evaluate decoded Hermite keys at a frame.

    Before the first key, the value of the first key applies, and after the last key, the value of
    the last key.

    Parameters
    ----------
    keys : list[dict[str, float]]
        Keys with ``frame``, ``value``, and ``slope``, in frame order, as :py:func:`read_animations`
        reports them.
    frame : float
        Frame to evaluate the curve at.

    Returns
    -------
    float
        Value of the curve at ``frame``.

    Raises
    ------
    IndexError
        ``keys`` is empty.
    """  # ruff: ignore[docstring-extraneous-exception]
    if frame <= keys[0]['frame']:
        return keys[0]['value']
    for start, end in itertools.pairwise(keys):
        span = end['frame'] - start['frame']
        if span > 0 and frame <= end['frame']:
            t = (frame - start['frame']) / span
            t2, t3 = t * t, t * t * t
            return ((2 * t3 - 3 * t2 + 1) * start['value'] +
                    (t3 - 2 * t2 + t) * span * start['slope'] + (-2 * t3 + 3 * t2) * end['value'] +
                    (t3 - t2) * span * end['slope'])
    return keys[-1]['value']
