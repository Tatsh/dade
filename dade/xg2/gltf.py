"""
Turn Extreme-G models and levels into binary glTF (``.glb``).

One converter serves all three builds. The N64 games hand their geometry to the RSP as F3DEX2
display lists and the PC port kept that format wholesale, byte order aside, so
:py:mod:`dade.xg2.f3dex2` reads every one of them and only the endianness differs. A container
holding several models becomes one file per model rather than one crowded scene, since the game's
own grouping is by archive slot and says nothing about what belongs together in space.

Coordinates are written through unchanged. The models are already Y-up, which a bike's own bounds
say plainly -- 490 wide by 422 tall by 1154 long, the long axis being Z -- and that is glTF's
convention too, so rotating them only stands them on end.
"""
from __future__ import annotations

from itertools import starmap
from typing import TYPE_CHECKING
import logging
import math

from dade.common.exceptions import UnreachableState
from dade.common.gltf import ARRAY_BUFFER, TRIANGLES, UNSIGNED_BYTE, GLBDocument
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
    from collections.abc import Iterator, Mapping, Sequence

    from .bmc import BmcClip
    from .skeleton import Skeleton
    from .typing import Endian, Texture
    from .xg1_objects import ObjectModel, ObjectPlacement

__all__ = ('ANGLE_SCALE', 'BONE_LENGTH', 'build_clip_glb', 'build_glb', 'build_level_glb',
           'build_pc_glb', 'build_track_glb', 'iter_models', 'pc_bank_size')

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
"""Radians per unit of a motion curve: a binary angle, a full turn to 65536.

Confirmed against anatomy rather than assumed. Taking the widest sweep each single-axis joint makes
across all seventeen clips, and undoing the wraps first, this scale puts the knees at 130 and 122
degrees and the elbows at 136 and 145 -- against roughly 135 and 150 for a real one. Four
independent joints landing that close is not something a wrong scale produces; the next candidate
up, a turn to 16384, would have knees bending five hundred degrees.

:meta hide-value:
"""
BONE_LENGTH = 1.0
"""Length given to every bone, since the skeleton's own lengths have not been located.

**An assumption**, and the reason a played-back clip has the right articulation but uniform limb
proportions. The bone *directions* are read from the file and are exact.

:meta hide-value:
"""


def iter_models(blob: bytes, endian: Endian = '>') -> Iterator[tuple[str, bytes]]:
    """
    Yield each flat model inside a decoded archive entry.

    An entry is either a flat model, whose header is a segment-5 pointer table and so begins with
    ``0x05``, or a sub-archive holding several of them.

    Parameters
    ----------
    blob : bytes
        A decoded archive entry.
    endian : dade.xg2.typing.Endian
        Byte order of the blob.

    Yields
    ------
    tuple[str, bytes]
        A suffix naming the model within its entry, and the model itself.
    """
    # The table's first entry is a segment-5 address, so the segment number is the first byte on
    # the N64 and the fourth on the PC.
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
    Report how many bytes of vertex bank a PC model's display lists reach into.

    Parameters
    ----------
    model : bytes
        The model blob.

    Returns
    -------
    int
        The highest segment-8 offset any vertex load reaches, or zero when none do.
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


def _euler(x: float, y: float, z: float) -> tuple[float, float, float, float]:
    """
    Turn one frame's three joint curves into a quaternion.

    The axes are applied Z, then Y, then X, which is how Acclaim skeletons order a three-degree
    joint. That order is **not** confirmed against this game's own data; the skeleton records an
    axis code per joint (:py:attr:`dade.xg2.skeleton.Bone.axes`) whose meaning is still unknown.

    Parameters
    ----------
    x : float
        Curve value for the first axis, in the units :py:data:`ANGLE_SCALE` converts.
    y : float
        Second axis.
    z : float
        Third axis.

    Returns
    -------
    tuple[float, float, float, float]
        The rotation as ``x, y, z, w``, which is glTF's order.
    """
    hx, hy, hz = (v * ANGLE_SCALE / 2.0 for v in (x, y, z))
    sx, cx = math.sin(hx), math.cos(hx)
    sy, cy = math.sin(hy), math.cos(hy)
    sz, cz = math.sin(hz), math.cos(hz)
    return (sx * cy * cz - cx * sy * sz, cx * sy * cz + sx * cy * sz, cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz)


def _aligned(frames: list[tuple[float, float, float, float]]) \
        -> list[tuple[float, float, float, float]]:
    """
    Flip whichever frames sit on the far hemisphere from the one before.

    A quaternion and its negation are the same rotation, so a curve is free to cross between them,
    and the joint angles here do: they are binary angles that wrap. A viewer interpolating between
    two frames on opposite hemispheres takes the long way round and the limb spins, so each frame is
    put on the same side as its predecessor first.

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
        Pixel offset the geometry named, used to name the material.
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
        # into the vertex colours, which are written as COLOR_0 whenever the geometry is unlit, so
        # the factor stays white and lets them through. A lit mesh writes NORMAL instead and has no
        # colour of its own, so it keeps the grey stand-in.
        pbr['baseColorFactor'] = [1.0, 1.0, 1.0, 1.0] if not lit else list(_FALLBACK_COLOR)
    else:
        png = encode_rgba(texture.width, texture.height, texture.rgba)
        pbr['baseColorTexture'] = {
            'index': document.add_image(png, 'image/png', name),
            'texCoord': 0
        }
        name = f'{name}_{texture.pixel_format}_{texture.width}x{texture.height}'
    entry: dict[str, object] = {
        # The ROM itself culls nothing: its only geometry mode writes set G_LIGHTING and clear
        # G_CULL_BOTH, so the hardware draws both faces. Culling here anyway is what makes a track
        # readable from the outside, since the far wall of a tunnel otherwise draws over the near
        # one.
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
               scale: float = 1.0) -> dict[str, object]:
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
        'TEXCOORD_0': document.floats(coords, 'VEC2', target=ARRAY_BUFFER)
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
    Build a binary glTF for one Windows model, given the bank holding its vertices.

    Parameters
    ----------
    model : bytes
        The model blob, holding the display lists and the textures.
    vertices : bytes
        The buffer segment 8 addresses. The port fills this at run time, so nothing in the
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
    Build a binary glTF carrying one ``BMC`` motion clip.

    A clip is a run of degree-of-freedom curves rather than a pose per bone. Given the *skeleton*
    those curves drive -- :py:func:`dade.xg2.skeleton.parse_skeleton` reads it out of any rider
    model -- each curve can be attached to the joint it belongs to, and the result is a real
    hierarchy. Without one, the old behaviour stands: a node per channel, driven on Y, which keeps
    the values exact and plays back as 67 sliders.

    Two scales are **assumptions**, flagged here because they change how the motion looks rather
    than whether it is structurally right. :py:data:`ANGLE_SCALE` reads the curves as binary angles,
    a full turn to 65536, which suits their observed range of roughly plus or minus eight thousand;
    and :py:data:`BONE_LENGTH` gives every bone the same length, because the field holding the real
    one has not been found. The hierarchy, the channel-to-joint mapping, and the bone directions are
    all read from the file and cross-checked on fourteen riders.

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
        Frames per second the keyframe times are laid out at.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or :py:obj:`None` when the clip has no frames.

    Raises
    ------
    UnreachableState
        If a node this function just wrote does not carry a list of children.
    """
    if not clip.frames or not clip.channels:
        return None
    document = GLBDocument(generator)
    times = [(index / frame_rate,) for index in range(clip.frames)]
    input_accessor = document.floats(times, 'SCALAR', bounds=True)
    channels: list[dict[str, object]] = []
    samplers: list[dict[str, object]] = []

    def sampler(output: int, node: int, path: str) -> None:
        samplers.append({'input': input_accessor, 'interpolation': 'LINEAR', 'output': output})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': path}})

    if skeleton is None or skeleton.channels != len(clip.channels):
        for index, values in enumerate(clip.channels):
            document.nodes.append({
                'name': f'{clip.name}/dof{index:02d}',
                'translation': [0.0, 0.0, 0.0]
            })
            sampler(document.floats([(0.0, v, 0.0) for v in values], 'VEC3'), index, 'translation')
    else:
        # Node 0 is the root the clip's first six curves drive; a bone's node is its index plus one.
        document.nodes.append({'name': clip.name, 'children': [], 'translation': [0.0, 0.0, 0.0]})
        for bone in skeleton.bones:
            document.nodes.append({
                'name': bone.name,
                'children': [],
                'translation': [v * BONE_LENGTH for v in bone.direction]
            })
        for index, bone in enumerate(skeleton.bones):
            parent = 0 if bone.parent < 0 else bone.parent + 1
            children = document.nodes[parent]['children']
            if not isinstance(children, list):  # pragma: no cover
                msg = f"Node {parent} has a {type(children).__name__} for 'children', not a list."
                raise UnreachableState(msg)
            children.append(index + 1)

        root = clip.channels
        sampler(document.floats(list(zip(root[0], root[1], root[2], strict=True)), 'VEC3'), 0,
                'translation')
        turns = _aligned(list(starmap(_euler, zip(root[3], root[4], root[5], strict=True))))
        sampler(document.floats(turns, 'VEC4'), 0, 'rotation')
        for index, bone in enumerate(skeleton.bones):
            if not bone.dof:
                continue
            curves = clip.channels[bone.channel:bone.channel + bone.dof]
            # A joint turning about fewer than three axes leaves the rest at zero.
            padded = list(curves) + [[0.0] * clip.frames] * (3 - len(curves))
            rotations = list(starmap(_euler, zip(*padded, strict=True)))
            sampler(document.floats(rotations, 'VEC4'), index + 1, 'rotation')

    document.animations.append({'channels': channels, 'name': label, 'samplers': samplers})
    return document.finish(label)


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
        The game's own ``G_TEXTURE`` factor. Extreme-G issues
        ``gsSPTexture(0x8000, 0x8000, ...)``, a half, which is why its coordinates otherwise come
        out at twice the size they should be.
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
    Build one frame of an object's icon, in the object's own space.

    Each face takes a flat colour from its own normal rather than the stored per-vertex ones, and is
    wound twice: the plates are single sided and are approached from either way round.

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

    Every object shares a handful of images, so the material each one draws with is made once and
    reused; making one per mesh embeds the same glow image as many times as the level has objects.

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

    Each pickup becomes a node at its record's position, lifted by :py:data:`OBJECT_LIFT`, carrying
    one child per icon of its cycle. An animation swings the pickup on X and Z the way its update
    does and steps the children in and out with a scale curve, so the file plays back the icon
    cycling and the swing together. Flame columns have no icon and contribute only their glow.

    Two things the game does cannot be written into a glTF and are left out: the icons and the glow
    panels turn to face the eye every frame, which no static scene can express, and the glow's
    texture scrolls, which needs an animated sampler. The glow is written at the first step of that
    scroll.

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

    Every pickup swings identically -- the update reads no per-object term and they all start
    together -- so one rotation sampler drives all of them, and one scale sampler drives every node
    holding the same slot of a cycle of the same length.

    Parameters
    ----------
    document : dade.common.gltf.GLBDocument
        The document being built.
    name : str
        Name for the animation.
    swung : collections.abc.Sequence[int]
        Nodes carrying a pickup's swing.
    stepped : collections.abc.Mapping[tuple[int, int], collections.abc.Sequence[int]]
        Nodes holding one slot of a cycle, keyed by the cycle's length and the slot.
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
