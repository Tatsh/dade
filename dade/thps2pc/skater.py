"""
Skater models and their animations, written as a skinned GLB.

A skater ``.PSX`` is a scene whose sectors are body parts. Its ``HIER`` chunk lists each part's
parent, a part being a root when it is its own parent, and the ``.PSH`` header beside it identifies
the parts. Every vertex belongs rigidly to its part. A vertex whose fourth 16-bit field has bit 1
set is a reference instead. Its y field identifies a slot in a buffer the game fills, in sector
order, with each transformed vertex that has bit 0 set. A reference therefore follows the part that
filled the slot, and references close the seams between parts.

Clips are stored in chunk ``0x2C``: a count, then an offset and a frame count for each clip. A clip
stores six channels for each part, three angles (4096 to a turn) and three translations, and each
channel opens with one byte. Its high nibble plus one is the step between keys and its low nibble
selects the encoding::

    0       a 16-bit key every step
    1..13   a 16-bit first key, then signed deltas of (mode + 1) bits packed most significant bit
            first, the stream padded to a byte at its end
    14      one 16-bit value for every frame
    15      zero for every frame

Frames between keys are interpolated linearly in integer steps. The last span is shorter when the
frame count is not one more than a multiple of the step. A part's angles give its rotation in model
space directly, composed as ``Ry @ Rx @ Rz``. Only its translation is relative to the parent, being
rotated by the parent's rotation and added to the parent's position. Chunk ``0x2A`` stores clips
already composed, as a row-major 4.12 matrix and a translation for each part.

The game advances a clip one frame each sixtieth of a second. The game decodes channels in
``FUN_004305e0``, composes them in ``DecompGetAnimatedTransforms``, and resolves references in
``FUN_004d2aa0``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import io
import logging
import re
import struct

from PIL import Image
import numpy as np

from dade.common.gltf import ARRAY_BUFFER, UNSIGNED_BYTE, GLBDocument
from dade.common.io import i16, u16, u32

from .psx import UV_SCALE
from .textures import TRANSPARENT_COLOR, iter_decoded, parse_lighting

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from .psx import Scene

__all__ = ('FRAMES_PER_SECOND', 'SCALE', 'Clip', 'Skater', 'build_skater_glb', 'decode_channel',
           'part_names', 'part_parents', 'read_skater', 'remap_clips')

log = logging.getLogger(__name__)

FRAMES_PER_SECOND = 60
"""Rate the game advances a clip, in frames per second.

:meta hide-value:
"""
SCALE = 1.0 / 2048.0
"""Factor converting model units to glTF units.

:meta hide-value:
"""

_HIERARCHY_CHUNK = 0x52454948
_CLIP_CHUNK = 0x2C
_POSE_CHUNK = 0x2A
_CONSTANT_MODE = 14
_ZERO_MODE = 15
_EXPORT_FLAG = 1
_REFERENCE_FLAG = 2
_TURN = 4096
_FIXED_ONE = 4096.0
_POSE_SIZE = 24
_PART_RE = re.compile(r'^#define\s+\w+?PART_(\w+)\s+(\d+)', re.MULTILINE)
_PARENT_RE = re.compile(r'^#define\s+\w+?PART_(\w+)\s+(\d+)\s*\n//\s*parent:\s*(.+?)\s*$',
                        re.MULTILINE)
_AXES = np.diag((1.0, -1.0, -1.0))


class Clip(NamedTuple):
    """One clip, as the model-space pose of every part on every frame."""

    name: str
    """Name for the clip, from its index."""
    rotations: np.ndarray
    """Rotation matrices, shaped ``(frames, parts, 3, 3)``."""
    translations: np.ndarray
    """Part positions, shaped ``(frames, parts, 3)``."""


class Skater(NamedTuple):
    """A skater scene with its hierarchy and clips."""

    clips: tuple[Clip, ...]
    """Clips stored in the file."""
    parents: tuple[int, ...]
    """Parent of each part, a root being its own parent."""
    scene: Scene
    """The parsed scene."""


def decode_channel(data: bytes, offset: int, frames: int) -> tuple[np.ndarray, int]:
    """
    Decode one channel of a compressed clip.

    Parameters
    ----------
    data : bytes
        The clip chunk.
    offset : int
        Offset of the channel's first byte.
    frames : int
        Number of frames in the clip.

    Returns
    -------
    tuple[numpy.ndarray, int]
        One signed 16-bit value per frame, and the offset after the channel.
    """
    head = data[offset]
    offset += 1
    step, mode = (head >> 4) + 1, head & 0xF
    out = np.zeros(frames, np.int64)
    if mode == _CONSTANT_MODE:
        out[:] = i16(data, offset)
        return out, offset + 2
    if mode == _ZERO_MODE:
        return out, offset
    keys = (frames - 1) // step
    spans = [step] * keys
    if step > 1 and (rest := frames - keys * step - 1):
        spans.append(rest)
    current = i16(data, offset)
    offset += 2
    out[0] = current
    index, bit = 1, 0
    for span in spans:
        if mode == 0:
            target = i16(data, offset)
            delta = target - current
            offset += 2
        else:
            window = int.from_bytes(data[offset:offset + 3].ljust(3, b'\x00'), 'big')
            delta = ((window << bit) >> (24 - mode - 1)) & ((1 << (mode + 1)) - 1)
            delta -= (delta >> mode) << (mode + 1)
            target = _wrap(current + delta)
            bit += mode + 1
            offset += bit >> 3
            bit &= 7
        increment = int(delta / span)
        for _ in range(span - 1):
            current = _wrap(current + increment)
            out[index] = current
            index += 1
        out[index] = current = target
        index += 1
    return out, offset + (1 if bit else 0)


def part_names(header: str) -> tuple[str, ...]:
    """
    Read the part names from a ``.PSH`` header, ordered by index.

    Parameters
    ----------
    header : str
        The header text.

    Returns
    -------
    tuple[str, ...]
        Lower-case part names, such as ``hawk_left_shin``.
    """
    found = {int(index): name.lower() for name, index in _PART_RE.findall(header)}
    return tuple(found[index] for index in sorted(found))


def part_parents(header: str) -> tuple[int, ...] | None:
    """
    Read each part's parent from the comments of a ``.PSH`` header.

    A part under ``Scene Root`` is its own parent. A model whose ``HIER`` chunk is missing is
    arranged by these comments. Where both exist they can disagree, and the chunk is what the game
    reads.

    Parameters
    ----------
    header : str
        The header text.

    Returns
    -------
    tuple[int, ...] | None
        The parent of each part ordered by index, or :py:obj:`None` when a part lacks a comment or
        identifies a parent that is not a part.
    """
    entries = {
        int(index): (name.lower(), parent.lower())
        for name, index, parent in _PARENT_RE.findall(header)
    }
    names = [entries[index][0] for index in sorted(entries)]
    if sorted(entries) != list(range(len(names))) or len(names) != len(part_names(header)):
        return None
    parents = []
    for index, (_, parent) in sorted(entries.items()):
        if parent == 'scene root':
            parents.append(index)
        elif parent in names:
            parents.append(names.index(parent))
        else:
            return None
    return tuple(parents)


def read_skater(scene: Scene, fallback: Sequence[int] = ()) -> Skater | None:
    """
    Read the hierarchy and clips of a skater scene.

    Parameters
    ----------
    scene : Scene
        A parsed scene.
    fallback : Sequence[int]
        Parents to use when the scene has no ``HIER`` chunk, such as the parents from
        :py:func:`part_parents`.

    Returns
    -------
    Skater | None
        The skater, or :py:obj:`None` when there is no hierarchy for every sector.
    """
    chunks = {chunk.id: chunk for chunk in scene.chunks()}
    count = len(scene.sectors)
    if (hierarchy := chunks.get(_HIERARCHY_CHUNK)) is not None and hierarchy.size >= count * 2:
        parents = tuple(u16(scene.data, hierarchy.offset + 8 + i * 2) for i in range(count))
    elif hierarchy is None and len(fallback) == count:
        parents = tuple(fallback)
    else:
        return None
    if any(parent >= count for parent in parents):
        return None
    clips: tuple[Clip, ...] = ()
    if (chunk := chunks.get(_CLIP_CHUNK)) is not None:
        body = scene.data[chunk.offset + 8:chunk.offset + 8 + chunk.size]
        clips = tuple(_compressed_clips(body, parents))
    elif (chunk := chunks.get(_POSE_CHUNK)) is not None:
        body = scene.data[chunk.offset + 8:chunk.offset + 8 + chunk.size]
        clips = tuple(_pose_clips(body, count))
    return Skater(clips=clips, parents=parents, scene=scene)


def remap_clips(clips: Iterable[Clip], source: Sequence[str],
                target: Sequence[str]) -> tuple[Clip, ...]:
    """
    Reorder clip parts to another model's parts, matching names without their skater prefix.

    Parameters
    ----------
    clips : Iterable[Clip]
        Clips in the order of ``source``.
    source : Sequence[str]
        Part names of the clips.
    target : Sequence[str]
        Part names of the model the clips are for.

    Returns
    -------
    tuple[Clip, ...]
        The clips in the order of ``target``.

    Raises
    ------
    KeyError
        If a target part has no source part of the same name.
    """
    lookup = {_part_key(name): index for index, name in enumerate(source)}
    if missing := [name for name in target if _part_key(name) not in lookup]:
        raise KeyError(missing[0])
    order = [lookup[_part_key(name)] for name in target]
    return tuple(
        clip._replace(rotations=clip.rotations[:, order], translations=clip.translations[:, order])
        for clip in clips)


def build_skater_glb(skater: Skater, names: Sequence[str], clips: Sequence[Clip],
                     name: str) -> bytes:
    """
    Write a skater as a GLB, with a joint for each part and one animation for each clip.

    The first frame of the first clip is the bind pose. The game's y axis points down and is turned
    to glTF's y up.

    Parameters
    ----------
    skater : Skater
        The skater.
    names : Sequence[str]
        Part names, one for each sector.
    clips : Sequence[Clip]
        Clips to write, in the order of the sectors. At least one is required.
    name : str
        Name for the scene.

    Returns
    -------
    bytes
        The GLB.

    Raises
    ------
    IndexError
        If ``clips`` is empty.
    """  # ruff: ignore[docstring-extraneous-exception]
    parents = skater.parents
    document = GLBDocument('dade thps2pc')
    rotations, translations = clips[0].rotations[0], clips[0].translations[0]
    joints = _add_joints(document, names, parents, rotations, translations)
    skin = len(document.skins)
    world = [_world(rotations[i], translations[i]) for i in range(len(names))]
    document.skins.append({
        'inverseBindMatrices':
            document.floats([np.linalg.inv(matrix).T.reshape(-1).tolist() for matrix in world],
                            'MAT4'),
        'joints':
            joints
    })
    roots = [joints[i] for i, parent in enumerate(parents) if parent == i]
    if len(roots) > 1:
        document.nodes.append({'children': roots, 'name': f'{name}_root'})
        roots = [len(document.nodes) - 1]
    document.skins[skin]['skeleton'] = roots[0]
    mesh = _add_mesh(document, skater, rotations, translations)
    document.nodes.append({'mesh': mesh, 'name': name, 'skin': skin})
    for clip in clips:
        _add_animation(document, clip, parents, joints)
    return document.finish(name, [*roots, len(document.nodes) - 1])


def _wrap(value: int) -> int:
    return (value + 0x8000) % 0x10000 - 0x8000


def _part_key(name: str) -> str:
    return name.split('_', 1)[-1]


def _order(parents: Sequence[int]) -> list[int]:
    order: list[int] = []
    while len(order) < len(parents):
        for index, parent in enumerate(parents):
            if index not in order and (parent == index or parent in order):
                order.append(index)
    return order


def _rotation(angles: np.ndarray) -> np.ndarray:
    x, y, z = np.moveaxis(angles * (2 * np.pi / _TURN), -1, 0)
    one, zero = np.ones_like(x), np.zeros_like(x)
    rotate_x = np.stack(
        [one, zero, zero, zero,
         np.cos(x), -np.sin(x), zero,
         np.sin(x), np.cos(x)], -1).reshape(*x.shape, 3, 3)
    rotate_y = np.stack(
        [np.cos(y), zero, np.sin(y), zero, one, zero, -np.sin(y), zero,
         np.cos(y)], -1).reshape(*x.shape, 3, 3)
    rotate_z = np.stack(
        [np.cos(z), -np.sin(z), zero,
         np.sin(z), np.cos(z), zero, zero, zero, one], -1).reshape(*x.shape, 3, 3)
    result: np.ndarray = rotate_y @ rotate_x @ rotate_z
    return result


def _compressed_clips(body: bytes, parents: Sequence[int]) -> Iterator[Clip]:
    count = len(parents)
    for index in range(u32(body, 0)):
        offset, frames = u32(body, 4 + index * 8), u32(body, 8 + index * 8)
        values = np.zeros((frames, count, 6))
        for part in range(count):
            for channel in range(6):
                values[:, part, channel], offset = decode_channel(body, offset, frames)
        rotations = _rotation(values[..., :3])
        translations = np.zeros((frames, count, 3))
        for part in _order(parents):
            local = values[:, part, 3:]
            if (parent := parents[part]) == part:
                translations[:, part] = local
            else:
                translations[:, part] = (np.einsum('fij,fj->fi', rotations[:, parent], local) +
                                         translations[:, parent])
        yield Clip(name=f'clip_{index:03d}', rotations=rotations, translations=translations)


def _pose_clips(body: bytes, count: int) -> Iterator[Clip]:
    for index in range(u32(body, 0)):
        offset, frames = u32(body, 4 + index * 8), u32(body, 8 + index * 8)
        values = np.frombuffer(body, '<i2', frames * count * 12, offset).reshape(frames, count,
                                                                                 12).astype(float)
        yield Clip(name=f'pose_{index:03d}',
                   rotations=values[..., :9].reshape(frames, count, 3, 3) / _FIXED_ONE,
                   translations=values[..., 9:])


def _world(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = _AXES @ rotation @ _AXES
    matrix[:3, 3] = _AXES @ translation * SCALE
    return matrix


def _local(rotations: np.ndarray, translations: np.ndarray, part: int,
           parent: int) -> tuple[np.ndarray, np.ndarray]:
    rotation, translation = rotations[..., part, :, :], translations[..., part, :]
    if parent != part:
        inverse = np.swapaxes(rotations[..., parent, :, :], -1, -2)
        rotation = inverse @ rotation
        translation = np.einsum('...ij,...j->...i', inverse,
                                translation - translations[..., parent, :])
    return _AXES @ rotation @ _AXES, translation @ _AXES * SCALE


def _add_joints(document: GLBDocument, names: Sequence[str], parents: Sequence[int],
                rotations: np.ndarray, translations: np.ndarray) -> list[int]:
    first = len(document.nodes)
    for part, name in enumerate(names):
        rotation, translation = _local(rotations, translations, part, parents[part])
        document.nodes.append({
            'name': name,
            'rotation': _quaternions(rotation[None])[0].tolist(),
            'translation': translation.tolist()
        })
    for part, parent in enumerate(parents):
        if parent != part:
            document.nodes[first + parent].setdefault('children', []).append(first + part)
    return list(range(first, first + len(names)))


def _vertices(scene: Scene) -> list[list[tuple[int, tuple[int, int, int]]]]:
    slots: list[tuple[int, tuple[int, int, int]]] = []
    parts: list[list[tuple[int, tuple[int, int, int]]]] = []
    for part, sector in enumerate(scene.sectors):
        vertices: list[tuple[int, tuple[int, int, int]]] = []
        for index in range(sector.count_a):
            offset = sector.verts_offset + index * 8
            position = (i16(scene.data, offset), i16(scene.data,
                                                     offset + 2), i16(scene.data, offset + 4))
            flags = u16(scene.data, offset + 6)
            if flags & _REFERENCE_FLAG:
                vertices.append(slots[position[1]] if position[1] < len(slots) else (part, (0, 0,
                                                                                            0)))
                continue
            vertices.append((part, position))
            if flags & _EXPORT_FLAG:
                slots.append((part, position))
        parts.append(vertices)
    return parts


def _textures(document: GLBDocument, scene: Scene) -> dict[int, tuple[int, int, int]]:
    try:
        tables = parse_lighting(scene.data, skip=len(scene.sectors))
        decoded = list(iter_decoded(scene.data, tables))
    except (IndexError, struct.error):
        log.debug('Scene has no texture tables.')
        return {}
    found: dict[int, tuple[int, int, int]] = {}
    for instance, pixels in decoded:
        image = Image.frombytes('RGB', (instance.width, instance.height), pixels).convert('RGBA')
        alpha = np.array(image)
        alpha[(alpha[..., :3] == TRANSPARENT_COLOR).all(-1)] = 0
        buffer = io.BytesIO()
        Image.fromarray(alpha).save(buffer, 'PNG')
        texture = document.add_image(buffer.getvalue(), 'image/png', f'{instance.checksum:08X}')
        document.materials.append({
            'alphaMode': 'MASK',
            'name': f'{instance.checksum:08X}',
            'pbrMetallicRoughness': {
                'baseColorTexture': {
                    'index': texture
                },
                'metallicFactor': 0.0
            }
        })
        found[instance.checksum] = (len(document.materials) - 1, instance.width, instance.height)
    return found


def _add_mesh(document: GLBDocument, skater: Skater, rotations: np.ndarray,
              translations: np.ndarray) -> int:
    scene = skater.scene
    materials = _textures(document, scene)
    checksums = scene.texture_checksums()
    untextured = -1
    batches: dict[int, list[tuple[int, tuple[int, int, int], tuple[float, float]]]] = {}
    for sector, vertices in zip(scene.sectors, _vertices(scene), strict=True):
        for face, slots in scene.triangles(sector):
            if face.is_hidden or any(face.corners[slot] >= len(vertices) for slot in slots):
                continue
            material, width, height = untextured, 1, 1
            if face.is_textured and face.texture_index < len(checksums) and (entry := materials.get(
                    checksums[face.texture_index])):
                material, width, height = entry
            for slot in reversed(slots):
                u, v = face.uvs[slot] if face.is_textured else (0.0, 0.0)
                batches.setdefault(material, []).append(
                    (*vertices[face.corners[slot]], (u * UV_SCALE / width, v * UV_SCALE / height)))
    if untextured in batches:
        document.materials.append({
            'name': 'untextured',
            'pbrMetallicRoughness': {
                'metallicFactor': 0.0
            }
        })
        batches[len(document.materials) - 1] = batches.pop(untextured)
    primitives = []
    for material, corners in sorted(batches.items()):
        positions = [(_AXES @ (rotations[owner] @ position + translations[owner]) * SCALE).tolist()
                     for owner, position, _ in corners]
        attributes = {
            'JOINTS_0':
                document.accessor(bytes(b for owner, _, _ in corners for b in (owner, 0, 0, 0)),
                                  ARRAY_BUFFER,
                                  componentType=UNSIGNED_BYTE,
                                  count=len(corners),
                                  type='VEC4'),
            'POSITION':
                document.floats(positions, 'VEC3', target=ARRAY_BUFFER, bounds=True),
            'WEIGHTS_0':
                document.floats([(1.0, 0.0, 0.0, 0.0)] * len(corners), 'VEC4', target=ARRAY_BUFFER)
        }
        if 'baseColorTexture' in document.materials[material]['pbrMetallicRoughness']:
            attributes['TEXCOORD_0'] = document.floats([uv for _, _, uv in corners],
                                                       'VEC2',
                                                       target=ARRAY_BUFFER)
        primitives.append({'attributes': attributes, 'material': material})
    document.meshes.append({'primitives': primitives})
    return len(document.meshes) - 1


def _quaternions(rotations: np.ndarray) -> np.ndarray:
    out = np.empty((len(rotations), 4))
    for index, matrix in enumerate(rotations):
        trace = float(np.trace(matrix))
        if trace > 0:
            s = 2.0 * np.sqrt(trace + 1.0)
            out[index] = ((matrix[2, 1] - matrix[1, 2]) / s, (matrix[0, 2] - matrix[2, 0]) / s,
                          (matrix[1, 0] - matrix[0, 1]) / s, s / 4)
        else:
            i = int(np.argmax(np.diag(matrix)))
            j, k = (i + 1) % 3, (i + 2) % 3
            s = 2.0 * np.sqrt(max(1.0 + matrix[i, i] - matrix[j, j] - matrix[k, k], 1e-12))
            values = np.zeros(4)
            values[i], values[j] = s / 4, (matrix[j, i] + matrix[i, j]) / s
            values[k], values[3] = (matrix[k, i] + matrix[i, k]) / s, (matrix[k, j] -
                                                                       matrix[j, k]) / s
            out[index] = values
        out[index] /= np.linalg.norm(out[index])
        if index and np.dot(out[index], out[index - 1]) < 0:
            out[index] = -out[index]
    return out


def _add_animation(document: GLBDocument, clip: Clip, parents: Sequence[int],
                   joints: Sequence[int]) -> None:
    frames = clip.rotations.shape[0]
    times = document.floats([(frame / FRAMES_PER_SECOND,) for frame in range(frames)],
                            'SCALAR',
                            bounds=True)
    channels, samplers = [], []
    for part, parent in enumerate(parents):
        rotation, translation = _local(clip.rotations, clip.translations, part, parent)
        for path, values, kind in (('rotation', _quaternions(rotation), 'VEC4'),
                                   ('translation', translation, 'VEC3')):
            samplers.append({
                'input': times,
                'interpolation': 'LINEAR',
                'output': document.floats(values.tolist(), kind)
            })
            channels.append({
                'sampler': len(samplers) - 1,
                'target': {
                    'node': joints[part],
                    'path': path
                }
            })
    document.animations.append({'channels': channels, 'name': clip.name, 'samplers': samplers})
