"""
Turn Max Payne level geometry into a binary glTF (``.glb``).

A level stores its geometry twice. The BSP faces split it for visibility, and a static mesh
container holds the geometry the game actually draws: a corner array shared by every mesh, then one
entry per placed mesh with its own vertices, normals and transform. The second form carries
Remedy's own texture coordinates and keeps props as separate placed objects, so it is used whenever
it can be read; the BSP faces are the fallback and are written untextured.

Faces are convex and are triangulated as fans, which is exact for convex polygons. Each fan is
wound to agree with the face's stored normal so that back-face culling shows a level from the
inside when the camera sits outside it, which is what a level viewer wants.

Each material's image is embedded. Targa images are re-encoded as PNG because glTF only carries PNG
and JPEG; JPEG data is embedded as it was stored.

Level coordinates are Y-up, which is glTF's convention, so positions are written through unchanged.
"""
from __future__ import annotations

from io import BytesIO
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
import json
import logging
import math
import struct

from PIL import Image

from .decals import DECAL_STEP, layer_faces

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .typing import (
        Corner,
        Level,
        Model,
        Placement,
        Polygon,
        PropAnimation,
        RenderMesh,
        StaticMesh,
        TextureImage,
        Vector3,
    )

__all__ = ('GLB_MAGIC', 'build_glb')

log = logging.getLogger(__name__)

GLB_MAGIC = b'glTF'
"""Magic starting every binary glTF.

:meta hide-value:
"""

_VERSION = 2
_JSON_CHUNK = b'JSON'
_BIN_CHUNK = b'BIN\x00'
_FLOAT = 5126
_UNSIGNED_INT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4
_REPEAT = 10497
_JPEG_MAGIC = b'\xff\xd8'
_PNG_MAGIC = b'\x89PNG'
_FALLBACK_COLOUR = (0.72, 0.72, 0.74, 1.0)
_NODRAW = 'nodraw'
_MAX_KEYFRAMES = 24
"""Keyframes kept per clip. The stored curves carry up to 256 samples of a smooth ease, which is
far more than the motion needs.

:meta hide-value:
"""
_STILL = 1e-6
"""Below this a channel's two poses are the same and the channel is not worth writing.

:meta hide-value:
"""
_SLERP_LINEAR = 0.9995
"""Above this the two rotations are close enough that a straight walk is indistinguishable, and
taking the arc would divide by nearly zero.

:meta hide-value:
"""
_NON_DRAWING = frozenset({'cameracollision', 'dummy'})
"""Material categories the engine does not draw.

Levels name these outright: anything ending in ``nodraw`` is collision geometry, and ``dummy``
carries Remedy's placeholder image. Keeping them would paper a level in magenta ``DUMMY`` text.

:meta hide-value:
"""

_SKY = 'skybox'
"""Category on the faces that close a level off where it opens to the sky.

These carry a placeholder image too -- teal ``SKYBOX`` text -- but unlike ``dummy`` they cannot
just be dropped. They are the only thing between a courtyard, an alley or a stretch of street and
nothing at all, so leaving them out puts a hole through the level wherever the game showed sky.
They are written with a flat colour instead, which a viewer can swap for a real sky.

:meta hide-value:
"""

_SKY_COLOUR = (0.29, 0.33, 0.40, 1.0)
"""Stand-in for the sky. Max Payne draws its own sky from the renderer's settings rather than from
anything the level stores, so there is nothing in the file to read: this is the dull overcast
blue-grey the game's nights are lit by.

:meta hide-value:
"""

_FLAT_FAN = 1e-9
"""Below this a fan triangle is a straight line and says nothing about which way its face points.

:meta hide-value:
"""

_UNLIT = 'KHR_materials_unlit'
"""Extension marking a material that takes its colour straight from the base colour.

:meta hide-value:
"""


def _pad(data: bytes, fill: bytes) -> bytes:
    return data + fill * (-len(data) % 4)


def _draws(level: Level, material_id: int) -> bool:
    """
    Report whether the engine draws faces using a material.

    Parameters
    ----------
    level : Level
        The level the material belongs to.
    material_id : int
        Identifier a face references.

    Returns
    -------
    bool
        :py:obj:`False` for collision-only and placeholder materials.
    """
    material = level.materials.get(material_id)
    if material is None:
        return True
    category = material.category.lower()
    return not (category.endswith(_NODRAW) or category in _NON_DRAWING)


def _wind(fan: list[tuple[int, int, int]], positions: Sequence[Vector3],
          normal: Vector3) -> list[tuple[int, int, int]]:
    """
    Reverse a fan whose corner order disagrees with its normal.

    The decision is taken from the first triangle that has any area. Levels put extra corners part
    way along a face's edges, where one polygon meets several, and a face whose first three corners
    are three of those is a straight line with no side to face. Reading the winding off it points
    the whole face the wrong way, and a floor drawn from below is a hole in the level seen from
    above.

    Parameters
    ----------
    fan : list[tuple[int, int, int]]
        Triangles as written.
    positions : collections.abc.Sequence[Vector3]
        Positions the triangles index.
    normal : Vector3
        The face's outward normal.

    Returns
    -------
    list[tuple[int, int, int]]
        The fan, reversed when needed so it winds counter-clockwise seen from the front.
    """
    for triangle in fan:
        a, b, c = (positions[i] for i in triangle)
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        facing = sum(x * n for x, n in zip(cross, normal, strict=True))
        if abs(facing) <= _FLAT_FAN:
            continue
        return fan if facing > 0.0 else [(z, y, x) for x, y, z in fan]
    return fan


def _image_payload(texture: TextureImage) -> tuple[bytes, str] | None:
    """
    Prepare an image for embedding, re-encoding Targa as PNG.

    Parameters
    ----------
    texture : TextureImage
        The image as the level stored it.

    Returns
    -------
    tuple[bytes, str] | None
        The bytes and their MIME type, or :py:obj:`None` if the image cannot be decoded.
    """
    if texture.data[:2] == _JPEG_MAGIC:
        return texture.data, 'image/jpeg'
    if texture.data[:4] == _PNG_MAGIC:
        return texture.data, 'image/png'
    try:
        with Image.open(BytesIO(texture.data)) as image:
            buffer = BytesIO()
            mode = 'RGBA' if image.mode in {'RGBA', 'LA', 'P'} else 'RGB'
            image.convert(mode).save(buffer, format='PNG')
    except OSError:
        log.warning('Could not decode `%s`.', texture.path)
        return None
    return buffer.getvalue(), 'image/png'


_OPAQUE = 240
_CLEAR = 15
_SOFT_FRACTION = 0.05
_MASK_MODE = 'MASK'
_ALPHA_CUTOFF = 0.5


def _compose_alpha(colour: bytes, mask: bytes) -> tuple[tuple[bytes, str], str] | None:
    """
    Put a mask's brightness into a colour image's alpha channel.

    The alpha mode follows the mask itself. A cutout -- foliage, a chain-link fence, a neon sign cut
    from its background -- is almost entirely black or white, and reads best as ``MASK`` because it
    needs no depth sorting. A mask with a real gradient, such as smoked glass or water, has to
    blend.

    Parameters
    ----------
    colour : bytes
        The colour image as the level stored it.
    mask : bytes
        The mask image as the level stored it.

    Returns
    -------
    tuple[tuple[bytes, str], str] | None
        The PNG and its MIME type, and the glTF alpha mode, or :py:obj:`None` when either image
        cannot be decoded.
    """
    try:
        payload, soft = _apply_mask(colour, mask)
    except OSError:
        return None
    return (payload, 'image/png'), 'BLEND' if soft > _SOFT_FRACTION else _MASK_MODE


def _apply_mask(colour: bytes, mask: bytes) -> tuple[bytes, float]:
    """
    Decode both images, put the mask into the colour's alpha, and measure the mask.

    Parameters
    ----------
    colour : bytes
        The colour image as the level stored it.
    mask : bytes
        The mask image as the level stored it.

    Returns
    -------
    tuple[bytes, float]
        The composed PNG and the share of mask pixels that are neither clear nor opaque.
    """
    with Image.open(BytesIO(colour)) as base, Image.open(BytesIO(mask)) as cover:
        rgb = base.convert('RGB')
        grey = cover.convert('L')
        if grey.size != rgb.size:
            grey = grey.resize(rgb.size)
        histogram = grey.histogram()
        rgb.putalpha(grey)
        buffer = BytesIO()
        rgb.save(buffer, format='PNG')
    return buffer.getvalue(), sum(histogram[_CLEAR + 1:_OPAQUE]) / max(sum(histogram), 1)


def _node_matrix(transform: Sequence[float]) -> list[float]:
    """
    Turn a stored four-by-three transform into a glTF node matrix.

    The transform is conjugated by the same depth mirror applied to vertices, which keeps the
    rotation's determinant positive so no renderer has to reverse winding for it.

    Parameters
    ----------
    transform : collections.abc.Sequence[float]
        Three basis rows then a translation, as ``M_Matrix4x3`` stores them.

    Returns
    -------
    list[float]
        Sixteen floats in the column-major order glTF expects.
    """
    a, b, c, t = (transform[0:3], transform[3:6], transform[6:9], transform[9:12])
    return [
        a[0], a[1], -a[2], 0.0, b[0], b[1], -b[2], 0.0, -c[0], -c[1], c[2], 0.0, t[0], t[1], -t[2],
        1.0
    ]


def _place(matrix: Sequence[float], point: Vector3) -> Vector3:
    """
    Put a point through a column-major node matrix.

    Parameters
    ----------
    matrix : collections.abc.Sequence[float]
        Sixteen floats from :py:func:`_node_matrix`.
    point : Vector3
        A point in the node's own space.

    Returns
    -------
    Vector3
        The point in the scene's space.
    """
    x, y, z = point
    return (matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
            matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
            matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14])


def _turn(matrix: Sequence[float], vector: Vector3) -> Vector3:
    """
    Put a direction through a column-major node matrix, leaving the translation out.

    Parameters
    ----------
    matrix : collections.abc.Sequence[float]
        Sixteen floats from :py:func:`_node_matrix`.
    vector : Vector3
        A direction in the node's own space.

    Returns
    -------
    Vector3
        The direction in the scene's space.
    """
    x, y, z = vector
    return (matrix[0] * x + matrix[4] * y + matrix[8] * z,
            matrix[1] * x + matrix[5] * y + matrix[9] * z,
            matrix[2] * x + matrix[6] * y + matrix[10] * z)


def _decompose(transform: Sequence[float]) -> tuple[list[float], list[float], list[float]]:
    """
    Split a stored transform into the translation, rotation and scale a glTF node animates on.

    A node carrying a ``matrix`` cannot be animated, so an animated prop has to be written as three
    separate properties instead. The split is taken from :py:func:`_node_matrix`'s output so a prop
    lands in exactly the same place whether or not it moves.

    Parameters
    ----------
    transform : collections.abc.Sequence[float]
        Three basis rows then a translation, as ``M_Matrix4x3`` stores them.

    Returns
    -------
    tuple[list[float], list[float], list[float]]
        The translation, the rotation as an ``xyzw`` quaternion, and the scale.
    """
    matrix = _node_matrix(transform)
    columns = [matrix[0:3], matrix[4:7], matrix[8:11]]
    scale = [math.sqrt(sum(v * v for v in column)) or 1.0 for column in columns]
    # A negative determinant would make the rotation a reflection, which no quaternion can hold;
    # the mirror conjugation is built to avoid one, and folding it into the scale keeps the node
    # correct if a level ever contains it.
    left, middle, right = (columns[i] for i in range(3))
    determinant = (left[0] * (middle[1] * right[2] - middle[2] * right[1]) - left[1] *
                   (middle[0] * right[2] - middle[2] * right[0]) + left[2] *
                   (middle[0] * right[1] - middle[1] * right[0]))
    if determinant < 0:
        scale[0] = -scale[0]
    rotation = [[columns[c][r] / scale[c] for c in range(3)] for r in range(3)]
    return [matrix[12], matrix[13], matrix[14]], _quaternion(rotation), scale


def _quaternion(rotation: Sequence[Sequence[float]]) -> list[float]:
    """
    Turn a rotation matrix into an ``xyzw`` quaternion.

    Parameters
    ----------
    rotation : collections.abc.Sequence[collections.abc.Sequence[float]]
        Three rows of three, orthonormal.

    Returns
    -------
    list[float]
        The quaternion, normalised.
    """
    trace = rotation[0][0] + rotation[1][1] + rotation[2][2]
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        out = [(rotation[2][1] - rotation[1][2]) / scale, (rotation[0][2] - rotation[2][0]) / scale,
               (rotation[1][0] - rotation[0][1]) / scale, 0.25 * scale]
    else:
        # Pivot on the largest diagonal entry, which keeps the divisor away from zero.
        axis = max(range(3), key=lambda i: rotation[i][i])
        other, third = (axis + 1) % 3, (axis + 2) % 3
        scale = math.sqrt(1.0 + rotation[axis][axis] - rotation[other][other] -
                          rotation[third][third]) * 2.0
        out = [0.0, 0.0, 0.0, (rotation[third][other] - rotation[other][third]) / scale]
        out[axis] = 0.25 * scale
        out[other] = (rotation[other][axis] + rotation[axis][other]) / scale
        out[third] = (rotation[third][axis] + rotation[axis][third]) / scale
    length = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / length for v in out]


def _keyframes(duration: float, curve: Sequence[float],
               total: float) -> tuple[list[float], list[float]]:
    """
    Thin one curve to a manageable number of keyframes and normalise it.

    Parameters
    ----------
    duration : float
        How long the clip runs.
    curve : collections.abc.Sequence[float]
        The curve's samples, evenly spaced across the duration.
    total : float
        What the curve's last sample means as a whole, so the samples come out as fractions.

    Returns
    -------
    tuple[list[float], list[float]]
        The keyframe times and the fraction of the motion done at each.
    """
    # Round the step up so that adding the final sample back cannot push the count over.
    step = max(1, -(-(len(curve) - 1) // (_MAX_KEYFRAMES - 1)))
    picked = list(range(0, len(curve), step))
    if picked[-1] != len(curve) - 1:
        picked.append(len(curve) - 1)
    last = max(len(curve) - 1, 1)
    return ([duration * index / last
             for index in picked], [curve[index] / total for index in picked])


def _lerp(start: Sequence[float], end: Sequence[float], at: float) -> list[float]:
    """
    Walk straight from one vector to another.

    Parameters
    ----------
    start : collections.abc.Sequence[float]
        The vector at nought.
    end : collections.abc.Sequence[float]
        The vector at one.
    at : float
        How far along.

    Returns
    -------
    list[float]
        The vector at *at*.
    """
    return [a + (b - a) * at for a, b in zip(start, end, strict=True)]


def _slerp(start: Sequence[float], end: Sequence[float], at: float) -> list[float]:
    """
    Walk from one quaternion to another along the shorter arc.

    Straight interpolation would make a door swing at an uneven rate and, for the wide arcs the
    game uses, visibly cut the corner.

    Parameters
    ----------
    start : collections.abc.Sequence[float]
        The rotation at nought, as ``xyzw``.
    end : collections.abc.Sequence[float]
        The rotation at one.
    at : float
        How far along.

    Returns
    -------
    list[float]
        The rotation at *at*, normalised.
    """
    dot = sum(a * b for a, b in zip(start, end, strict=True))
    # A quaternion and its negation are the same rotation; flipping picks the shorter way round.
    target = list(end) if dot >= 0.0 else [-v for v in end]
    dot = abs(dot)
    if dot > _SLERP_LINEAR:
        out = _lerp(start, target, at)
    else:
        angle = math.acos(dot)
        near = math.sin((1.0 - at) * angle) / math.sin(angle)
        far = math.sin(at * angle) / math.sin(angle)
        out = [a * near + b * far for a, b in zip(start, target, strict=True)]
    length = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / length for v in out]


def _mirror(vector: Vector3) -> Vector3:
    """
    Mirror a vector along the depth axis.

    Max Payne is a Direct3D game and stores a left-handed world; glTF is right-handed. Without the
    conversion every level comes out as its own mirror image, which only shows up on signage: the
    Choir Communications billboard reads backwards.

    Parameters
    ----------
    vector : Vector3
        A position or normal in the level's own space.

    Returns
    -------
    Vector3
        The vector with its depth component negated.
    """
    return (vector[0], vector[1], -vector[2])


class _Document:
    """
    Builds a glTF document as meshes are added.

    Parameters
    ----------
    level : Level
        The level being converted. Its images are embedded up front so materials can refer to them.
    """
    def __init__(self, level: Level) -> None:
        self._level = level
        self._blob = bytearray()
        self._by_path: dict[str, int] = {}
        self._by_material: dict[tuple[int, int], int] = {}
        self._sky_material: int | None = None
        self._by_lightmap: dict[int, int | None] = {}
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []
        self.meshes: list[dict[str, Any]] = []
        self.nodes: list[dict[str, Any]] = []
        self.materials: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.textures: list[dict[str, Any]] = []
        self.animations: list[dict[str, Any]] = []
        self._raw = {texture.path: texture.data for texture in level.textures}
        self._masked: dict[tuple[str, str], tuple[int, str]] = {}
        self._by_model: dict[str, int] = {}
        # A mask is only ever read through the material that names it, so embedding it on its own
        # would double its weight for nothing.
        masks = {m.alpha for m in level.materials.values() if m.alpha}
        for texture in level.textures:
            if texture.path in masks:
                continue
            payload = _image_payload(texture)
            if payload is None:
                continue
            self._by_path.setdefault(texture.path, self._add_texture(payload, texture.path))

    def add_animation(self, node: int, mesh: str, clip: PropAnimation) -> bool:
        """
        Add one clip as a glTF animation driving a node's translation and rotation.

        The level drives the two separately: one curve gives the distance travelled in world units
        and the other how far the prop has turned, each with its own sample count. Both are walked
        and baked into keyframes, which leaves nothing for a viewer to interpolate differently, and
        is why the samples are thinned first -- a crane's curve carries 4096 of them.

        A channel whose two poses agree is left out, so a hinged door gets rotation alone.

        Parameters
        ----------
        node : int
            Index of the node the clip drives.
        mesh : str
            The prop's name, which the clip's name is appended to.
        clip : PropAnimation
            The clip.

        Returns
        -------
        bool
            Whether the clip drove anything.
        """
        start, end = _decompose(clip.start), _decompose(clip.end)
        travel = math.dist(start[0], end[0])
        turn = 1.0 - abs(sum(a * b for a, b in zip(start[1], end[1], strict=True)))

        def slide(at: float) -> list[float]:
            return _lerp(start[0], end[0], at)

        def spin(at: float) -> list[float]:
            return _slerp(start[1], end[1], at)

        channels: list[dict[str, Any]] = []
        samplers: list[dict[str, Any]] = []
        walks = (
            ('translation', 'VEC3', clip.distance, travel, travel, slide),
            ('rotation', 'VEC4', clip.turn, turn, 1.0, spin),
        )
        for path, kind, curve, moves, total, pose in walks:
            if moves <= _STILL or not curve:
                continue
            times, progress = _keyframes(clip.duration, curve, total)
            values = [pose(at) for at in progress]
            size = len(values[0])
            samplers.append({
                'input':
                    self.accessor(struct.pack(f'<{len(times)}f', *times),
                                  None,
                                  componentType=_FLOAT,
                                  count=len(times),
                                  max=[max(times)],
                                  min=[min(times)],
                                  type='SCALAR'),
                'interpolation':
                    'LINEAR',
                'output':
                    self.accessor(b''.join(struct.pack(f'<{size}f', *value) for value in values),
                                  None,
                                  componentType=_FLOAT,
                                  count=len(values),
                                  type=kind)
            })
            channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': path}})
        if not channels:
            return False
        self.animations.append({
            'channels': channels,
            # The prop and the clip are both named by the level, and a clip name is only unique
            # within its prop, so the two together are what a viewer can list and a script can
            # match: `DO_Animate("open1")` sent to `::Sanctum Corridor::door01.DO`.
            'name': f'{mesh}/{clip.name}',
            'samplers': samplers
        })
        return True

    def settle(self, node: int, matrix: Sequence[float]) -> None:
        """
        Put a node back on a matrix after its clips turned out to drive nothing.

        Parameters
        ----------
        node : int
            Index of the node.
        matrix : collections.abc.Sequence[float]
            The node's four-by-three transform.
        """
        entry = self.nodes[node]
        for key in ('rotation', 'scale', 'translation'):
            entry.pop(key, None)
        entry['matrix'] = _node_matrix(matrix)

    def _add_texture(self, payload: tuple[bytes, str], name: str) -> int:
        """
        Embed one image and give it a texture.

        Parameters
        ----------
        payload : tuple[bytes, str]
            The encoded image and its MIME type.
        name : str
            Name for the image.

        Returns
        -------
        int
            Index into the document's textures.
        """
        self.images.append({
            'bufferView': self._add_view(payload[0]),
            'mimeType': payload[1],
            'name': name
        })
        self.textures.append({'sampler': 0, 'source': len(self.images) - 1})
        return len(self.textures) - 1

    def masked_texture(self, colour: str, mask: str) -> tuple[int, str] | None:
        """
        Compose a colour image with its alpha mask, reusing the result across materials.

        Parameters
        ----------
        colour : str
            Path of the colour image.
        mask : str
            Path of the mask image.

        Returns
        -------
        tuple[int, str] | None
            The texture index and the glTF alpha mode, or :py:obj:`None` when either image cannot
            be decoded.
        """
        if (found := self._masked.get((colour, mask))) is not None:
            return found
        composed = _compose_alpha(self._raw.get(colour, b''), self._raw.get(mask, b''))
        if composed is None:
            log.warning('Could not mask `%s` with `%s`.', colour, mask)
            return None
        payload, mode = composed
        index = self._add_texture(payload, f'{colour} + {mask}')
        self._masked[colour, mask] = (index, mode)
        return index, mode

    def _add_view(self, payload: bytes, target: int | None = None) -> int:
        self._blob.extend(b'\x00' * (-len(self._blob) % 4))
        view: dict[str, Any] = {
            'buffer': 0,
            'byteLength': len(payload),
            'byteOffset': len(self._blob)
        }
        if target is not None:
            view['target'] = target
        self._blob.extend(payload)
        self.views.append(view)
        return len(self.views) - 1

    def accessor(self, payload: bytes, target: int | None, **extra: Any) -> int:
        """
        Append attribute or index data and describe it with an accessor.

        Parameters
        ----------
        payload : bytes
            The raw data.
        target : int | None
            glTF buffer target, or :py:obj:`None` for data a vertex puller never reads, such as an
            animation's keyframes.
        extra : Any
            Remaining accessor fields.

        Returns
        -------
        int
            Index into the document's accessors.
        """
        self.accessors.append({'bufferView': self._add_view(payload, target), **extra})
        return len(self.accessors) - 1

    def model_material(self, name: str, model: Model, images: Mapping[str, TextureImage]) -> int:
        """
        Add a material belonging to a model rather than to the level.

        A model brings its own library, naming an image file that the caller was asked to read in
        beside it. Materials are keyed by that file name so two NPCs sharing a texture share it here
        too.

        Parameters
        ----------
        name : str
            The material's name in the model's library.
        model : Model
            The model the material belongs to.
        images : collections.abc.Mapping[str, TextureImage]
            The model's images, keyed by lowercased file name.

        Returns
        -------
        int
            Index into the document's materials.
        """
        file = model.materials.get(name, '')
        if (found := self._by_model.get(file.lower())) is not None:
            return found
        pbr: dict[str, Any] = {'metallicFactor': 0.0, 'roughnessFactor': 0.9}
        texture = images.get(file.lower())
        payload = _image_payload(texture) if texture else None
        if payload is None:
            pbr['baseColorFactor'] = list(_FALLBACK_COLOUR)
        else:
            pbr['baseColorTexture'] = {'index': self._add_texture(payload, file), 'texCoord': 0}
        self.materials.append({
            'doubleSided': False,
            'name': f'{name} ({file})' if file else name,
            'pbrMetallicRoughness': pbr
        })
        self._by_model[file.lower()] = len(self.materials) - 1
        return len(self.materials) - 1

    def material(self, key: tuple[int, int]) -> int:
        """
        Return the glTF material for a level material and lightmap pair, creating it once.

        A face names both the material it draws with and which of the level's baked lighting
        atlases lights it, so the two together decide the material a primitive needs. The atlas
        goes in the occlusion slot on the second coordinate set: glTF has no slot that multiplies a
        baked lightmap into the base colour, and occlusion is the one a plain viewer darkens with
        rather than ignoring. A viewer after the game's own look should multiply that texture's
        colour into the base rather than treating it as ambient occlusion.

        Parameters
        ----------
        key : tuple[int, int]
            The material identifier a face references and the atlas that lights it.

        Returns
        -------
        int
            Index into the document's materials.
        """
        if key in self._by_material:
            return self._by_material[key]
        material_id, lightmap = key
        material = self._level.materials.get(material_id)
        pbr: dict[str, Any] = {'metallicFactor': 0.0, 'roughnessFactor': 0.9}
        if material and material.category.lower() == _SKY:
            return self._sky()
        mode = ''
        index = None
        if material and material.alpha:
            if (masked := self.masked_texture(material.image, material.alpha)) is not None:
                index, mode = masked
        elif material:
            index = self._by_path.get(material.image)
        if index is None:
            pbr['baseColorFactor'] = list(_FALLBACK_COLOUR)
        else:
            pbr['baseColorTexture'] = {'index': index, 'texCoord': 0}
        # A material whose image carries its own alpha says how to blend it rather than naming a
        # mask to composite, so there is nothing to build and the mode is taken as given.
        if not mode and material:
            mode = material.blend
        name = material.texture if material else f'material_{material_id}'
        entry: dict[str, Any] = {
            # A cut-out is a flat card meant to be seen from either side, so it cannot be culled,
            # and a material may ask for both sides outright.
            'doubleSided': bool(mode) or bool(material and material.dual_sided),
            'name': name,
            'pbrMetallicRoughness': pbr
        }
        if (atlas := self._lightmap(lightmap)) is not None:
            entry['occlusionTexture'] = {'index': atlas, 'texCoord': 1}
            entry['name'] = f'{name} + lightmap {lightmap}'
        if mode:
            entry['alphaMode'] = mode
            if mode == _MASK_MODE:
                entry['alphaCutoff'] = _ALPHA_CUTOFF
        self.materials.append(entry)
        self._by_material[key] = len(self.materials) - 1
        return len(self.materials) - 1

    def _sky(self) -> int:
        """
        Give every skybox face one flat material, made once and shared.

        Returns
        -------
        int
            Index into the document's materials.
        """
        if self._sky_material is None:
            self.materials.append({
                # Sky is not a surface and must not shade, so it is written unlit. A viewer that
                # does not know the extension still gets the same colour, just lit.
                'extensions': {
                    _UNLIT: {}
                },
                'name': _SKY,
                'pbrMetallicRoughness': {
                    'baseColorFactor': list(_SKY_COLOUR),
                    'metallicFactor': 0.0,
                    'roughnessFactor': 1.0
                }
            })
            self._sky_material = len(self.materials) - 1
        return self._sky_material

    def _lightmap(self, index: int) -> int | None:
        """
        Embed one baked lighting atlas, reusing it across every material that names it.

        Parameters
        ----------
        index : int
            Index into the level's atlases.

        Returns
        -------
        int | None
            The texture index, or :py:obj:`None` when the level has no such atlas or it will not
            decode.
        """
        if not 0 <= index < len(self._level.lightmaps):
            return None
        if index in self._by_lightmap:
            return self._by_lightmap[index]
        payload = _image_payload(self._level.lightmaps[index])
        found = None if payload is None else self._add_texture(payload, f'lightmap_{index}')
        self._by_lightmap[index] = found
        return found

    def finish(self, name: str) -> bytes:
        """
        Serialise the document.

        Parameters
        ----------
        name : str
            Name for the scene.

        Returns
        -------
        bytes
            A complete binary glTF.
        """
        binary = _pad(bytes(self._blob), b'\x00')
        document: dict[str, Any] = {
            'accessors': self.accessors,
            'asset': {
                'generator': 'dade maxpayne',
                'version': '2.0'
            },
            'bufferViews': self.views,
            'buffers': [{
                'byteLength': len(binary)
            }],
            'materials': self.materials,
            'meshes': self.meshes,
            'nodes': self.nodes,
            'scene': 0,
            'scenes': [{
                'name': name,
                'nodes': list(range(len(self.nodes)))
            }]
        }
        if self.images:
            document['images'] = self.images
            document['samplers'] = [{'wrapS': _REPEAT, 'wrapT': _REPEAT}]
            document['textures'] = self.textures
        if self.animations:
            document['animations'] = self.animations
        if self._sky_material is not None:
            document['extensionsUsed'] = [_UNLIT]
        chunk = _pad(json.dumps(document, separators=(',', ':')).encode(), b' ')
        length = 12 + 8 + len(chunk) + 8 + len(binary)
        return b''.join((GLB_MAGIC, struct.pack('<II', _VERSION, length),
                         struct.pack('<I',
                                     len(chunk)), _JSON_CHUNK, chunk, struct.pack(
                                         '<I', len(binary)), _BIN_CHUNK, binary))


def _add_mesh(document: _Document,
              positions: Sequence[Vector3],
              normals: Sequence[Vector3],
              coords: Sequence[tuple[float, float]],
              groups: dict[Any, list[tuple[int, int, int]]],
              name: str,
              matrix: Sequence[float] | None,
              material: Callable[[Any], int] | None = None,
              *,
              animate: bool = False,
              lightmap_coords: Sequence[tuple[float, float]] = ()) -> int:
    """
    Add one mesh and the node that places it.

    Parameters
    ----------
    document : _Document
        The document being built.
    positions : collections.abc.Sequence[Vector3]
        Vertex positions.
    normals : collections.abc.Sequence[Vector3]
        One normal per position.
    coords : collections.abc.Sequence[tuple[float, float]]
        One texture coordinate per position, empty when the mesh is untextured.
    groups : dict[Any, list[tuple[int, int, int]]]
        Triangles grouped by whatever decides their material.
    name : str
        Name for the node and mesh.
    matrix : collections.abc.Sequence[float] | None
        The mesh's four-by-three transform, or :py:obj:`None` to leave the node at the origin.
    material : collections.abc.Callable[[Any], int] | None
        Turns a group's key into a document material index. Defaults to the level's own materials.
    lightmap_coords : collections.abc.Sequence[tuple[float, float]]
        One lightmap coordinate per position, empty when the mesh has none.
    animate : bool
        Write the node's placement as translation, rotation and scale rather than as one matrix. A
        node carrying a matrix cannot be animated.

    Returns
    -------
    int
        Index of the node that was added.
    """
    material = material or document.material
    attributes = {
        'NORMAL':
            document.accessor(b''.join(struct.pack('<3f', *v) for v in normals),
                              _ARRAY_BUFFER,
                              componentType=_FLOAT,
                              count=len(normals),
                              type='VEC3'),
        'POSITION':
            document.accessor(b''.join(struct.pack('<3f', *v) for v in positions),
                              _ARRAY_BUFFER,
                              componentType=_FLOAT,
                              count=len(positions),
                              max=[max(v[i] for v in positions) for i in range(3)],
                              min=[min(v[i] for v in positions) for i in range(3)],
                              type='VEC3')
    }
    for slot, values in (('TEXCOORD_0', coords), ('TEXCOORD_1', lightmap_coords)):
        if not values:
            continue
        attributes[slot] = document.accessor(b''.join(struct.pack('<2f', *v) for v in values),
                                             _ARRAY_BUFFER,
                                             componentType=_FLOAT,
                                             count=len(values),
                                             type='VEC2')
    primitives = []
    for material_id, triangles in sorted(groups.items()):
        flat = [index for triangle in triangles for index in triangle]
        primitives.append({
            'attributes':
                attributes,
            'indices':
                document.accessor(struct.pack(f'<{len(flat)}I', *flat),
                                  _ELEMENT_ARRAY_BUFFER,
                                  componentType=_UNSIGNED_INT,
                                  count=len(flat),
                                  max=[max(flat)],
                                  min=[min(flat)],
                                  type='SCALAR'),
            'material':
                material(material_id),
            'mode':
                _TRIANGLES
        })
    document.meshes.append({'name': name, 'primitives': primitives})
    node: dict[str, Any] = {'mesh': len(document.meshes) - 1, 'name': name}
    if matrix is not None:
        if animate:
            translation, rotation, scale = _decompose(matrix)
            node.update(rotation=rotation, scale=scale, translation=translation)
        else:
            node['matrix'] = _node_matrix(matrix)
    document.nodes.append(node)
    return len(document.nodes) - 1


def _add_static_mesh(
    document: _Document,
    level: Level,
    mesh: StaticMesh,
    corners: Sequence[Corner],
    name: str,
    *,
    placed: bool = False,
    clips: Sequence[PropAnimation] = (),
    lifts: Mapping[int, int] = MappingProxyType({})
) -> None:
    """
    Add one mesh, expanding its shared corners into vertices.

    Faces the engine does not draw are left out, so collision volumes and the skybox's placeholder
    image do not paper over the level.

    Vertices arrive in their room's space and :py:attr:`StaticMesh.transform` is the transform the
    reader worked out for that room from the level's exit graph, so it always has to be applied.

    Parameters
    ----------
    document : _Document
        The document being built.
    level : Level
        The level the mesh belongs to, consulted for which materials draw.
    mesh : StaticMesh
        The mesh to add.
    corners : collections.abc.Sequence[Corner]
        The container's shared corner array.
    name : str
        Name for the node and mesh.
    placed : bool
        Apply :py:attr:`StaticMesh.transform`.
    clips : collections.abc.Sequence[PropAnimation]
        Animations the mesh can play. A mesh with any is written so it can be animated.
    lifts : collections.abc.Mapping[int, int]
        How far off its plane each face has to sit, in steps of
        :py:data:`dade.maxpayne.decals.DECAL_STEP`, keyed by the face's index. Faces that stay put
        may be left out.
    """
    positions: list[Vector3] = []
    normals: list[Vector3] = []
    coords: list[tuple[float, float]] = []
    baked: list[tuple[float, float]] = []
    groups: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for at, face in enumerate(mesh.faces):
        if not _draws(level, face.material):
            continue
        base = len(positions)
        end = face.first_corner + face.corner_count
        if end > len(corners):
            return
        # Anything laid over another surface rides a little way up its own normal, so that a
        # viewer drawing both at once does not have to guess which is in front.
        step = lifts.get(at, 0) * DECAL_STEP
        lift = _mirror(face.normal)
        for corner in corners[face.first_corner:end]:
            if corner.position >= len(mesh.positions):
                return
            x, y, z = _mirror(mesh.positions[corner.position])
            positions.append((x + lift[0] * step, y + lift[1] * step, z + lift[2] * step))
            normals.append(_mirror(mesh.normals[corner.position]))
            coords.append(corner.uv)
            baked.append(corner.lightmap_uv)
        fan = [(base, base + i, base + i + 1) for i in range(1, face.corner_count - 1)]
        # A face names both its material and the atlas that lights it, and a primitive can carry
        # only one of each, so the two together group the triangles.
        groups.setdefault((face.material, face.lightmap), []).extend(
            _wind(fan, positions, _mirror(face.normal)))
    if not groups:
        return
    moving = [clip for clip in clips if clip.start != clip.end]
    node = _add_mesh(document,
                     positions,
                     normals,
                     coords,
                     groups,
                     name,
                     mesh.transform if placed else None,
                     animate=bool(moving),
                     lightmap_coords=baked)
    written = sum(document.add_animation(node, name, clip) for clip in moving)
    if moving and not written and placed:
        # Nothing drove the node after all, so it may as well carry a matrix like the rest.
        document.settle(node, mesh.transform)


def _add_bsp(document: _Document, polygons: Sequence[Polygon], vertices: Sequence[Vector3],
             name: str) -> None:
    """
    Add the BSP faces as one untextured node.

    Parameters
    ----------
    document : _Document
        The document being built.
    polygons : collections.abc.Sequence[Polygon]
        The level's faces.
    vertices : collections.abc.Sequence[Vector3]
        The level's vertex pool.
    name : str
        Name for the node and mesh.
    """
    mirrored = [_mirror(vertex) for vertex in vertices]
    normals: list[Vector3] = [(0.0, 1.0, 0.0)] * len(mirrored)
    triangles: list[tuple[int, int, int]] = []
    for polygon in polygons:
        first = polygon.first_vertex
        normal = _mirror(polygon.normal)
        for index in range(first, first + polygon.vertex_count):
            normals[index] = normal
        fan = [(first, first + i, first + i + 1) for i in range(1, polygon.vertex_count - 1)]
        triangles.extend(_wind(fan, mirrored, normal))
    _add_mesh(document, mirrored, normals, (), {(-1, -1): triangles}, name, None)


def _add_model(document: _Document, model: Model, placement: Placement, label: str) -> None:
    """
    Add one NPC or pickup as real geometry.

    The model arrives in its own space with its own material library, so its images are embedded
    beside the level's and the placement's transform puts it where the level asked for it.

    Parameters
    ----------
    document : _Document
        The document being built.
    model : Model
        The model to add, with its images already read in.
    placement : Placement
        Where the object stands.
    label : str
        Prefix naming what the node holds, such as ``character:transit_cop``.
    """
    images = {texture.path.lower(): texture for texture in model.textures}
    for index, mesh in enumerate(model.meshes):
        positions: list[Vector3] = []
        normals: list[Vector3] = []
        coords: list[tuple[float, float]] = []
        groups: dict[int, list[tuple[int, int, int]]] = {}
        for face in mesh.faces:
            base = len(positions)
            for corner in range(3):
                point = mesh.positions[face.positions[corner]]
                positions.append(_mirror(point))
                normals.append(
                    _mirror(mesh.normals[face.positions[corner]]) if mesh.normals else (0.0, 1.0,
                                                                                        0.0))
                coords.append(mesh.coords[face.coords[corner]] if mesh.coords else (0.0, 0.0))
            groups.setdefault(face.material, []).append((base, base + 2, base + 1))
        if not groups:
            continue
        name = f'{label} {placement.name}'.strip()
        _add_mesh(
            document,
            positions,
            normals,
            coords,
            groups,
            name if len(model.meshes) == 1 else f'{name} #{index}',
            placement.transform,
            material=lambda key, mesh=mesh: document.model_material(  # type: ignore[misc]
                mesh.materials[key] if key < len(mesh.materials) else '', model, images))


def _add_placement(document: _Document, placement: Placement, label: str) -> None:
    """
    Add one NPC or pickup as an empty node.

    The models live outside the level, under ``data/database/skins`` and
    ``data/database/level_items``, so what the level itself supplies is where each one stands and
    which model belongs there. Carrying that as a named, positioned node keeps the placement usable
    without the model.

    Parameters
    ----------
    document : _Document
        The document being built.
    placement : Placement
        Where the object stands.
    label : str
        Prefix naming what the node holds, such as ``character:transit_cop``.
    """
    document.nodes.append({
        'matrix': _node_matrix(placement.transform),
        'name': f'{label} {placement.name}'.strip()
    })


def _lift_decals(level: Level, containers: Sequence[RenderMesh]) -> list[list[dict[int, int]]]:
    """
    Work out which faces have to come off their plane, across the whole level at once.

    Whether two surfaces fight depends on where they end up in the scene, not on which mesh they
    were stored in, so every drawn face is gathered in scene space first and layered together. See
    :py:func:`dade.maxpayne.decals.layer_faces` for what the layering means.

    Parameters
    ----------
    level : Level
        The level being written, consulted for which materials draw.
    containers : collections.abc.Sequence[RenderMesh]
        The containers whose meshes will be written, in the order they will be written in.

    Returns
    -------
    list[list[dict[int, int]]]
        One entry per container, one per mesh within it, mapping a face's index to how many steps
        of :py:data:`dade.maxpayne.decals.DECAL_STEP` it has to rise. Faces that stay put are left
        out.
    """
    surfaces: list[tuple[Vector3, list[Vector3], tuple[int, int, int]]] = []
    origins: list[tuple[int, int, int]] = []
    for group, container in enumerate(containers):
        for index, mesh in enumerate(container.meshes):
            matrix = _node_matrix(mesh.transform)
            for at, face in enumerate(mesh.faces):
                if not _draws(level, face.material):
                    continue
                end = face.first_corner + face.corner_count
                if end > len(container.corners) or any(
                        corner.position >= len(mesh.positions)
                        for corner in container.corners[face.first_corner:end]):
                    continue
                surfaces.append((_turn(matrix, _mirror(face.normal)), [
                    _place(matrix, _mirror(mesh.positions[corner.position]))
                    for corner in container.corners[face.first_corner:end]
                ], (group, index, face.material)))
                origins.append((group, index, at))
    out: list[list[dict[int, int]]] = [[{} for _ in c.meshes] for c in containers]
    for layer, (group, index, at) in zip(layer_faces(surfaces), origins, strict=True):
        if layer:
            out[group][index][at] = layer
    return out


def build_glb(level: Level,
              *,
              name: str = 'level',
              models: Mapping[str, Model] | None = None) -> bytes:
    """
    Build a ``.glb`` from a level.

    Parameters
    ----------
    level : Level
        A level from :py:func:`dade.maxpayne.ldb.read_level`.
    name : str
        Name given to the scene and its nodes.
    models : collections.abc.Mapping[str, Model] | None
        Models to draw the NPCs and pickups with, keyed by the node label the placement gets, such
        as ``character:transit_cop``. A placement with no model is written as an empty node.

    Returns
    -------
    bytes
        A complete binary glTF.

    Raises
    ------
    ValueError
        If the level has nothing to draw.
    """
    document = _Document(level)
    containers = [(c, p) for c, p in ((level.mesh, name), (level.props, f'{name}_prop')) if c]
    lifts = _lift_decals(level, [container for container, _prefix in containers])
    for group, (container, prefix) in enumerate(containers):
        for index, mesh in enumerate(container.meshes):
            label = container.names[index] if index < len(container.names) else f'{prefix}_{index}'
            clips = container.animations[index] if index < len(container.animations) else ()
            _add_static_mesh(document,
                             level,
                             mesh,
                             container.corners,
                             label,
                             clips=clips,
                             lifts=lifts[group][index],
                             placed=True)
    found = models or {}
    for placement, label in ([(c.placement, f'character:{c.skin}')
                              for c in level.characters] + [(i.placement, f'item:{i.item}')
                                                            for i in level.items]):
        model = found.get(label)
        if model is not None and any(m.faces for m in model.meshes):
            _add_model(document, model, placement, label)
        else:
            _add_placement(document, placement, label)
    if not any('mesh' in node for node in document.nodes):
        if not level.geometry.polygons:
            msg = 'The level has no faces.'
            raise ValueError(msg)
        _add_bsp(document, level.geometry.polygons, level.geometry.vertices, name)
    return document.finish(name)
