"""
Assemble Amplitude's default FreQ avatar into one skinned, animated binary glTF.

The avatar is built from the eight parts of the ``db avatar parts`` section of
``gen/freq2_config.txt``, each a Milo scene, in the choices of ``default_settings``. A part's
``trans_root`` is reset to the identity and hung from the ``<trans_root>_joint.mesh`` of its
parent part: the torso from the lower body, the instrument, both arms, and the head from the torso,
and the two gears from the head. The lower body hangs from nothing and retains its stored
transform. Only the meshes reachable from a part's ``draw_root`` through draw lists are drawn, at
their finest level of detail.

A ``Rnd::Mesh`` vertex is placed by up to three transforms. With ``w1`` and ``w2`` the vertex's
two weights, its position ``p`` moves to ``(1 - w1 - w2) * p * W(owner) + w1 * p * B0 * W(bone0) +
w2 * p * B1 * W(bone1)``, where ``W`` is a world transform and ``B0`` and ``B1`` are the mesh's bind
transforms. Each ``B`` maps the owner's space into its bone's at rest. The three terms are therefore
written as one glTF skin over every bone of every part. A rigid mesh follows its owner alone.

Every part with an ``anims`` list plays the ``fbase_<bone>.tnm`` keys of the ``base_rnd`` scene, as
``AvatarPart`` sets them up. Rotation keys move every bone, translation keys only the pelvis and the
arm bones, and scale keys none, with translation interpolated linearly. Each arm is posed by
``ArmPart::SolveIK``. The ``?arm_h`` keys give the hand in the instrument's space, the ``?arm_l``
translation keys give the elbow's pole, and the upper arm and the forearm retain their lengths at
rest.

Each frame range of the ``db avatar anims`` section becomes one glTF animation, sampled every
:py:data:`SAMPLE_STEP` ticks, at every key inside the range, and at both ends, and never outside
the range. A frame is a song tick, :py:data:`TICKS_PER_BEAT` to a quarter note. An entry's first
range takes the entry's name, and each further range the entry's name and the range's key. One
animation plays one range on every part. The game plays the arm (pose) ranges over a body loop at
run time, and that layering is not reproduced.

The game is Z-up. A root node turns the avatar to glTF's Y-up, and every other transform is written
in the game's space.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import logging
import math
import struct

import numpy as np

from dade.common.gltf import ARRAY_BUFFER, FLOAT, UNSIGNED_SHORT, GLBDocument

from .dataarray import dtb_to_obj
from .mesh import _mat_textures
from .rnd import read_mesh, read_trans_anim
from .typing import AvatarArm, AvatarPart, AvatarTrack

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from .typing import DataArrayNode, RndMesh

__all__ = ('DEFAULT_BPM', 'SAMPLE_STEP', 'TICKS_PER_BEAT', 'export_default_avatar')

log = logging.getLogger(__name__)

DEFAULT_BPM = 120.0
"""Tempo the animations are timed at when none is given, in beats a minute.

:meta hide-value:
"""
SAMPLE_STEP = 20
"""Distance between the samples of an animation, in ticks.

:meta hide-value:
"""
TICKS_PER_BEAT = 480
"""Ticks in a quarter note.

:meta hide-value:
"""

_CONFIGS = ('gen/freq2_config.txt.bin', 'gen/cfg_freq2euro.txt.bin')
# Part numbers and their parents, in the order ``Avatar::Avatar`` creates them.
_PARENTS: Mapping[int, int | None] = {4: None, 3: 4, 7: 3, 0: 3, 1: 3, 2: 3, 6: 2, 5: 2}
_LEFT_ARM = 0
_ARM_PARTS = frozenset({0, 1})
_INSTRUMENT = 7
_ARM_BONE = 'arm_'
_PELVIS = 'pelvis'
_SLERP_EPSILON = 1e-5
_Y_UP = (-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))
_INFLUENCES = 4
_ARM_ANIMS = 2  # An arm's ``anims`` are its forearm, then its hand.
_RANGE_FIELDS = 3  # A frame range is its key, its start, and its length.
_OUTPUT = 'avatar_default.glb'


def _find(node: Sequence[DataArrayNode], key: str | int) -> list[DataArrayNode] | None:
    return next((child for child in node if isinstance(child, list) and child and child[0] == key),
                None)


def _symbol(node: Sequence[DataArrayNode], key: str) -> str | None:
    entry = _find(node, key)
    return entry[1] if entry is not None and len(entry) > 1 and isinstance(entry[1], str) else None


def _matrix(values: Sequence[float]) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:, :3] = np.reshape(values, (4, 3))
    return matrix


def _rotation(q: np.ndarray) -> np.ndarray:
    # The basis rows ``Rnd::MakeRotMatrix`` writes, the transpose of the column-vector rotation.
    x, y, z, w = q
    return np.array(((1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)),
                     (2 * (x * y - w * z), 1 - 2 * (z * z + x * x), 2 * (y * z + w * x)),
                     (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))))


def _quaternion(rows: np.ndarray) -> np.ndarray:
    m = rows.T
    if (trace := float(np.trace(m))) > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = np.array(
            ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, s / 4))
    else:
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = 2.0 * math.sqrt(1.0 + m[i, i] - m[j, j] - m[k, k])
        q = np.zeros(4)
        q[i], q[j], q[k] = s / 4, (m[j, i] + m[i, j]) / s, (m[k, i] + m[i, k]) / s
        q[3] = (m[k, j] - m[j, k]) / s
    result: np.ndarray = q / np.linalg.norm(q)
    return result


def _trs(local: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    scale = np.linalg.norm(local[:3, :3], axis=1)
    if np.linalg.det(local[:3, :3]) < 0:
        scale[2] = -scale[2]
    return local[3, :3], _quaternion(local[:3, :3] / scale[:, None]), scale


def _normalized(vector: np.ndarray) -> np.ndarray:
    result: np.ndarray = vector / np.linalg.norm(vector)
    return result


def _at_frame(frames: np.ndarray, frame: float) -> tuple[int, int, float]:
    # ``AtFrame``: clamped at both ends, and exact on a key.
    last = len(frames) - 1
    if frame <= frames[0]:
        return 0, 0, 0.0
    if frame >= frames[last]:
        return last, last, 0.0
    high = int(np.searchsorted(frames, frame, side='right'))
    low = high - 1
    if frames[low] == frame:
        return low, low, 0.0
    return low, high, float((frame - frames[low]) / (frames[high] - frames[low]))


def _slerp(frames: np.ndarray, values: np.ndarray, frame: float) -> np.ndarray:
    # ``QuatSlerp``: along the shorter arc, and linear between nearly equal keys.
    low, high, t = _at_frame(frames, frame)
    start: np.ndarray = values[low]
    end: np.ndarray = values[high]
    if t == 0:
        return start
    if (dot := float(start @ end)) < 0:
        end, dot = -end, -dot
    if 1.0 - dot <= _SLERP_EPSILON:
        return (1 - t) * start + t * end
    theta = math.acos(dot)
    return (math.sin((1 - t) * theta) * start + math.sin(t * theta) * end) / math.sin(theta)


def _lerp(frames: np.ndarray, values: np.ndarray, frame: float) -> np.ndarray:
    low, high, t = _at_frame(frames, frame)
    result: np.ndarray = (1 - t) * values[low] + t * values[high]
    return result


def _track(data: bytes) -> AvatarTrack:
    anim = read_trans_anim(data)
    return AvatarTrack(np.array([key.frame for key in anim.rotation_keys]),
                       np.array([key.value for key in anim.rotation_keys]).reshape(-1, 4),
                       np.array([key.frame for key in anim.translation_keys]),
                       np.array([key.value for key in anim.translation_keys]).reshape(-1, 3))


def _solve_arm(hand: np.ndarray, pole: np.ndarray, arm: AvatarArm,
               upper_rest: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # ``ArmPart::SolveIK``, with the hand and the pole already in the socket's space.
    wrist = hand[3, :3]
    reach = float(np.linalg.norm(wrist))
    to_shoulder = -wrist / reach
    axis = _normalized(np.cross(pole - wrist, to_shoulder))
    bend = np.cross(to_shoulder, axis)
    forearm_squared = arm.forearm_length * arm.forearm_length
    along = min((forearm_squared - arm.upper_length ** 2 + reach * reach) / (reach + reach),
                arm.forearm_length)
    elbow = to_shoulder * along + bend * math.sqrt(max(forearm_squared - along * along,
                                                       0.0)) + wrist
    side = axis if arm.left else -axis
    forearm_y = _normalized(wrist - elbow)
    forearm_x = _normalized(np.cross(forearm_y, side + hand[2, :3]))
    upper_y = _normalized(elbow)
    upper = upper_rest.copy()
    upper[:3, :3] = (np.cross(upper_y, side), upper_y, side)
    forearm = np.eye(4)
    forearm[:3, :3] = (forearm_x, forearm_y, np.cross(forearm_x, forearm_y))
    forearm[3, :3] = elbow
    return upper, forearm


class _Rig:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.parents: list[int] = []
        self.world: list[np.ndarray] = []
        self.local: list[np.ndarray] = []
        self.index: dict[str, int] = {}
        self.tracks: dict[int, AvatarTrack] = {}
        self.translated: set[int] = set()
        self.arms: list[AvatarArm] = []
        self.instrument: int | None = None

    def add(self, name: str, parent: int, world: np.ndarray) -> None:
        self.index[name] = len(self.names)
        self.names.append(name)
        self.parents.append(parent)
        self.world.append(world)
        self.local.append(world @ np.linalg.inv(self.world[parent]) if parent >= 0 else world)

    def animated(self) -> list[int]:
        return sorted({*self.tracks, *(j for arm in self.arms for j in arm[1:4])})

    def key_frames(self) -> np.ndarray:
        frames = [track.rotation_frames for track in self.tracks.values()]
        frames += [self.tracks[joint].translation_frames for joint in self.translated]
        return np.unique(np.concatenate(frames)) if frames else np.zeros(0)

    def pose(self, frame: float) -> list[np.ndarray]:
        local = [matrix.copy() for matrix in self.local]
        for joint, track in self.tracks.items():
            if len(track.rotations):
                local[joint][:3, :3] = _rotation(
                    _slerp(track.rotation_frames, track.rotations, frame))
            if joint in self.translated and len(track.translations):
                local[joint][3, :3] = _lerp(track.translation_frames, track.translations, frame)
        world: list[np.ndarray] = []
        for joint, parent in enumerate(self.parents):
            world.append(local[joint] @ world[parent] if parent >= 0 else local[joint])
        for arm in self.arms:
            # ``ArmPart::SetFrame``: the instrument's space mapped into the socket's.
            to_socket = (world[self.instrument] if self.instrument is not None else
                         np.eye(4)) @ np.linalg.inv(world[arm.socket])
            hand, pole = np.eye(4), np.zeros(3)
            if (keys := self.tracks.get(arm.hand)) is not None:
                if len(keys.translations):
                    hand[3, :3] = _lerp(keys.translation_frames, keys.translations, frame)
                if len(keys.rotations):
                    hand[:3, :3] = _rotation(_slerp(keys.rotation_frames, keys.rotations, frame))
            if (keys := self.tracks.get(arm.forearm)) is not None and len(keys.translations):
                pole = _lerp(keys.translation_frames, keys.translations, frame)
            local[arm.hand] = hand @ to_socket
            local[arm.upper], local[arm.forearm] = _solve_arm(
                local[arm.hand], (np.append(pole, 1.0) @ to_socket)[:3], arm, local[arm.upper])
        return local


def _config(root: Path) -> list[DataArrayNode] | None:
    for name in _CONFIGS:
        if (path := root / name).is_file():
            config, _ = dtb_to_obj(path.read_bytes())
            if (db := _find(config, 'db')) is not None:
                return _find(db, 'avatar')
    return None


def _parts(root: Path, avatar: Sequence[DataArrayNode]) -> Iterator[AvatarPart]:
    parts = _find(avatar, 'parts') or []
    defaults = _find(avatar, 'default_settings') or []
    for number in _PARENTS:
        data, setting = _find(parts, number), _find(defaults, number)
        if data is None or setting is None or (choice_name := _symbol(setting, 'type')) is None:
            continue
        choice = _find(_find(data, 'types') or [], choice_name)
        directory, trans_root, draw_root = (_symbol(data, key)
                                            for key in ('rnd_dir', 'trans_root', 'draw_root'))
        if choice is None or directory is None or trans_root is None or draw_root is None:
            log.warning('Avatar part %d is incomplete in the configuration.', number)
            continue
        anims = tuple(name for name in (_find(data, 'anims') or [])[1:] if isinstance(name, str))
        directory = directory.lower()
        if directory.endswith('.rnd'):  # ``InstrPart``: one scene, a mesh for each choice.
            mesh = f'instr_{choice[1]:02d}'
            yield AvatarPart(number, (root / directory.removesuffix('.rnd'),), mesh,
                             f'{trans_root}_joint', mesh, anims, '')
        else:
            yield AvatarPart(
                number,
                tuple(root / directory / name for name in choice[1:3]
                      if isinstance(name, str) and name), trans_root, f'{trans_root}_joint',
                draw_root, anims, None)


def _load(dirs: Sequence[Path]) -> tuple[dict[str, RndMesh], list[Path]]:
    meshes: dict[str, RndMesh] = {}
    materials: list[Path] = []
    for path in dirs:
        manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
        for entry in manifest['objects']:
            match entry['type']:
                case 'Mesh':
                    meshes[entry['name']] = read_mesh((path / entry['file']).read_bytes())
                case 'Mat':
                    materials.append(path / entry['file'])
    return meshes, materials


def _texture(dirs: Sequence[Path], materials: Sequence[Path]) -> bytes | None:
    pngs = {png.stem.lower(): png for path in dirs for png in path.glob('*.png')}
    for material in materials:
        if material.is_file():
            for texture in _mat_textures(material.read_bytes()):
                if (png := pngs.get(texture.rsplit('.', 1)[0].lower())) is not None:
                    return png.read_bytes()
    return None


def _subtree(meshes: Mapping[str, RndMesh], name: str,
             parent: str | None) -> Iterator[tuple[str, str | None]]:
    if name in meshes:
        yield name, parent
        for child in meshes[name].transform.children:
            yield from _subtree(meshes, child, name)


def _draws(meshes: Mapping[str, RndMesh], name: str) -> Iterator[str]:
    if (mesh := meshes.get(name)) is not None and mesh.showing:
        yield name
        for child in mesh.draws:
            yield from _draws(meshes, child)


def _attach(rig: _Rig, part: AvatarPart, meshes: Mapping[str, RndMesh],
            tracks: Mapping[str, AvatarTrack]) -> None:
    root = f'{part.trans_root}.mesh'
    socket = rig.index.get(f'{part.joint}.mesh', -1) if _PARENTS[part.number] is not None else -1
    stored = _matrix(meshes[root].transform.world)
    offset = np.linalg.inv(stored) @ rig.world[socket] if socket >= 0 else np.eye(4)
    for name, parent in _subtree(meshes, root, None):
        rig.add(name, rig.index[parent] if parent is not None else socket,
                _matrix(meshes[name].transform.world) @ offset)
    for bone in part.anims:
        if (joint := rig.index.get(f'{bone}.mesh')) is not None and (track :=
                                                                     tracks.get(bone)) is not None:
            rig.tracks[joint] = track
            if bone == _PELVIS or bone[1:].startswith(_ARM_BONE):
                rig.translated.add(joint)
    if part.number == _INSTRUMENT:
        rig.instrument = rig.index[root]
    if part.number in _ARM_PARTS and socket >= 0 and len(part.anims) >= _ARM_ANIMS:
        upper = rig.index[root]
        forearm, hand = (rig.index[f'{name}.mesh'] for name in part.anims[:_ARM_ANIMS])
        for joint in (forearm, hand):  # ``ArmPart::Rebuild`` hangs both from the socket.
            rig.parents[joint] = socket
            rig.local[joint] = rig.world[joint] @ np.linalg.inv(rig.world[socket])
        rig.arms.append(
            AvatarArm(socket, upper, forearm, hand, part.number == _LEFT_ARM,
                      float(np.linalg.norm(rig.world[upper][3, :3] - rig.world[forearm][3, :3])),
                      float(np.linalg.norm(rig.world[forearm][3, :3] - rig.world[hand][3, :3]))))


def _influences(owner: int, bones: Sequence[int],
                weights: Sequence[float]) -> list[tuple[int, float]]:
    merged: dict[int, float] = {owner: 1.0 - sum(weights)}
    for bone, weight in zip(bones, weights, strict=True):
        merged[bone] = merged.get(bone, 0.0) + weight
    used = [(joint, weight) for joint, weight in merged.items() if weight > 0]
    return used + [(0, 0.0)] * (_INFLUENCES - len(used))


def _primitive(document: GLBDocument, rig: _Rig, mesh: RndMesh, geometry: RndMesh,
               owner: int) -> dict[str, Any]:
    world = rig.world[owner]
    positions = np.array([vertex.position for vertex in geometry.vertices])
    positions = np.c_[positions, np.ones(len(positions))] @ world
    normals = np.array([vertex.normal
                        for vertex in geometry.vertices]) @ np.linalg.inv(world[:3, :3]).T
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=normals, where=lengths > 0)
    bones = [owner, owner]
    if mesh.bones is not None:
        bones = [rig.index.get(name, owner) for name in mesh.bones.names]
    influences = [
        _influences(owner, bones, vertex.weights if mesh.bones is not None else (0.0, 0.0))
        for vertex in geometry.vertices
    ]
    joints = b''.join(struct.pack('<4H', *(joint for joint, _ in row)) for row in influences)
    attributes = {
        'POSITION':
            document.floats(positions[:, :3].tolist(), 'VEC3', bounds=True, target=ARRAY_BUFFER),
        'NORMAL':
            document.floats(normals.tolist(), 'VEC3', target=ARRAY_BUFFER),
        'TEXCOORD_0':
            document.floats([vertex.uv for vertex in geometry.vertices],
                            'VEC2',
                            target=ARRAY_BUFFER),
        'JOINTS_0':
            document.accessor(joints,
                              ARRAY_BUFFER,
                              componentType=UNSIGNED_SHORT,
                              count=len(influences),
                              type='VEC4'),
        'WEIGHTS_0':
            document.floats([[weight for _, weight in row] for row in influences],
                            'VEC4',
                            target=ARRAY_BUFFER),
    }
    return {
        'attributes': attributes,
        'indices': document.indices([index for face in geometry.faces for index in face])
    }


def _add_skin(document: GLBDocument, rig: _Rig) -> None:
    document.nodes.append({
        'children': [joint + 1 for joint, parent in enumerate(rig.parents) if parent < 0],
        'name': 'avatar',
        'rotation': list(_Y_UP)
    })
    for joint, name in enumerate(rig.names):
        translation, rotation, scale = _trs(rig.local[joint])
        node: dict[str, Any] = {
            'name': name.removesuffix('.mesh'),
            'rotation': rotation.tolist(),
            'scale': scale.tolist(),
            'translation': translation.tolist()
        }
        if children := [child + 1 for child, parent in enumerate(rig.parents) if parent == joint]:
            node['children'] = children
        document.nodes.append(node)
    inverse = np.linalg.inv(np.array(rig.world))
    inverse[:, :, 3] = (0.0, 0.0, 0.0, 1.0)  # glTF requires the affine row exactly.
    document.skins.append({
        'inverseBindMatrices':
            document.accessor(inverse.astype('<f4').tobytes(),
                              componentType=FLOAT,
                              count=len(rig.world),
                              type='MAT4'),
        'joints':
            list(range(1,
                       len(rig.names) + 1)),
        'skeleton':
            0
    })


def _clips(avatar: Sequence[DataArrayNode]) -> Iterator[tuple[str, int, int]]:
    for entry in (_find(avatar, 'anims') or [])[1:]:
        if not isinstance(entry, list) or not entry or not isinstance(entry[0], str):
            continue
        ranges = [
            item for item in entry[1:] if isinstance(item, list) and len(item) >= _RANGE_FIELDS
        ]
        for position, (key, start, length, *_) in enumerate(ranges):
            if isinstance(start, (int, float)) and isinstance(length, (int, float)) and length > 0:
                yield (entry[0] if position == 0 else f'{entry[0]}_{key}', int(start),
                       int(start + length))


def _add_animations(document: GLBDocument, rig: _Rig, avatar: Sequence[DataArrayNode],
                    bpm: float) -> None:
    if not (animated := rig.animated()):
        return
    keys = rig.key_frames()
    cache: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for name, start, end in _clips(avatar):
        if (samplers := cache.get((start, end))) is None:
            frames = np.unique(
                np.concatenate((np.arange(start, end, SAMPLE_STEP, dtype=np.float64),
                                keys[(keys > start) & (keys < end)], (float(end),))))
            poses = [rig.pose(float(frame)) for frame in frames]
            times = document.floats(
                [((frame - start) / TICKS_PER_BEAT * 60.0 / bpm,) for frame in frames],
                'SCALAR',
                bounds=True)
            samplers = []
            for joint in animated:
                translations, rotations, scales = zip(*(_trs(pose[joint]) for pose in poses),
                                                      strict=True)
                aligned = np.array(rotations)
                for index in range(1, len(aligned)):
                    if aligned[index] @ aligned[index - 1] < 0:
                        aligned[index] = -aligned[index]
                for path, values, kind in (('translation', translations, 'VEC3'),
                                           ('rotation', aligned, 'VEC4'), ('scale', scales,
                                                                           'VEC3')):
                    samplers.append({
                        'node': joint + 1,
                        'path': path,
                        'sampler': {
                            'input': times,
                            'interpolation': 'LINEAR',
                            'output': document.floats(np.asarray(values).tolist(), kind)
                        }
                    })
            cache[start, end] = samplers
        document.animations.append({
            'channels': [{
                'sampler': index,
                'target': {
                    'node': sampler['node'],
                    'path': sampler['path']
                }
            } for index, sampler in enumerate(samplers)],
            'name': name,
            'samplers': [sampler['sampler'] for sampler in samplers]
        })


def export_default_avatar(root: Path, *, bpm: float = DEFAULT_BPM) -> Path | None:
    """
    Write the default FreQ avatar of an extracted Amplitude ``MAIN.ARK`` as one binary glTF.

    The GLB is written as ``avatar_default.glb`` beside the ``base_rnd`` scene (for the retail
    disc, ``freqmaker/avatar_default.glb``), with one skin over every bone and one animation for
    each frame range of the configuration. The decomposed Milo scenes (see
    :py:func:`dade.harmonix.milo.convert`) and the compiled configuration must still be present.

    Parameters
    ----------
    root : pathlib.Path
        The extraction root of ``MAIN.ARK``, the directory with ``gen`` and ``freqmaker``.
    bpm : float
        The tempo the animations are timed at, in beats a minute.

    Returns
    -------
    pathlib.Path | None
        The GLB, or ``None`` when the configuration, the base scene, or every part is missing.
    """
    if (avatar := _config(root)) is None or (base := _symbol(avatar, 'base_rnd')) is None:
        return None
    if not (base_dir := root / base.lower().removesuffix('.rnd')).is_dir():
        log.warning('The avatar base scene `%s` is missing.', base_dir)
        return None
    tracks = {
        path.stem.removeprefix('fbase_'): _track(path.read_bytes())
        for path in sorted(base_dir.glob('fbase_*.tnm'))
    }
    rig = _Rig()
    document = GLBDocument()
    drawn: list[tuple[AvatarPart, dict[str, RndMesh], list[Path]]] = []
    for part in _parts(root, avatar):
        if not all((path / 'manifest.json').is_file() for path in part.dirs):
            log.warning('Avatar part %d is missing a scene in `%s`.', part.number, part.dirs)
            continue
        meshes, materials = _load(part.dirs)
        if f'{part.trans_root}.mesh' not in meshes:
            log.warning('Avatar part %d has no `%s`.', part.number, part.trans_root)
            continue
        if part.material is not None:
            materials = [part.dirs[0] / meshes[f'{part.trans_root}.mesh'].material]
        _attach(rig, part, meshes, tracks)
        drawn.append((part, meshes, materials))
    if not rig.names:
        return None
    _add_skin(document, rig)
    roots = [0]
    for part, meshes, materials in drawn:
        primitives = []
        for name in _draws(meshes, f'{part.draw_root}.mesh'):
            mesh = meshes[name]
            geometry = meshes.get(mesh.geometry_owner, mesh)
            if not geometry.vertices:
                continue
            if (owner := rig.index.get(owner_name := mesh.transform_owner or name)) is None:
                log.warning('Avatar mesh `%s` follows `%s`, which is not a bone.', name, owner_name)
                continue
            primitives.append(_primitive(document, rig, mesh, geometry, owner))
        if not primitives:
            continue
        shading: dict[str, Any] = {'metallicFactor': 0.0}
        if (png := _texture(part.dirs, materials)) is not None:
            shading['baseColorTexture'] = {
                'index': document.add_image(png, 'image/png', part.draw_root)
            }
        document.materials.append({'name': part.draw_root, 'pbrMetallicRoughness': shading})
        for primitive in primitives:
            primitive['material'] = len(document.materials) - 1
        document.meshes.append({'name': part.draw_root, 'primitives': primitives})
        document.nodes.append({'mesh': len(document.meshes) - 1, 'name': part.draw_root, 'skin': 0})
        roots.append(len(document.nodes) - 1)
    _add_animations(document, rig, avatar, bpm)
    out = base_dir.parent / _OUTPUT
    out.write_bytes(document.finish('avatar_default', roots))
    log.debug('Avatar: %d bones, %d meshes, %d animations -> `%s`.', len(rig.names),
              len(document.meshes), len(document.animations), out)
    return out
