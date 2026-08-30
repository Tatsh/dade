"""
Export ``.EGP2`` geometry to a single binary glTF (``.glb``) file.

Everything the viewer needs lands in one file: positions, texture coordinates, vertex colours,
triangle indices, the material list, and the PNG for each material's texture, all packed into the
GLB binary chunk.

The game stores geometry Z-up while glTF is Y-up, so positions are rewritten as ``(x, z, -y)``.
"""
from __future__ import annotations

from math import cos, isfinite, sin
from typing import TYPE_CHECKING, Any
import io
import json
import logging
import struct

from PIL.Image import new as new_image

from .model import read_materials, read_meshes, triangles
from .prop import (
    is_alternate,
    read_items,
    read_materials as read_prop_materials,
    read_sections,
    wardrobe_key,
)
from .texture import decode, iter_geometry_textures

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from PIL.Image import Image

    from .model import Mesh
    from .olv import Placement
    from .prop import PropSection

__all__ = ('GLB_MAGIC', 'build_glb', 'build_prop_glb', 'write_glb', 'write_prop_glb')

log = logging.getLogger(__name__)

GLB_MAGIC = 0x46546C67
"""Magic word starting every binary glTF file.

:meta hide-value:
"""

_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_FLOAT = 5126
_UNSIGNED_BYTE = 5121
_UNSIGNED_SHORT = 5123
_UNSIGNED_INT = 5125
_TRIANGLES = 4
_IMAGE_RECORD_BIAS = 0x80
_GLOW_STRENGTH = 0.14
_SHADOW_ALPHA = 115
_SKIN_HINTS = ('body', 'suit', 'torso', 'head', 'face')
_ALPHA_CLEAR = 0.02
_ALPHA_PARTIAL = 0.20
_TRIANGLE_CORNERS = 3
_SHORT_INDEX_LIMIT = 0xFFFF


class _Buffer:
    """Accumulates the GLB binary chunk and records a buffer view for each block added."""
    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict[str, Any]] = []

    def add(self, payload: bytes, target: int | None = None) -> int:
        """
        Append a block and return its buffer view index.

        Parameters
        ----------
        payload : bytes
            The bytes to append.
        target : int | None
            Optional glTF buffer target hint.

        Returns
        -------
        int
            Index of the new buffer view.
        """
        while len(self.data) % 4:
            self.data.append(0)
        view: dict[str, Any] = {
            'buffer': 0,
            'byteOffset': len(self.data),
            'byteLength': len(payload)
        }
        if target is not None:
            view['target'] = target
        self.data += payload
        self.views.append(view)
        return len(self.views) - 1


def _finite(value: float) -> float:
    """
    Replace a non-finite coordinate with zero.

    A few of the game's vertices carry NaN or infinite texture coordinates. glTF accessors may not
    hold those, and a validator rejects the whole file over them.

    Parameters
    ----------
    value : float
        The stored coordinate.

    Returns
    -------
    float
        The value, or ``0.0`` when it is not finite.
    """
    return value if isfinite(value) else 0.0


def _is_shadow(mesh: Mesh) -> bool:
    """
    Report whether a mesh is one of the baked shadow decals.

    A handful of meshes -- a twentieth of one percent of a level's vertices -- carry a vertex colour
    of pure black throughout. Vertex colour multiplies the texture, so whatever map they name
    contributes nothing and the game must be blending them to darken what is behind. Drawn as
    ordinary opaque geometry they become black holes in the floor, which is what the shadows under
    Vesuvio's bathroom fixtures were.

    Parameters
    ----------
    mesh : Mesh
        The mesh to test.

    Returns
    -------
    bool
        ``True`` when every vertex is black.
    """
    return all(not v.red and not v.green and not v.blue for packet in mesh.packets
               for v in packet.vertices)


def _mesh_arrays(mesh: Mesh,
                 *,
                 glow: bool = False,
                 shadow: bool = False) -> tuple[bytes, bytes, bytes, list[int], int]:
    """
    Flatten one mesh's packets into glTF attribute buffers.

    Degenerate strip triangles, used by the cooker to stitch strips together, are dropped.

    Parameters
    ----------
    mesh : Mesh
        The mesh to flatten.
    glow : bool
        Whether the mesh uses a plain white glow sprite, in which case vertex alpha is taken from
        vertex brightness so the sprite fades out where the hardware's additive blend would have
        contributed nothing.
    shadow : bool
        Whether the mesh is a baked shadow decal, in which case it is given a fixed partial alpha so
        it darkens the floor instead of punching a black hole in it.

    Returns
    -------
    tuple[bytes, bytes, bytes, list[int], int]
        Positions, texture coordinates, colours, triangle indices, and the vertex count.
    """
    positions = bytearray()
    texcoords = bytearray()
    colors = bytearray()
    indices: list[int] = []
    base = 0
    for packet in mesh.packets:
        for v in packet.vertices:
            positions += struct.pack('<3f', _finite(v.x), _finite(v.z), -_finite(v.y))
            texcoords += struct.pack('<2f', _finite(v.u), 1.0 - _finite(v.v))
            red, green, blue = (min(255, v.red * 2), min(255, v.green * 2), min(255, v.blue * 2))
            # A glow sprite is additive on hardware, so its brightness is how much it shows through.
            # Ordinary blending cannot brighten, only cover, so the strength is held well down to
            # keep it a haze over whatever it lights rather than a wash that hides it.
            luminance = (red * 2 + green * 5 + blue) // 8
            if glow:
                alpha = int(luminance * _GLOW_STRENGTH)
            elif shadow:
                alpha = _SHADOW_ALPHA
            else:
                alpha = 255
            colors += bytes((red, green, blue, alpha))
        for a, b, c in triangles(len(packet.vertices), packet.primitive):
            pa, pb, pc = (packet.vertices[a][:3], packet.vertices[b][:3], packet.vertices[c][:3])
            if len({pa, pb, pc}) == _TRIANGLE_CORNERS:
                indices += [base + a, base + b, base + c]
        base += len(packet.vertices)
    return bytes(positions), bytes(texcoords), bytes(colors), indices, base


def _material_images(data: bytes) -> dict[int, tuple[bytes, str]]:
    """
    Render every embedded texture that a material references to PNG bytes.

    Parameters
    ----------
    data : bytes
        The whole geometry blob.

    Returns
    -------
    dict[int, tuple[bytes, str]]
        Image record offset to the encoded PNG and the alpha mode that suits it.
    """
    out: dict[int, tuple[bytes, str]] = {}
    for texture in iter_geometry_textures(data):
        image = decode(data, texture)
        stem = texture.name.rsplit('/', 1)[-1].lower()
        mode = _alpha_mode(image)
        if _is_glow(image):
            mode = 'GLOW'
        elif stem.startswith(('add_', 'sub_')):
            image = _as_overlay(image, darkening=stem.startswith('sub_'))
            mode = 'BLEND'
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        out[texture.data_offset - _IMAGE_RECORD_BIAS] = (buffer.getvalue(), mode)
    return out


def _prop_images(data: bytes) -> dict[str, tuple[bytes, str]]:
    """
    Render a ``.SGP2`` library's embedded textures and key them by base name.

    Sections name their texture rather than pointing at it, so the images have to be reachable by
    name.

    Parameters
    ----------
    data : bytes
        The whole ``.SGP2`` file.

    Returns
    -------
    dict[str, tuple[bytes, str]]
        Lowercased base name to the encoded PNG and the alpha mode that suits it.
    """
    images = _material_images(data)
    by_name: dict[str, tuple[bytes, str]] = {}
    for texture in iter_geometry_textures(data):
        # Every texture this walk yields was rendered by the walk above, so the key is always there.
        found = images[texture.data_offset - _IMAGE_RECORD_BIAS]
        name = texture.name.rsplit('/', 1)[-1].lower()
        png, mode = found
        # Skin and clothing are never cut out. A few of these maps keep a small margin of clear
        # texels, enough to be taken for a stencil, which punches holes in a face.
        if mode == 'MASK' and any(hint in name for hint in _SKIN_HINTS):
            found = (png, 'OPAQUE')
        by_name.setdefault(name, found)
    return by_name


def _prop_meshes(section: bytes) -> list[tuple[str, tuple[str, ...], bytes, bytes, list[int], int]]:
    """
    Flatten a ``.SGP2`` section into one entry per draw group.

    Each item's command list says which material draws which stretch of its geometry, so no guessing
    is needed: the group's material gives the texture outright. Where an item is one of a set of
    interchangeable pieces -- a crowd character carries a wardrobe of jackets and shoes in the one
    model, and the game dresses each passer-by by handing the renderer a bitmask -- only the first
    of each set is kept, since drawing them all leaves the alternatives fighting in the same space.

    Parameters
    ----------
    section : bytes
        The section's bytes.

    Returns
    -------
    list[tuple[str, tuple[str, ...], bytes, bytes, list[int], int]]
        Per group: the item's name, its material's texture names, positions, texture coordinates,
        triangle indices, and the vertex count.
    """
    materials = read_prop_materials(section)
    worn: set[str] = set()
    out: list[tuple[str, tuple[str, ...], bytes, bytes, list[int], int]] = []
    for item in read_items(section):
        if is_alternate(item.name):
            key = wardrobe_key(item.name)
            if key in worn:
                continue
            worn.add(key)
        for group in item.groups:
            positions = bytearray()
            texcoords = bytearray()
            indices: list[int] = []
            base = 0
            for primitive, vertices in group.packets:
                for v in vertices:
                    positions += struct.pack('<3f', v.x, v.z, -v.y)
                    texcoords += struct.pack('<2f', v.u, 1.0 - v.v)
                for a, b, c in triangles(len(vertices), primitive):
                    if len({vertices[a][:3], vertices[b][:3],
                            vertices[c][:3]}) == _TRIANGLE_CORNERS:
                        indices += [base + a, base + b, base + c]
                base += len(vertices)
            if not indices:
                continue
            names = materials[group.material] if group.material < len(materials) else ()
            out.append((item.name, names, bytes(positions), bytes(texcoords), indices, base))
    return out


def _is_glow(image: Image) -> bool:
    """
    Report whether a texture is a plain white glow sprite.

    Several levels light windows and signs with a small texture that is a single pure white colour.
    White contributes nothing to a multiply, so on hardware the sprite's appearance comes entirely
    from its vertex colours under an additive blend. Drawn normally it is an opaque white slab that
    hides whatever it was meant to light, such as the Bada Bing sign.

    Parameters
    ----------
    image : Image
        The decoded texture.

    Returns
    -------
    bool
        ``True`` when every pixel is opaque white.
    """
    return image.convert('RGBA').getextrema() == ((255, 255), (255, 255), (255, 255), (255, 255))


def _as_overlay(image: Image, *, darkening: bool) -> Image:
    """
    Approximate a subtractive or additive decal as a blended texture.

    Neither blend is expressible in core glTF, so both are recast as ordinary alpha blending with
    alpha taken from luminance. That works because both operations scale with how bright the source
    is: a nearly black texel adds nothing and subtracts nothing, so it should be nearly invisible
    either way.

    A subtractive decal computes ``dest - src``, so its colour is replaced with black and blending
    toward black by ``luminance`` reproduces the darkening. These textures are very dark to begin
    with -- the shadow, scum, and crack decals average 19 to 32 out of 255 -- so treating a dark
    texel as *more* opaque instead of less turns a faint smudge into a solid black patch.

    Parameters
    ----------
    image : Image
        The decoded texture.
    darkening : bool
        ``True`` for a subtractive decal, ``False`` for an additive one.

    Returns
    -------
    Image
        The texture recast for alpha blending.
    """
    luminance = image.convert('L')
    image = new_image('RGBA', image.size, (0, 0, 0, 255)) if darkening else image.copy()
    image.putalpha(luminance)
    return image


def _alpha_mode(image: Image) -> str:
    """
    Choose the glTF alpha mode that suits an image's alpha channel.

    Anything fully opaque is ``OPAQUE``. Cut-out art such as foliage keeps crisp edges with
    ``MASK``. The game's ``add_`` and ``sub_`` overlays are soft gradients and only look right with
    ``BLEND``; drawn opaque they appear as solid black patches.

    A texture is only treated as see-through when a meaningful share of it actually is. Some maps
    carry an alpha channel that is not transparency at all: Tony's face has 0.4% of its texels near
    zero and 4% partly on, against 40% and 60% for a hair texture that really does need to be
    drawn with holes. Taking that face for translucent made him semi-transparent, so his own
    skull showed through from the front and his face showed through from behind.

    Parameters
    ----------
    image : Image
        The decoded texture.

    Returns
    -------
    str
        One of ``OPAQUE``, ``MASK``, or ``BLEND``.
    """
    counts = image.getchannel('A').histogram()
    total = sum(counts) or 1
    clear = sum(counts[:8]) / total
    partial = sum(counts[8:248]) / total
    if clear < _ALPHA_CLEAR and partial < _ALPHA_PARTIAL:
        return 'OPAQUE'
    return 'BLEND' if partial >= _ALPHA_PARTIAL else 'MASK'


def build_glb(  # noqa: C901, PLR0914
    data: bytes,
    *,
    generator: str = 'dade',
    double_sided: bool = False,
    libraries: Sequence[bytes] = (),
    placements: Sequence[Placement] = ()) -> bytes | None:
    """
    Build a binary glTF for one ``.EGP2`` geometry blob.

    A level's props and cast are not part of its geometry: they are held once each in a ``.SGP2``
    library and placed by the level's ``.OLV``. Given both, every placement becomes a node carrying
    the object's position and turn, so the doors, chairs, and vehicles appear where the game puts
    them rather than in a file of their own. Objects placed more than once share a single mesh.

    A level's cast is spread over several libraries, so more than one may be given; the first to
    name an object supplies it. A placement whose object no library holds is skipped.

    Parameters
    ----------
    data : bytes
        The whole geometry blob.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.
    double_sided : bool
        Draw both faces of every triangle. Off by default so viewers cull back faces, which is what
        the game does: interiors are built without the faces the player never sees, and drawing them
        makes ceilings and outer walls block the view from outside.
    libraries : Sequence[bytes]
        The level's ``.SGP2`` prop and character libraries, when their objects are to be placed.
    placements : Sequence[Placement]
        Where to put each of those libraries' objects, read from the level's ``.OLV``.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or ``None`` when the blob holds no decodable geometry.
    """
    meshes = read_meshes(data)
    if not meshes:
        return None
    materials = read_materials(data)
    images = _material_images(data)
    buffer = _Buffer()
    accessors: list[dict[str, Any]] = []
    gltf_meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    def accessor(view: int, component: int, count: int, kind: str, **extra: Any) -> int:
        accessors.append({
            'bufferView': view,
            'componentType': component,
            'count': count,
            'type': kind,
            **extra
        })
        return len(accessors) - 1

    used: dict[int, int] = {}
    glowing: set[int] = set()
    gltf_materials: list[dict[str, Any]] = []
    gltf_textures: list[dict[str, Any]] = []
    gltf_images: list[dict[str, Any]] = []
    for index, material in enumerate(materials):
        found = images.get(material.texture_offset) if material.texture_offset else None
        png, mode = found if found is not None else (None, 'OPAQUE')
        pbr: dict[str, Any] = {'baseColorFactor': [1.0, 1.0, 1.0, 1.0], 'metallicFactor': 0.0}
        if png is not None:
            gltf_images.append({
                'bufferView': buffer.add(png),
                'mimeType': 'image/png',
                'name': material.name.rsplit('/', 1)[-1]
            })
            gltf_textures.append({'source': len(gltf_images) - 1, 'sampler': 0})
            pbr['baseColorTexture'] = {'index': len(gltf_textures) - 1}
        if mode == 'GLOW':
            glowing.add(index)
            mode = 'BLEND'
        used[index] = len(gltf_materials)
        gltf_materials.append({
            'name': material.name.rsplit('/', 1)[-1] or f'material_{index}',
            'pbrMetallicRoughness': pbr,
            'alphaMode': mode,
            'doubleSided': double_sided
        })

    shadow_material: int | None = None
    for mesh in meshes:
        shadow = _is_shadow(mesh)
        positions, texcoords, colors, indices, count = _mesh_arrays(mesh,
                                                                    glow=mesh.material in glowing,
                                                                    shadow=shadow)
        if not indices:
            continue
        if shadow and shadow_material is None:
            gltf_materials.append({
                'name': 'shadow',
                'pbrMetallicRoughness': {
                    'baseColorFactor': [0.0, 0.0, 0.0, 1.0],
                    'metallicFactor': 0.0
                },
                'alphaMode': 'BLEND',
                'doubleSided': double_sided
            })
            shadow_material = len(gltf_materials) - 1
        floats = struct.unpack(f'<{count * 3}f', positions)
        axes = [floats[i::3] for i in range(3)]
        wide = count > _SHORT_INDEX_LIMIT
        packed = struct.pack(f'<{len(indices)}{"I" if wide else "H"}', *indices)
        primitive = {
            'attributes': {
                'POSITION':
                    accessor(buffer.add(positions, 34962),
                             _FLOAT,
                             count,
                             'VEC3',
                             min=[min(a) for a in axes],
                             max=[max(a) for a in axes]),
                'TEXCOORD_0':
                    accessor(buffer.add(texcoords, 34962), _FLOAT, count, 'VEC2'),
                'COLOR_0':
                    accessor(buffer.add(colors, 34962),
                             _UNSIGNED_BYTE,
                             count,
                             'VEC4',
                             normalized=True)
            },
            'indices':
                accessor(buffer.add(packed, 34963), _UNSIGNED_INT if wide else _UNSIGNED_SHORT,
                         len(indices), 'SCALAR'),
            'mode':
                _TRIANGLES
        }
        if shadow and shadow_material is not None:
            primitive['material'] = shadow_material
        elif mesh.material in used:
            primitive['material'] = used[mesh.material]
        gltf_meshes.append({'name': f'mesh_{len(gltf_meshes)}', 'primitives': [primitive]})
        nodes.append({'mesh': len(gltf_meshes) - 1})

    if libraries and placements:
        sections: dict[str, tuple[int, PropSection]] = {}
        for number, blob in enumerate(libraries):
            for section in read_sections(blob):
                sections.setdefault(section.name.rsplit('/', 1)[-1].lower(), (number, section))
        cached_images: dict[int, dict[str, tuple[bytes, str]]] = {}
        prop_materials: dict[tuple[int, str], int] = {}
        prop_meshes: dict[str, int | None] = {}

        def prop_material(number: int, name: str) -> int | None:
            if (number, name) not in prop_materials:
                if number not in cached_images:
                    cached_images[number] = _prop_images(libraries[number])
                found = cached_images[number].get(name)
                if found is None:
                    return None
                png, mode = found
                gltf_images.append({
                    'bufferView': buffer.add(png),
                    'mimeType': 'image/png',
                    'name': name
                })
                gltf_textures.append({'source': len(gltf_images) - 1, 'sampler': 0})
                gltf_materials.append({
                    'name': name,
                    'pbrMetallicRoughness': {
                        'baseColorFactor': [1.0, 1.0, 1.0, 1.0],
                        'metallicFactor': 0.0,
                        'baseColorTexture': {
                            'index': len(gltf_textures) - 1
                        }
                    },
                    'alphaMode': 'BLEND' if mode == 'GLOW' else mode,
                    # Props are drawn from both sides. A level is a shell built without the faces
                    # the player never reaches, so culling it is right, but a prop is a thin thing
                    # seen from anywhere: a tablecloth, a door, a chair back. Culling those leaves
                    # angular holes wherever a surface happens to face away.
                    'doubleSided': True
                })
                prop_materials[number, name] = len(gltf_materials) - 1
            return prop_materials[number, name]

        def prop_mesh(key: str) -> int | None:
            if (found := sections.get(key)) is None:
                return None
            number, section = found
            body = libraries[number][section.offset:section.offset + section.size]
            entries = []
            for _label, names, positions, texcoords, indices, count in _prop_meshes(body):
                floats = struct.unpack(f'<{count * 3}f', positions)
                axes = [floats[i::3] for i in range(3)]
                wide = count > _SHORT_INDEX_LIMIT
                packed = struct.pack(f'<{len(indices)}{"I" if wide else "H"}', *indices)
                entry: dict[str, Any] = {
                    'attributes': {
                        'POSITION':
                            accessor(buffer.add(positions, 34962),
                                     _FLOAT,
                                     count,
                                     'VEC3',
                                     min=[min(a) for a in axes],
                                     max=[max(a) for a in axes]),
                        'TEXCOORD_0':
                            accessor(buffer.add(texcoords, 34962), _FLOAT, count, 'VEC2')
                    },
                    'indices':
                        accessor(buffer.add(packed,
                                            34963), _UNSIGNED_INT if wide else _UNSIGNED_SHORT,
                                 len(indices), 'SCALAR'),
                    'mode':
                        _TRIANGLES
                }
                chosen = next((m for m in (prop_material(number, n.lower())
                                           for n in names) if m is not None), None)
                if chosen is not None:
                    entry['material'] = chosen
                entries.append(entry)
            if not entries:
                return None
            gltf_meshes.append({'name': key, 'primitives': entries})
            return len(gltf_meshes) - 1

        for placement in placements:
            # An instance recording no position at all is a spawn stub the game fills in when it
            # needs the character. Drawing them all at the origin piles a dozen models into the same
            # space, where they interpenetrate and z-fight into a mess.
            if not placement.x and not placement.y:
                continue
            key = placement.prototype.lower()
            if key not in prop_meshes:
                prop_meshes[key] = prop_mesh(key)
            if (drawn := prop_meshes[key]) is None:
                continue
            # The game turns an object about its vertical axis, which is Z there and Y here.
            half = placement.rotation / 2
            nodes.append({
                'name': placement.name,
                'mesh': drawn,
                'translation': [placement.x, placement.z, -placement.y],
                'rotation': [0.0, sin(half), 0.0, cos(half)]
            })

    if not gltf_meshes:
        return None
    document: dict[str, Any] = {
        'asset': {
            'version': '2.0',
            'generator': generator
        },
        'scene': 0,
        'scenes': [{
            'nodes': list(range(len(nodes)))
        }],
        'nodes': nodes,
        'meshes': gltf_meshes,
        'accessors': accessors,
        'bufferViews': buffer.views,
        'buffers': [{
            'byteLength': len(buffer.data)
        }],
        'materials': gltf_materials,
        'samplers': [{
            'wrapS': 10497,
            'wrapT': 10497
        }]
    }
    if gltf_textures:
        document['textures'] = gltf_textures
        document['images'] = gltf_images
    return _pack_glb(document, bytes(buffer.data))


def _pack_glb(document: dict[str, Any], binary: bytes) -> bytes:
    """
    Wrap a glTF document and its binary payload in the GLB container.

    Parameters
    ----------
    document : dict[str, Any]
        The glTF JSON.
    binary : bytes
        The binary chunk the document's buffer views index into.

    Returns
    -------
    bytes
        The complete ``.glb`` file.
    """
    payload = json.dumps(document, separators=(',', ':')).encode()
    payload += b' ' * (-len(payload) % 4)
    binary += b'\0' * (-len(binary) % 4)
    total = 12 + 8 + len(payload) + 8 + len(binary)
    return b''.join((struct.pack('<III', GLB_MAGIC, 2,
                                 total), struct.pack('<II', len(payload), _JSON_CHUNK), payload,
                     struct.pack('<II', len(binary), _BIN_CHUNK), binary))


def build_prop_glb(data: bytes,
                   *,
                   generator: str = 'dade',
                   double_sided: bool = False) -> bytes | None:
    """
    Build a binary glTF for a ``.SGP2`` prop and character library.

    Each object section becomes its own node, keeping the object-local coordinates the file stores.
    A section names its textures rather than pointing at them, so each is matched to the file's
    embedded image records by base name. Where a section names as many textures as it has runs of
    packets, each run takes its own; otherwise every run falls back to the first texture that
    resolves, so a character whose maps outnumber its runs still gets one of them throughout.

    Parameters
    ----------
    data : bytes
        The whole ``.SGP2`` file.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.
    double_sided : bool
        Draw both faces of every triangle.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or ``None`` when the library holds no decodable geometry.
    """
    by_name = _prop_images(data)
    buffer = _Buffer()
    accessors: list[dict[str, Any]] = []
    gltf_meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    gltf_materials: list[dict[str, Any]] = []
    gltf_textures: list[dict[str, Any]] = []
    gltf_images: list[dict[str, Any]] = []
    material_for: dict[str, int] = {}

    def accessor(view: int, component: int, count: int, kind: str, **extra: Any) -> int:
        accessors.append({
            'bufferView': view,
            'componentType': component,
            'count': count,
            'type': kind,
            **extra
        })
        return len(accessors) - 1

    def material(name: str) -> int | None:
        if name in material_for:
            return material_for[name]
        found = by_name.get(name)
        if found is None:
            return None
        png, mode = found
        gltf_images.append({'bufferView': buffer.add(png), 'mimeType': 'image/png', 'name': name})
        gltf_textures.append({'source': len(gltf_images) - 1, 'sampler': 0})
        gltf_materials.append({
            'name': name,
            'pbrMetallicRoughness': {
                'baseColorFactor': [1.0, 1.0, 1.0, 1.0],
                'metallicFactor': 0.0,
                'baseColorTexture': {
                    'index': len(gltf_textures) - 1
                }
            },
            'alphaMode': 'BLEND' if mode == 'GLOW' else mode,
            'doubleSided': double_sided
        })
        material_for[name] = len(gltf_materials) - 1
        return material_for[name]

    for section in read_sections(data):
        body = data[section.offset:section.offset + section.size]
        label = section.name.rsplit('/', 1)[-1]
        entries = []
        for _item, names, positions, texcoords, indices, base in _prop_meshes(body):
            floats = struct.unpack(f'<{base * 3}f', positions)
            axes = [floats[i::3] for i in range(3)]
            wide = base > _SHORT_INDEX_LIMIT
            packed = struct.pack(f'<{len(indices)}{"I" if wide else "H"}', *indices)
            attributes = {
                'POSITION':
                    accessor(buffer.add(positions, 34962),
                             _FLOAT,
                             base,
                             'VEC3',
                             min=[min(a) for a in axes],
                             max=[max(a) for a in axes]),
                'TEXCOORD_0':
                    accessor(buffer.add(texcoords, 34962), _FLOAT, base, 'VEC2')
            }
            primitive_entry: dict[str, Any] = {
                'attributes':
                    attributes,
                'indices':
                    accessor(buffer.add(packed, 34963), _UNSIGNED_INT if wide else _UNSIGNED_SHORT,
                             len(indices), 'SCALAR'),
                'mode':
                    _TRIANGLES
            }
            chosen = next((m for m in (material(n.lower()) for n in names) if m is not None), None)
            if chosen is not None:
                primitive_entry['material'] = chosen
            entries.append(primitive_entry)
        if not entries:
            continue
        gltf_meshes.append({'name': label, 'primitives': entries})
        nodes.append({'name': label, 'mesh': len(gltf_meshes) - 1})

    if not gltf_meshes:
        return None
    document: dict[str, Any] = {
        'asset': {
            'version': '2.0',
            'generator': generator
        },
        'scene': 0,
        'scenes': [{
            'nodes': list(range(len(nodes)))
        }],
        'nodes': nodes,
        'meshes': gltf_meshes,
        'accessors': accessors,
        'bufferViews': buffer.views,
        'buffers': [{
            'byteLength': len(buffer.data)
        }],
        'materials': gltf_materials,
        'samplers': [{
            'wrapS': 10497,
            'wrapT': 10497
        }]
    }
    if gltf_textures:
        document['textures'] = gltf_textures
        document['images'] = gltf_images
    return _pack_glb(document, bytes(buffer.data))


def write_prop_glb(path: Path, output_dir: Path) -> tuple[Path, ...]:
    """
    Write a ``.glb`` for one ``.SGP2`` prop library.

    Parameters
    ----------
    path : Path
        The ``.SGP2`` file to read.
    output_dir : Path
        Directory to write into. It is created if missing.

    Returns
    -------
    tuple[Path, ...]
        The file written, empty when the library has no decodable geometry.
    """
    if (glb := build_prop_glb(path.read_bytes())) is None:
        return ()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f'{path.stem}_props.glb'
    destination.write_bytes(glb)
    return (destination,)


def write_glb(
    path: Path,
    output_dir: Path,
    *,
    libraries: Sequence[bytes] = (),
    placements: Sequence[Placement] = ()) -> tuple[Path, ...]:
    """
    Write a ``.glb`` for one geometry blob.

    Parameters
    ----------
    path : Path
        The ``.EGP2`` or ``.SGP2`` file to read.
    output_dir : Path
        Directory to write into. It is created if missing.
    libraries : Sequence[bytes]
        The level's ``.SGP2`` prop and character libraries, when their objects are to be placed.
    placements : Sequence[Placement]
        Where to put each of those libraries' objects, read from the level's ``.OLV``.

    Returns
    -------
    tuple[Path, ...]
        The file written, empty when the blob has no decodable geometry.
    """
    if (glb := build_glb(path.read_bytes(), libraries=libraries, placements=placements)) is None:
        return ()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f'{path.stem}.glb'
    destination.write_bytes(glb)
    return (destination,)
