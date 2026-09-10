"""
Export ``.EGP2`` geometry to a single binary glTF (``.glb``) file.

Everything the viewer needs lands in one file: positions, texture coordinates, vertex colours,
triangle indices, the material list, and the PNG for each material's texture, all packed into the
GLB binary chunk.

The game stores geometry Z-up while glTF is Y-up, and positions are rewritten as ``(x, z, -y)``.

Every material is written double-sided. The console never culls a back face. The Graphics
Synthesizer has no such hardware, and the engine's cull test (``ss_MiniGL_v1``'s
``mCullFace``/``mFrontFace`` state, read by one function at ``0x001D9AF0``) is available only from
the immediate-mode ``mBegin``/``mEnd`` path. Neither the level renderer (``t_EnvMesh``) nor the prop
renderer uses it. Both build DMA chains straight to VIF1 and run a VU1 microprogram whose only
rejection is a whole packet failing an eight-corner bounding-box frustum test. Winding was therefore
never load-bearing, the cooker made plenty of it inconsistent, and culling on export drops surfaces
the game genuinely draws.
"""
from __future__ import annotations

from math import cos, isfinite, sin
from typing import TYPE_CHECKING, Any
import io
import logging
import struct

from PIL.Image import new as new_image

from dade.common.gltf import (
    ARRAY_BUFFER,
    ELEMENT_ARRAY_BUFFER,
    FLOAT,
    TRIANGLES,
    UNSIGNED_BYTE,
    UNSIGNED_INT,
    UNSIGNED_SHORT,
    GLBDocument,
)

from .model import BLEND_PASSES, read_materials, read_meshes, triangles
from .prop import (
    is_alternate,
    read_items,
    read_materials as read_prop_materials,
    read_sections,
    wardrobe_key,
)
from .texture import decode, iter_geometry_textures
from .typing import BlendMode

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

_IMAGE_RECORD_BIAS = 0x80
_GLOW_STRENGTH = 0.14
_SKIN_HINTS = ('body', 'suit', 'torso', 'head', 'face')
_ALPHA_CLEAR = 0.02
_ALPHA_PARTIAL = 0.20
_TRIANGLE_CORNERS = 3
# GS TEST_1 alpha test: ATST GEQUAL with AREF 8 on the PS2's 0..128 scale, giving 16 of 255 here.
_CUTOUT_REF = 16 / 255
_SHORT_INDEX_LIMIT = 0xFFFF


def _finite(value: float) -> float:
    """
    Replace a non-finite coordinate with zero.

    A few of the game's vertices store NaN or infinite texture coordinates. glTF accessors may not
    include those, and a validator rejects the whole file over them.

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


def _mesh_arrays(mesh: Mesh, *, glow: bool = False) -> tuple[bytes, bytes, bytes, list[int], int]:
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
            # A glow sprite is additive on hardware, and its brightness is how much it shows
            # through. Ordinary blending cannot brighten, only cover, and the strength is therefore
            # set well down, making it a haze over whatever it lights rather than a wash hiding it.
            luminance = (red * 2 + green * 5 + blue) // 8
            alpha = int(luminance * _GLOW_STRENGTH) if glow else 255
            colors += bytes((red, green, blue, alpha))
        for a, b, c in triangles(len(packet.vertices), packet.primitive):
            pa, pb, pc = (packet.vertices[a][:3], packet.vertices[b][:3], packet.vertices[c][:3])
            if len({pa, pb, pc}) == _TRIANGLE_CORNERS:
                indices += [base + a, base + b, base + c]
        base += len(packet.vertices)
    return bytes(positions), bytes(texcoords), bytes(colors), indices, base


def _cooked_mode(image: Image, blend_mode: BlendMode) -> tuple[str, Image]:
    """
    Turn the cooker's blend mode into the nearest glTF alpha mode.

    glTF has neither the engine's additive ``Cs + Cd`` nor its subtractive ``Cd - Cs``, and both are
    therefore recast as ordinary alpha blending with alpha taken from luminance. That is right in
    direction. A black texel neither adds nor subtracts and must be transparent. A subtractive
    texture additionally goes black, and blending toward black by luminance darkens as intended.

    Parameters
    ----------
    image : Image
        The decoded texture, modified for the overlay modes.
    blend_mode : BlendMode
        The mode cooked into the texture's record.

    Returns
    -------
    tuple[str, Image]
        The glTF ``alphaMode`` and the image to store, rewritten by the overlay modes.
    """
    match blend_mode:
        case BlendMode.CUTOUT:
            return 'MASK', image
        case BlendMode.BLEND:
            return 'BLEND', image
        case BlendMode.ADDITIVE | BlendMode.SUBTRACTIVE:
            return 'BLEND', _as_overlay(image, darkening=blend_mode is BlendMode.SUBTRACTIVE)
        case _:
            # A pure white glow sprite is cooked as DEFAULT, and drawn as-is it is an opaque white
            # slab over whatever it was meant to light. It therefore gets the treatment the pass
            # alone cannot give it.
            return ('GLOW' if _is_glow(image) else 'OPAQUE'), image


def _material_images(data: bytes, *, cooked: bool = False) -> dict[int, tuple[bytes, str]]:
    """
    Render every embedded texture that a material references to PNG bytes.

    Parameters
    ----------
    data : bytes
        The whole geometry blob.
    cooked : bool
        Take each texture's alpha mode from the cooker's blend mode rather than inferring it from
        the image and its name.

    Returns
    -------
    dict[int, tuple[bytes, str]]
        Image record offset to the encoded PNG and the alpha mode that suits it.
    """
    out: dict[int, tuple[bytes, str]] = {}
    for texture in iter_geometry_textures(data):
        image = decode(data, texture)
        stem = texture.name.rsplit('/', 1)[-1].lower()
        if cooked:
            mode, image = _cooked_mode(image, texture.blend_mode)
        else:
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

    Sections identify their texture by name rather than pointing at it, and the images therefore
    have to be addressable by name.

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
        # Every texture this walk yields was rendered by the walk above, and the key is always set.
        found = images[texture.data_offset - _IMAGE_RECORD_BIAS]
        name = texture.name.rsplit('/', 1)[-1].lower()
        png, mode = found
        # Skin and clothing are never cut out. A few of these maps retain a small margin of clear
        # texels, enough to be taken for a stencil, and that punches holes in a face.
        if mode == 'MASK' and any(hint in name for hint in _SKIN_HINTS):
            found = (png, 'OPAQUE')
        by_name.setdefault(name, found)
    return by_name


def _prop_meshes(section: bytes) -> list[tuple[str, tuple[str, ...], bytes, bytes, list[int], int]]:
    """
    Flatten a ``.SGP2`` section into one entry per draw group.

    Each item's command list states which material draws which stretch of its geometry, and no
    guessing is needed. The group's material gives the texture outright. Where an item is one of a
    set of interchangeable pieces (a crowd character stores a wardrobe of jackets and shoes in the
    one model, and the game dresses each passer-by by handing the renderer a bitmask), only the
    first of each set is retained. Drawing them all sets the alternatives fighting in one space.

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
    White contributes nothing to a multiply, and on hardware the sprite's appearance comes entirely
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

    Neither blend is expressible in core glTF, and both are therefore recast as ordinary alpha
    blending with alpha taken from luminance. That works because both operations scale with how
    bright the source is. A nearly black texel adds nothing and subtracts nothing, and should be
    nearly invisible in both cases.

    A subtractive decal computes ``dest - src``. Its colour is therefore replaced with black, and
    blending toward black by ``luminance`` reproduces the darkening. These textures are very dark to
    begin with, the shadow, scum, and crack decals averaging 19 to 32 out of 255, and treating a
    dark texel as *more* opaque instead of less turns a faint smudge into a solid black patch.

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

    Anything fully opaque is ``OPAQUE``. Cut-out art such as foliage retains crisp edges with
    ``MASK``. The game's ``add_`` and ``sub_`` overlays are soft gradients and only look right with
    ``BLEND``; drawn opaque they appear as solid black patches.

    A texture is only treated as see-through when a meaningful share of it actually is. Some maps
    include an alpha channel that is not transparency at all. Tony's face has 0.4% of its texels
    near zero and 4% partly on, against 40% and 60% for a hair texture that really does need to be
    drawn with holes. Taking that face for translucent made him semi-transparent, with his skull
    showing through from the front and his face showing through from behind.

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


def build_glb(  # ruff: ignore[complex-structure, too-many-locals]
    data: bytes,
    *,
    generator: str = 'dade',
    libraries: Sequence[bytes] = (),
    placements: Sequence[Placement] = ()) -> bytes | None:
    """
    Build a binary glTF for one ``.EGP2`` geometry blob.

    A level's props and cast are not part of its geometry. They are stored once each in a ``.SGP2``
    library and placed by the level's ``.OLV``. Given both, every placement becomes a node with the
    object's position and turn, and the doors, chairs, and vehicles therefore appear where the game
    puts them rather than in a separate file. Objects placed more than once share a single mesh.

    A level's cast is spread over several libraries, and more than one may therefore be given; the
    first to list an object supplies it. A placement whose object no library stores is skipped.

    Parameters
    ----------
    data : bytes
        The whole geometry blob.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.
    libraries : Sequence[bytes]
        The level's ``.SGP2`` prop and character libraries, when their objects are to be placed.
    placements : Sequence[Placement]
        Where to put each of those libraries' objects, read from the level's ``.OLV``.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or ``None`` when the blob includes no decodable geometry.
    """
    meshes = read_meshes(data)
    if not meshes:
        return None
    materials = read_materials(data)
    images = _material_images(data, cooked=True)
    # A material belongs to exactly one pass, and the meshes give each one its pass.
    pass_of = {m.material: m.render_pass for m in meshes if m.material >= 0}
    document = GLBDocument(generator)
    gltf_meshes = document.meshes
    nodes = document.nodes
    used: dict[int, int] = {}
    glowing: set[int] = set()
    gltf_materials = document.materials
    for index, material in enumerate(materials):
        found = images.get(material.texture_offset) if material.texture_offset else None
        png, mode = found if found is not None else (None, 'OPAQUE')
        pbr: dict[str, Any] = {'baseColorFactor': [1.0, 1.0, 1.0, 1.0], 'metallicFactor': 0.0}
        if png is not None:
            pbr['baseColorTexture'] = {
                'index': document.add_image(png, 'image/png',
                                            material.name.rsplit('/', 1)[-1])
            }
        if mode == 'GLOW':
            glowing.add(index)
            mode = 'BLEND'
        elif mode == 'OPAQUE' and pass_of.get(index, 1) in BLEND_PASSES:
            # The mode is open here, and the pass decides. The pass this material sits in blends.
            mode = 'BLEND'
        used[index] = len(gltf_materials)
        entry: dict[str, Any] = {
            'name': material.name.rsplit('/', 1)[-1] or f'material_{index}',
            'pbrMetallicRoughness': pbr,
            'alphaMode': mode,
            'doubleSided': True
        }
        if mode == 'MASK':
            entry['alphaCutoff'] = _CUTOUT_REF
        gltf_materials.append(entry)

    for mesh in meshes:
        positions, texcoords, colors, indices, count = _mesh_arrays(mesh,
                                                                    glow=mesh.material in glowing)
        if not indices:
            continue
        floats = struct.unpack(f'<{count * 3}f', positions)
        axes = [floats[i::3] for i in range(3)]
        wide = count > _SHORT_INDEX_LIMIT
        packed = struct.pack(f'<{len(indices)}{"I" if wide else "H"}', *indices)
        primitive = {
            'attributes': {
                'POSITION':
                    document.accessor(positions,
                                      ARRAY_BUFFER,
                                      componentType=FLOAT,
                                      count=count,
                                      type='VEC3',
                                      min=[min(a) for a in axes],
                                      max=[max(a) for a in axes]),
                'TEXCOORD_0':
                    document.accessor(texcoords,
                                      ARRAY_BUFFER,
                                      componentType=FLOAT,
                                      count=count,
                                      type='VEC2'),
                'COLOR_0':
                    document.accessor(colors,
                                      ARRAY_BUFFER,
                                      componentType=UNSIGNED_BYTE,
                                      count=count,
                                      type='VEC4',
                                      normalized=True)
            },
            'indices':
                document.accessor(packed,
                                  ELEMENT_ARRAY_BUFFER,
                                  componentType=UNSIGNED_INT if wide else UNSIGNED_SHORT,
                                  count=len(indices),
                                  type='SCALAR'),
            'mode':
                TRIANGLES
        }
        if mesh.material in used:
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
                gltf_materials.append({
                    'name': name,
                    'pbrMetallicRoughness': {
                        'baseColorFactor': [1.0, 1.0, 1.0, 1.0],
                        'metallicFactor': 0.0,
                        'baseColorTexture': {
                            'index': document.add_image(png, 'image/png', name)
                        }
                    },
                    'alphaMode': 'BLEND' if mode == 'GLOW' else mode,
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
                            document.accessor(positions,
                                              ARRAY_BUFFER,
                                              componentType=FLOAT,
                                              count=count,
                                              type='VEC3',
                                              min=[min(a) for a in axes],
                                              max=[max(a) for a in axes]),
                        'TEXCOORD_0':
                            document.accessor(texcoords,
                                              ARRAY_BUFFER,
                                              componentType=FLOAT,
                                              count=count,
                                              type='VEC2')
                    },
                    'indices':
                        document.accessor(packed,
                                          ELEMENT_ARRAY_BUFFER,
                                          componentType=UNSIGNED_INT if wide else UNSIGNED_SHORT,
                                          count=len(indices),
                                          type='SCALAR'),
                    'mode':
                        TRIANGLES
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
            # The game turns an object about its vertical axis, Z there and Y here.
            half = placement.rotation / 2
            nodes.append({
                'name': placement.name,
                'mesh': drawn,
                'translation': [placement.x, placement.z, -placement.y],
                'rotation': [0.0, sin(half), 0.0, cos(half)]
            })

    if not gltf_meshes:
        return None
    return document.finish('scene')


def build_prop_glb(data: bytes, *, generator: str = 'dade') -> bytes | None:
    """
    Build a binary glTF for a ``.SGP2`` prop and character library.

    Each object section becomes a separate node, retaining the object-local coordinates the file
    stores. A section identifies its textures by name rather than pointing at them, and each is
    therefore matched to the file's embedded image records by base name. Where a section lists as
    many textures as it has runs of packets, each run takes one; otherwise every run falls back to
    the first texture that resolves, and a character whose maps outnumber its runs still gets one of
    them throughout.

    Parameters
    ----------
    data : bytes
        The whole ``.SGP2`` file.
    generator : str
        Value recorded in the glTF ``asset.generator`` field.

    Returns
    -------
    bytes | None
        The ``.glb`` file, or ``None`` when the library includes no decodable geometry.
    """
    by_name = _prop_images(data)
    document = GLBDocument(generator)
    gltf_meshes = document.meshes
    nodes = document.nodes
    gltf_materials = document.materials
    material_for: dict[str, int] = {}

    def material(name: str) -> int | None:
        if name in material_for:
            return material_for[name]
        found = by_name.get(name)
        if found is None:
            return None
        png, mode = found
        gltf_materials.append({
            'name': name,
            'pbrMetallicRoughness': {
                'baseColorFactor': [1.0, 1.0, 1.0, 1.0],
                'metallicFactor': 0.0,
                'baseColorTexture': {
                    'index': document.add_image(png, 'image/png', name)
                }
            },
            'alphaMode': 'BLEND' if mode == 'GLOW' else mode,
            'doubleSided': True
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
                    document.accessor(positions,
                                      ARRAY_BUFFER,
                                      componentType=FLOAT,
                                      count=base,
                                      type='VEC3',
                                      min=[min(a) for a in axes],
                                      max=[max(a) for a in axes]),
                'TEXCOORD_0':
                    document.accessor(texcoords,
                                      ARRAY_BUFFER,
                                      componentType=FLOAT,
                                      count=base,
                                      type='VEC2')
            }
            primitive_entry: dict[str, Any] = {
                'attributes':
                    attributes,
                'indices':
                    document.accessor(packed,
                                      ELEMENT_ARRAY_BUFFER,
                                      componentType=UNSIGNED_INT if wide else UNSIGNED_SHORT,
                                      count=len(indices),
                                      type='SCALAR'),
                'mode':
                    TRIANGLES
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
    return document.finish('scene')


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
