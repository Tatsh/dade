"""
Turn Extreme-G models and levels into binary glTF (``.glb``).

One converter serves all three builds. The N64 games hand their geometry to the RSP as F3DEX2
display lists and the PC port retained that format wholesale, byte order aside.
:py:mod:`dade.xg2.f3dex2` therefore reads every one of them, and only the endianness differs. A
container with several models becomes one file per model rather than one crowded scene. The game's
grouping is by archive slot and establishes nothing about what belongs together in space.

Coordinates are written through unchanged. The models are already Y-up, as a bike's bounds show
plainly (490 wide by 422 tall by 1154 long, the long axis being Z), and that is glTF's convention
too. Rotating them only stands them on end.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import math
import struct

from dade.common.gltf import ARRAY_BUFFER, FLOAT, TRIANGLES, UNSIGNED_BYTE, GLBDocument
from dade.common.png import encode_rgba

from .f3dex2 import (
    Mesh,
    Vertex,
    _commands,
    _entry_points,
    _is_pc_display_list,
    parse_display_lists,
    parse_pc_display_lists,
    texcoords,
)
from .models import walk_sub_archive
from .rider import parse_rider
from .xg1_objects import (
    GLOW_ALPHA,
    GLOW_TEXTURE_KEY,
    ICON_TICKS,
    OBJECT_LIFT,
    TICK_HZ,
    face_colour,
    pickup_swing,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from .bmc import BmcClip
    from .skeleton import Skeleton
    from .typing import Basis, Endian, Quaternion, Texture, Vector
    from .xg1_objects import ObjectModel, ObjectPlacement

__all__ = ('ANGLE_SCALE', 'TRANSLATION_SCALE', 'build_clip_glb', 'build_glb', 'build_level_glb',
           'build_pc_glb', 'build_rider_glb', 'build_track_glb', 'iter_models', 'pc_bank_size',
           'pose_clip')

log = logging.getLogger(__name__)

_SEGMENT_5 = 0x05
_MIN_MODEL_BYTES = 16
_FALLBACK_COLOR = (0.75, 0.75, 0.78, 1.0)
_TRANSPARENT = 0xFF
_SIGN_BIT = 0x7F
_PC_G_VTX = 0x04
_VERTEX_BYTES = 16
_FRAME_RATE = 30.0

ANGLE_SCALE = math.tau / 65536.0
"""Radians per unit of a motion curve, a binary angle with a full turn to 65536.

The game drops the low four bits and turns by ``angle * pi / 4096`` per half angle
(``BuildPackedAxisAngleQuaternion``, ``0x800AF3E8`` in the N64 build). The half angle is
therefore ``angle * ANGLE_SCALE / 2``.

:meta hide-value:
"""
TRANSLATION_SCALE = 4.0
"""Vertex units per unit of a translation curve.

The pose decoder shifts a sample left by six into 28.4 fixed point, and the skinning drops the four
fraction bits again.

:meta hide-value:
"""
_ANGLE_DROP = 4
_ANGLE_MASK = 0xFFFF
# What each channel code drives, as (kind, axis) pairs in curve order. A code the decoder has no
# case for still consumes its curve.
_CODES: dict[int, tuple[tuple[str, int], ...]] = {
    0: (('t', 0),),
    1: (('t', 1),),
    2: (('t', 2),),
    3: (('r', 0),),
    4: (('r', 1),),
    5: (('r', 2),),
    7: (('t', 0), ('t', 1), ('t', 2)),
    8: (('t', 2), ('t', 1), ('t', 0)),
    9: (('r', 0), ('r', 1), ('r', 2)),
    10: (('r', 2), ('r', 1), ('r', 0))
}
_IGNORED = (('', 0),)


def iter_models(blob: bytes, endian: Endian = '>') -> Iterator[tuple[str, bytes]]:
    """
    Yield each flat model inside a decoded archive entry.

    An entry is either a flat model, whose header is a segment-5 pointer table and so begins with
    ``0x05``, or a sub-archive with several of them.

    Parameters
    ----------
    blob : bytes
        A decoded archive entry.
    endian : dade.xg2.typing.Endian
        Byte order of the blob.

    Yields
    ------
    tuple[str, bytes]
        A suffix identifying the model within its entry, and the model itself.
    """
    # The table's first entry is a segment-5 address, putting the segment number in the first byte
    # on the N64 and the fourth on the PC.
    tag = 0 if endian == '>' else 3

    def is_model(data: bytes) -> bool:
        return len(data) >= _MIN_MODEL_BYTES and data[tag] == _SEGMENT_5

    if is_model(blob):
        yield '', blob
        return
    for offset, size in walk_sub_archive(blob, endian):
        sub = blob[offset:offset + size]
        if is_model(sub):
            yield f'_{offset:06X}', sub


def pc_bank_size(model: bytes) -> int:
    """
    Report how many bytes of vertex bank a PC model's display lists address.

    Parameters
    ----------
    model : bytes
        The model blob.

    Returns
    -------
    int
        The highest segment-8 offset any vertex load addresses, or zero when none do.
    """
    needed = 0
    for start in _entry_points(model, '<'):
        if not _is_pc_display_list(model, start):
            continue
        for op, w0, w1 in _commands(model, start, '<'):
            if op == _PC_G_VTX:
                swapped = int.from_bytes(w0.to_bytes(4, 'little'), 'big')
                needed = max(needed, (w1 & 0xFFFFFF) + ((swapped >> 18) & 0x3F) * _VERTEX_BYTES)
    return needed


def _turn(basis: Basis, column: int, value: float) -> Quaternion:
    """
    Turn about one column of a basis by one curve value, as the game's pose decoder does.

    Parameters
    ----------
    basis : dade.xg2.typing.Basis
        The joint's basis, row by row.
    column : int
        Which column is the axis.
    value : float
        The curve value, a binary angle.

    Returns
    -------
    dade.xg2.typing.Quaternion
        The rotation.
    """
    half = ((int(value) & _ANGLE_MASK) >> _ANGLE_DROP << _ANGLE_DROP) * ANGLE_SCALE / 2.0
    sine = math.sin(half)
    return (basis[0][column] * sine, basis[1][column] * sine, basis[2][column] * sine,
            math.cos(half))


def _multiply(first: Quaternion, second: Quaternion) -> Quaternion:
    """
    Multiply two quaternions, *second* applied first.

    Parameters
    ----------
    first : dade.xg2.typing.Quaternion
        The rotation applied last.
    second : dade.xg2.typing.Quaternion
        The rotation applied first.

    Returns
    -------
    dade.xg2.typing.Quaternion
        The product.
    """
    x1, y1, z1, w1 = first
    x2, y2, z2, w2 = second
    return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 + y1 * w2 + z1 * x2 - x1 * z2,
            w1 * z2 + z1 * w2 + x1 * y2 - y1 * x2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)


def pose_clip(clip: BmcClip, skeleton: Skeleton) -> tuple[list[Vector], list[list[Quaternion]]]:
    """
    Decode every frame of a clip into the skeleton's joint rotations and root translation.

    Each joint reads its curves in the order its channel codes give. A turn is about a column of
    the joint's basis, and a joint's turns multiply together in that order, the first applied last.
    A translation code sets the root's translation whichever joint it belongs to, as the game's
    decoder does.

    Parameters
    ----------
    clip : dade.xg2.bmc.BmcClip
        The clip.
    skeleton : dade.xg2.skeleton.Skeleton
        The skeleton it drives.

    Returns
    -------
    tuple[list[dade.xg2.typing.Vector], list[list[dade.xg2.typing.Quaternion]]]
        The root's translation per frame in vertex units, and per joint the rotation per frame,
        joint 0 being the root and joint *n* bone *n - 1*.
    """
    joints = [(0, skeleton.root_dof, skeleton.root_axes, skeleton.root_basis)]
    joints += [(bone.channel, bone.dof, bone.axes, bone.basis) for bone in skeleton.bones]
    translations: list[list[float]] = [[0.0, 0.0, 0.0] for _ in range(clip.frames)]
    rotations: list[list[Quaternion]] = []
    for start, dof, codes, basis in joints:
        curves = iter(clip.channels[start:start + dof])
        turns: list[list[Quaternion]] = []
        for kind, axis in (step for code in codes for step in _CODES.get(code, _IGNORED)):
            if (curve := next(curves, None)) is None:
                break
            if kind == 't':
                for frame, value in enumerate(curve):
                    translations[frame][axis] = value * TRANSLATION_SCALE
            elif kind == 'r':
                turns.append([_turn(basis, axis, value) for value in curve])
        frames: list[Quaternion] = []
        for frame in range(clip.frames):
            rotation: Quaternion = (0.0, 0.0, 0.0, 1.0)
            for turn in turns:
                rotation = _multiply(rotation, turn[frame])
            frames.append(rotation)
        rotations.append(_aligned(frames))
    return [(x, y, z) for x, y, z in translations], rotations


def _add_joints(document: GLBDocument, skeleton: Skeleton) -> list[int]:
    """
    Add one node per joint, posed at rest, and return their indices.

    A joint's node sits at its pivot, its translation being the step from its parent's pivot. The
    game's transform for a joint is its parent's, then a turn about the pivot, and at rest every
    joint is therefore where its pivot is and the mesh is in its bind pose.

    Parameters
    ----------
    document : dade.common.gltf.GLBDocument
        The document being built.
    skeleton : dade.xg2.skeleton.Skeleton
        The skeleton.

    Returns
    -------
    list[int]
        Node indices, the root first and then one per bone.
    """
    first = len(document.nodes)
    pivots = [skeleton.root_pivot, *(bone.pivot for bone in skeleton.bones)]
    parents = [-1, *(bone.parent + 1 for bone in skeleton.bones)]
    names = ['root', *(bone.name for bone in skeleton.bones)]
    for index, (name, parent) in enumerate(zip(names, parents, strict=True)):
        origin = pivots[parent] if parent >= 0 else (0.0, 0.0, 0.0)
        node: dict[str, object] = {
            'name': name,
            'translation': [a - b for a, b in zip(pivots[index], origin, strict=True)]
        }
        if children := [first + child for child, owner in enumerate(parents) if owner == index]:
            node['children'] = children
        document.nodes.append(node)
    return list(range(first, first + len(names)))


def _add_clip(document: GLBDocument, clip: BmcClip, label: str, skeleton: Skeleton,
              joints: Sequence[int], frame_rate: float) -> None:
    """
    Add a clip as an animation of the joint nodes :py:func:`_add_joints` made.

    Parameters
    ----------
    document : dade.common.gltf.GLBDocument
        The document being built.
    clip : dade.xg2.bmc.BmcClip
        The clip.
    label : str
        Name for the animation.
    skeleton : dade.xg2.skeleton.Skeleton
        The skeleton the clip drives.
    joints : collections.abc.Sequence[int]
        The joint nodes, the root first.
    frame_rate : float
        Frames per second the keyframe times are spaced at.
    """
    translations, rotations = pose_clip(clip, skeleton)
    times = document.floats([(index / frame_rate,) for index in range(clip.frames)],
                            'SCALAR',
                            bounds=True)
    channels: list[dict[str, object]] = []
    samplers: list[dict[str, object]] = []
    pivot = skeleton.root_pivot
    outputs = [(document.floats([(x + pivot[0], y + pivot[1], z + pivot[2])
                                 for x, y, z in translations], 'VEC3'), joints[0], 'translation')]
    dof = [skeleton.root_dof, *(bone.dof for bone in skeleton.bones)]
    outputs += [(document.floats(frames, 'VEC4'), joints[index], 'rotation')
                for index, frames in enumerate(rotations) if dof[index]]
    for output, node, path in outputs:
        samplers.append({'input': times, 'interpolation': 'LINEAR', 'output': output})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': path}})
    document.animations.append({'channels': channels, 'name': label, 'samplers': samplers})


def _aligned(frames: list[tuple[float, float, float, float]]) \
        -> list[tuple[float, float, float, float]]:
    """
    Flip whichever frames sit on the far hemisphere from the one before.

    A quaternion and its negation are the same rotation, and a curve is therefore free to cross
    between them. The joint angles here do, being binary angles that wrap. A viewer interpolating
    between two frames on opposite hemispheres takes the long way round and the limb spins, and each
    frame is therefore put on the same side as its predecessor first.

    Parameters
    ----------
    frames : list[tuple[float, float, float, float]]
        One rotation per frame, as ``x, y, z, w``.

    Returns
    -------
    list[tuple[float, float, float, float]]
        The same rotations, sign-aligned.
    """
    out = list(frames[:1])
    for frame in frames[1:]:
        previous = out[-1]
        if sum(a * b for a, b in zip(previous, frame, strict=True)) < 0.0:
            out.append((-frame[0], -frame[1], -frame[2], -frame[3]))
        else:
            out.append(frame)
    return out


def _material(document: GLBDocument, texture: Texture | None, key: int | None, *, lit: bool) -> int:
    """
    Add the material for one image, or a plain grey stand-in when it could not be decoded.

    Parameters
    ----------
    document : dade.common.gltf.GLBDocument
        The document being built.
    texture : dade.xg2.typing.Texture | None
        The decoded image, if there is one.
    key : int | None
        Pixel offset the geometry specified, used to identify the material.
    lit : bool
        Whether the geometry writes packed normals rather than vertex colours.

    Returns
    -------
    int
        Index into the document's materials.
    """
    name = f'tex_{key:06X}' if key is not None else 'untextured'
    pbr: dict[str, object] = {'metallicFactor': 0.0, 'roughnessFactor': 0.9}
    if texture is None:
        # An untextured surface drawn by the flat combiner has its primitive colour already folded
        # into the vertex colours, written as COLOR_0 whenever the geometry is unlit. The factor
        # therefore stays white and lets them through. A lit mesh writes NORMAL instead and has no
        # colour, and it therefore retains the grey stand-in.
        pbr['baseColorFactor'] = [1.0, 1.0, 1.0, 1.0] if not lit else list(_FALLBACK_COLOR)
    else:
        png = encode_rgba(texture.width, texture.height, texture.rgba)
        pbr['baseColorTexture'] = {
            'index': document.add_image(png, 'image/png', name),
            'texCoord': 0
        }
        name = f'{name}_{texture.pixel_format}_{texture.width}x{texture.height}'
    entry: dict[str, object] = {
        # The ROM itself culls nothing. Its only geometry mode writes set G_LIGHTING and clear
        # G_CULL_BOTH, and the hardware therefore draws both faces. Culling here regardless is what
        # makes a track readable from the outside. The far wall of a tunnel otherwise draws over the
        # near wall.
        'doubleSided': False,
        'name': name,
        'pbrMetallicRoughness': pbr
    }
    translucent = texture is not None and any(texture.rgba[i] != _TRANSPARENT
                                              for i in range(3, len(texture.rgba), 4))
    if translucent:
        entry['alphaMode'] = 'BLEND'
    document.materials.append(entry)
    return len(document.materials) - 1


def _primitive(document: GLBDocument,
               mesh: Mesh,
               material: int,
               width: int,
               height: int,
               scale: float = 1.0,
               extra: Mapping[str, int] | None = None) -> dict[str, object]:
    """
    Build one glTF primitive from a mesh.

    Parameters
    ----------
    document : dade.common.gltf.GLBDocument
        The document being built.
    mesh : dade.xg2.f3dex2.Mesh
        The triangles drawn with one image.
    material : int
        Index of the material they draw with.
    width : int
        Width of that image, needed to normalise the texture coordinates.
    height : int
        Height of that image.
    scale : float
        Factor the game's ``G_TEXTURE`` applies to the coordinates.
    extra : collections.abc.Mapping[str, int] | None
        Further attributes and their accessors, such as a skin's ``JOINTS_0``.

    Returns
    -------
    dict[str, object]
        The primitive.
    """
    positions = [(float(v.x), float(v.y), float(v.z)) for v in mesh.vertices]
    coords = [texcoords(v, width, height, scale) for v in mesh.vertices]
    corners = [i for triangle in mesh.triangles for i in triangle]
    attributes = {
        'POSITION': document.floats(positions, 'VEC3', target=ARRAY_BUFFER, bounds=True),
        'TEXCOORD_0': document.floats(coords, 'VEC2', target=ARRAY_BUFFER),
        **(extra or {})
    }
    if mesh.lit:
        attributes['NORMAL'] = document.floats([_normal(v) for v in mesh.vertices],
                                               'VEC3',
                                               target=ARRAY_BUFFER)
    else:
        colors = bytes(b for v in mesh.vertices for b in (v.red, v.green, v.blue, v.alpha))
        attributes['COLOR_0'] = document.accessor(colors,
                                                  ARRAY_BUFFER,
                                                  componentType=UNSIGNED_BYTE,
                                                  count=len(mesh.vertices),
                                                  type='VEC4',
                                                  normalized=True)
    return {
        'attributes': attributes,
        'indices': document.indices(corners),
        'material': material,
        'mode': TRIANGLES
    }


def _normal(vertex: Vertex) -> tuple[float, float, float]:
    """
    Unpack a lit vertex's normal from the three signed bytes it shares with vertex colour.

    Parameters
    ----------
    vertex : dade.xg2.f3dex2.Vertex
        The vertex.

    Returns
    -------
    tuple[float, float, float]
        The unit normal, or ``(0, 1, 0)`` when the stored one has no length.
    """
    x, y, z = (c - 0x100 if c > _SIGN_BIT else c for c in (vertex.red, vertex.green, vertex.blue))
    length = math.sqrt(x * x + y * y + z * z)
    if not length:
        return (0.0, 1.0, 0.0)
    return (x / length, y / length, z / length)


def build_glb(model: bytes,
              textures: list[Texture],
              name: str,
              endian: Endian = '>',
              generator: str = 'dade xg2') -> bytes | None:
    """
    Build a binary glTF for one flat model.

    Parameters
    ----------
    model : bytes
        The model blob.
    textures : list[dade.xg2.typing.Texture]
        Images decoded from that same blob, matched to geometry by pixel offset.
    name : str
        Name for the scene and its single node.
    endian : dade.xg2.typing.Endian
        Byte order: ``>`` for the N64 builds, ``<`` for the PC port.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when the model draws nothing.
    """
    return _assemble(parse_display_lists(model, endian), textures, name, generator)


def build_pc_glb(model: bytes,
                 vertices: bytes,
                 textures: list[Texture],
                 name: str,
                 generator: str = 'dade xg2') -> bytes | None:
    """
    Build a binary glTF for one Windows model, given the bank with its vertices.

    Parameters
    ----------
    model : bytes
        The model blob, with the display lists and the textures.
    vertices : bytes
        The buffer segment 8 addresses. The port fills this at run time, and nothing in the
        game's files supplies it yet; see :py:func:`pc_bank_size` for how much is needed.
    textures : list[dade.xg2.typing.Texture]
        Images decoded from the model blob.
    name : str
        Name for the scene and its single node.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when the model draws nothing.
    """
    return _assemble(parse_pc_display_lists(model, vertices), textures, name, generator)


def _assemble(meshes: Sequence[Mesh],
              textures: list[Texture],
              name: str,
              generator: str,
              scale: float = 1.0) -> bytes | None:
    """
    Turn decoded meshes and images into a finished document.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when there is nothing to draw.
    """
    if not meshes:
        return None
    by_offset = {texture.offset: texture for texture in textures}
    document = GLBDocument(generator)
    primitives = []
    for mesh in meshes:
        texture = by_offset.get(mesh.texture) if mesh.texture is not None else None
        material = _material(document, texture, mesh.texture, lit=mesh.lit)
        width = texture.width if texture else 1
        height = texture.height if texture else 1
        primitives.append(_primitive(document, mesh, material, width, height, scale))
    document.meshes.append({'name': name, 'primitives': primitives})
    document.nodes.append({'mesh': 0, 'name': name})
    return document.finish(name)


def build_clip_glb(clip: BmcClip,
                   label: str,
                   skeleton: Skeleton | None = None,
                   frame_rate: float = _FRAME_RATE,
                   generator: str = 'dade xg2') -> bytes | None:
    """
    Build a binary glTF with one ``BMC`` motion clip.

    A clip is a run of degree-of-freedom curves rather than a pose per bone. Given the *skeleton*
    those curves drive (:py:func:`dade.xg2.skeleton.parse_skeleton` reads it out of any rider
    model), each curve is attached to the joint it belongs to and decoded as
    :py:func:`pose_clip` describes, on joints placed at the skeleton's pivots. Without one, the
    fallback writes a node per channel, driven on Y, preserving the values exactly and playing back
    as 67 sliders. :py:func:`build_rider_glb` writes the same animation with the rider's mesh
    bound to it.

    Parameters
    ----------
    clip : dade.xg2.bmc.BmcClip
        The parsed clip.
    label : str
        Name for the scene and the animation.
    skeleton : dade.xg2.skeleton.Skeleton | None
        The skeleton the clip drives. Without it, or when its channel count disagrees with the
        clip's, the node-per-channel fallback is used.
    frame_rate : float
        Frames per second the keyframe times are spaced at.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when the clip has no frames.
    """
    if not clip.frames or not clip.channels:
        return None
    document = GLBDocument(generator)
    if skeleton is not None and skeleton.channels == len(clip.channels):
        joints = _add_joints(document, skeleton)
        _add_clip(document, clip, label, skeleton, joints, frame_rate)
        return document.finish(label, joints[:1])
    times = document.floats([(index / frame_rate,) for index in range(clip.frames)],
                            'SCALAR',
                            bounds=True)
    channels: list[dict[str, object]] = []
    samplers: list[dict[str, object]] = []
    for index, values in enumerate(clip.channels):
        document.nodes.append({
            'name': f'{clip.name}/dof{index:02d}',
            'translation': [0.0, 0.0, 0.0]
        })
        samplers.append({
            'input': times,
            'interpolation': 'LINEAR',
            'output': document.floats([(0.0, v, 0.0) for v in values], 'VEC3')
        })
        channels.append({
            'sampler': len(samplers) - 1,
            'target': {
                'node': index,
                'path': 'translation'
            }
        })
    document.animations.append({'channels': channels, 'name': label, 'samplers': samplers})
    return document.finish(label)


def build_rider_glb(model: bytes,
                    textures: list[Texture],
                    clips: Iterable[tuple[str, BmcClip]],
                    name: str,
                    frame_rate: float = _FRAME_RATE,
                    generator: str = 'dade xg2') -> bytes | None:
    """
    Build a binary glTF of an N64 rider, skinned to its skeleton, with every clip that drives it.

    The mesh is written in its bind pose and bound with a glTF skin, one joint for the root and one
    per bone, each joint's inverse bind matrix undoing its pivot. The weights are the game's
    (:py:func:`dade.xg2.rider.parse_rider`). Each clip whose curve count matches the skeleton's
    becomes an animation of the joints, decoded as :py:func:`pose_clip` describes, and a viewer
    playing one moves the mesh as the game's software skinning does.

    Parameters
    ----------
    model : bytes
        The decompressed rider.
    textures : list[dade.xg2.typing.Texture]
        Images decoded from the same model.
    clips : collections.abc.Iterable[tuple[str, dade.xg2.bmc.BmcClip]]
        Candidate clips, each with a name for its animation.
    name : str
        Name for the scene, the mesh, and its node.
    frame_rate : float
        Frames per second the keyframe times are spaced at.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when *model* is not a rider or draws nothing.
    """
    if (rider := parse_rider(model)) is None or not rider.meshes:
        return None
    document = GLBDocument(generator)
    by_offset = {texture.offset: texture for texture in textures}
    primitives = []
    for mesh, weights in zip(rider.meshes, rider.weights, strict=True):
        texture = by_offset.get(mesh.texture) if mesh.texture is not None else None
        skinning = {
            'JOINTS_0':
                document.accessor(bytes(j for joints, _ in weights for j in joints),
                                  ARRAY_BUFFER,
                                  componentType=UNSIGNED_BYTE,
                                  count=len(weights),
                                  type='VEC4'),
            'WEIGHTS_0':
                document.floats([w for _, w in weights], 'VEC4', target=ARRAY_BUFFER)
        }
        primitives.append(
            _primitive(document,
                       mesh,
                       _material(document, texture, mesh.texture, lit=mesh.lit),
                       texture.width if texture else 1,
                       texture.height if texture else 1,
                       extra=skinning))
    document.meshes.append({'name': name, 'primitives': primitives})
    document.nodes.append({'mesh': 0, 'name': name, 'skin': 0})
    joints = _add_joints(document, rider.skeleton)
    pivots = [rider.skeleton.root_pivot, *(bone.pivot for bone in rider.skeleton.bones)]
    inverse = b''.join(
        struct.pack('<16f', 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -x, -y, -z,
                    1.0) for x, y, z in pivots)
    document.skins.append({
        'inverseBindMatrices':
            document.accessor(inverse, componentType=FLOAT, count=len(pivots), type='MAT4'),
        'joints':
            joints,
        'name':
            name,
        'skeleton':
            joints[0]
    })
    for label, clip in clips:
        if clip.frames and rider.skeleton.channels == len(clip.channels):
            _add_clip(document, clip, label, rider.skeleton, joints, frame_rate)
    return document.finish(name, [0, joints[0]])


def build_level_glb(meshes: Sequence[Mesh],
                    textures: list[Texture],
                    name: str,
                    scale: float = 1.0,
                    generator: str = 'dade xg2') -> bytes | None:
    """
    Build a binary glTF from meshes a level bytecode produced.

    Parameters
    ----------
    meshes : collections.abc.Sequence[dade.xg2.f3dex2.Mesh]
        Decoded level geometry.
    textures : list[dade.xg2.typing.Texture]
        Images from the same level, matched to geometry by pixel offset.
    name : str
        Name for the scene and its node.
    scale : float
        The game's ``G_TEXTURE`` factor. Extreme-G issues
        ``gsSPTexture(0x8000, 0x8000, ...)``, a half. Without it the coordinates come out at twice
        the size they should be.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when the level draws nothing.
    """
    return _assemble(meshes, textures, name, generator, scale)


def _icon_mesh(placement: ObjectPlacement, frame: int) -> Mesh:
    """
    Build one frame of an object's icon, in the object's space.

    Each face takes a flat colour from its normal rather than from the stored per-vertex ones, and
    is wound twice. The plates are single sided and are approached from either way round.

    Returns
    -------
    dade.xg2.f3dex2.Mesh
        The icon.
    """
    model = placement.icons[frame % len(placement.icons)]
    vertices: list[Vertex] = []
    triangles: list[tuple[int, int, int]] = []
    for at in range(0, len(model.indices), 3):
        red, green, blue = face_colour(model, at)
        first = len(vertices)
        for corner in range(3):
            x, y, z = model.positions[model.indices[at + corner]]
            vertices.append(Vertex(x, y, z, 0, 0, red, green, blue, _TRANSPARENT))
        triangles += [(first, first + 1, first + 2), (first + 2, first + 1, first)]
    return Mesh(None, False, vertices, triangles)  # ruff: ignore[boolean-positional-value-in-call]


def _glow_mesh(model: ObjectModel, placement: ObjectPlacement) -> Mesh:
    """
    Build one object's glow panels, in the object's own space.

    Returns
    -------
    dade.xg2.f3dex2.Mesh
        The panels.
    """
    vertices = [
        Vertex(x, y, z, *model.coords[index], *placement.glow, GLOW_ALPHA)
        for index, (x, y, z) in enumerate(model.positions)
    ]
    triangles: list[tuple[int, int, int]] = []
    for at in range(0, len(model.indices), 3):
        corner = (model.indices[at], model.indices[at + 1], model.indices[at + 2])
        triangles += [corner, corner[::-1]]
    return Mesh(lit=False, texture=GLOW_TEXTURE_KEY, triangles=triangles, vertices=vertices)


def _add_mesh(document: GLBDocument, mesh: Mesh, textures: Mapping[int, Texture],
              materials: dict[int | None, int], name: str, scale: float) -> int:
    """
    Add one object's mesh and return its index.

    Every object shares a handful of images, and the material each one draws with is therefore made
    once and reused. Making one per mesh embeds the same glow image once per object in the level.

    Returns
    -------
    int
        Index into the document's meshes.
    """
    texture = textures.get(mesh.texture) if mesh.texture is not None else None
    if mesh.texture not in materials:
        materials[mesh.texture] = _material(document, texture, mesh.texture, lit=mesh.lit)
    width = texture.width if texture else 1
    height = texture.height if texture else 1
    document.meshes.append({
        'name': name,
        'primitives': [_primitive(document, mesh, materials[mesh.texture], width, height, scale)]
    })
    return len(document.meshes) - 1


def build_track_glb(meshes: Sequence[Mesh],
                    textures: list[Texture],
                    placements: Sequence[ObjectPlacement],
                    glow: ObjectModel | None,
                    name: str,
                    scale: float = 1.0,
                    generator: str = 'dade xg2') -> bytes | None:
    """
    Build a binary glTF from a level's geometry and the objects placed around it.

    Each pickup becomes a node at its record's position, lifted by :py:data:`OBJECT_LIFT`, with one
    child per icon of its cycle. An animation swings the pickup on X and Z the way its update does
    and steps the children in and out with a scale curve, and the file therefore plays back the
    icon cycling and the swing together. Flame columns have no icon and contribute only their glow.

    Two behaviours cannot be written into a glTF and are omitted. The icons and the glow panels turn
    to face the eye every frame, beyond what a static scene can express, and the glow's texture
    scrolls, needing an animated sampler. The glow is written at the first step of that scroll.

    Parameters
    ----------
    meshes : collections.abc.Sequence[dade.xg2.f3dex2.Mesh]
        Decoded level geometry.
    textures : list[dade.xg2.typing.Texture]
        Images from the same level, matched to geometry by pixel offset, plus the baked glow image
        keyed by :py:data:`dade.xg2.xg1_objects.GLOW_TEXTURE_KEY`.
    placements : collections.abc.Sequence[dade.xg2.xg1_objects.ObjectPlacement]
        The objects the level places.
    glow : dade.xg2.xg1_objects.ObjectModel | None
        The panels every object's glow is drawn with.
    name : str
        Name for the scene and its nodes.
    scale : float
        The game's own ``G_TEXTURE`` factor.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when the level draws nothing.
    """
    if not meshes:
        return None
    if not placements:
        return _assemble(meshes, textures, name, generator, scale)
    by_offset = {texture.offset: texture for texture in textures}
    document = GLBDocument(generator)
    primitives = []
    for mesh in meshes:
        texture = by_offset.get(mesh.texture) if mesh.texture is not None else None
        material = _material(document, texture, mesh.texture, lit=mesh.lit)
        primitives.append(
            _primitive(document, mesh, material, texture.width if texture else 1,
                       texture.height if texture else 1, scale))
    document.meshes.append({'name': name, 'primitives': primitives})
    document.nodes.append({'mesh': 0, 'name': name})
    roots = [0]
    swung: list[int] = []
    stepped: dict[tuple[int, int], list[int]] = {}
    materials: dict[int | None, int] = {}
    for index, placement in enumerate(placements):
        if glow is not None:
            document.nodes.append({
                'mesh':
                    _add_mesh(document, _glow_mesh(glow, placement), by_offset, materials,
                              f'{name}/glow{index:02d}', scale),
                'name':
                    f'{name}/glow{index:02d}',
                'translation': [float(placement.x),
                                float(placement.y),
                                float(placement.z)]
            })
            roots.append(len(document.nodes) - 1)
        if not placement.icons:
            continue
        children = []
        for frame in range(len(placement.icons)):
            label = f'{name}/pickup{index:02d}/icon{frame}'
            document.nodes.append({
                'mesh':
                    _add_mesh(document, _icon_mesh(placement, frame), by_offset, materials, label,
                              scale),
                'name':
                    label,
                'scale': [1.0, 1.0, 1.0] if frame == 0 else [0.0, 0.0, 0.0]
            })
            children.append(len(document.nodes) - 1)
            stepped.setdefault((len(placement.icons), frame), []).append(len(document.nodes) - 1)
        document.nodes.append({
            'children':
                children,
            'name':
                f'{name}/pickup{index:02d}',
            'translation': [
                float(placement.x),
                float(placement.y + OBJECT_LIFT),
                float(placement.z)
            ]
        })
        roots.append(len(document.nodes) - 1)
        swung.append(len(document.nodes) - 1)
    _animate(document, name, swung, stepped)
    return document.finish(name, roots)


def _animate(document: GLBDocument, name: str, swung: Sequence[int],
             stepped: Mapping[tuple[int, int], Sequence[int]]) -> None:
    """
    Add the swing and the icon cycle as one animation.

    Every pickup swings identically, the update reading no per-object term and all of them starting
    together. One rotation sampler therefore drives all of them, and one scale sampler drives every
    node at the same slot of a cycle of the same length.

    Parameters
    ----------
    document : dade.common.gltf.GLBDocument
        The document being built.
    name : str
        Name for the animation.
    swung : collections.abc.Sequence[int]
        Nodes given a pickup's swing.
    stepped : collections.abc.Mapping[tuple[int, int], collections.abc.Sequence[int]]
        Nodes at one slot of a cycle, keyed by the cycle's length and the slot.
    """
    if not swung and not stepped:
        return
    longest = max((length for length, _ in stepped), default=1)
    ticks = longest * ICON_TICKS
    channels: list[dict[str, object]] = []
    samplers: list[dict[str, object]] = []
    turns = _aligned([_swing_rotation(tick / TICK_HZ) for tick in range(ticks + 1)])
    swing_input = document.floats([(tick / TICK_HZ,) for tick in range(ticks + 1)],
                                  'SCALAR',
                                  bounds=True)
    swing_output = document.floats(turns, 'VEC4')
    for node in swung:
        samplers.append({'input': swing_input, 'interpolation': 'LINEAR', 'output': swing_output})
        channels.append({
            'sampler': len(samplers) - 1,
            'target': {
                'node': node,
                'path': 'rotation'
            }
        })
    for (length, slot), nodes in sorted(stepped.items()):
        steps = [(step * ICON_TICKS / TICK_HZ,) for step in range(longest + 1)]
        shown = [(1.0, 1.0, 1.0) if step % length == slot else (0.0, 0.0, 0.0)
                 for step in range(longest + 1)]
        output = document.floats(shown, 'VEC3')
        source = document.floats(steps, 'SCALAR', bounds=True)
        for node in nodes:
            samplers.append({'input': source, 'interpolation': 'STEP', 'output': output})
            channels.append({
                'sampler': len(samplers) - 1,
                'target': {
                    'node': node,
                    'path': 'scale'
                }
            })
    document.animations.append({'channels': channels, 'name': name, 'samplers': samplers})


def _swing_rotation(seconds: float) -> tuple[float, float, float, float]:
    """
    Turn a moment of the icon's swing into a quaternion.

    Returns
    -------
    tuple[float, float, float, float]
        The rotation as ``x, y, z, w``.
    """
    angle_x, angle_z = pickup_swing(seconds)
    half_x, half_z = angle_x / 2.0, angle_z / 2.0
    sin_x, cos_x = math.sin(half_x), math.cos(half_x)
    sin_z, cos_z = math.sin(half_z), math.cos(half_z)
    # Z then X, matching the order the update applies its two angles.
    return (sin_x * cos_z, -sin_x * sin_z, cos_x * sin_z, cos_x * cos_z)
