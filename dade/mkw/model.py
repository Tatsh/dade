"""Decode Mario Kart World BFRES v10 geometry into GLB."""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING
import re
import struct

from PIL import Image, ImageChops
import numpy as np
import zstandard

from dade.common.gltf import ARRAY_BUFFER, GLBDocument

from .texture import decode_texture

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('decode_model', 'model_lod_count')

# BFRES v10 offsets are adapted from MIT-licensed ns2-assets by dougchansan.
_SHAPE_SIZE = 0x60
_MESH_SIZE = 0x38
_MAX_COORDINATE = 1000
_MAX_STRING_SIZE = 256
_MIN_BFRES_SIZE = 0x180
_MIN_STRIDE = 12
_MAX_STRIDE = 256
_MAX_VERTICES = 10_000_000
_MIN_INLIER_RATIO = 0.9
_MIN_TRIANGLE_AREA = 1e-10
_TRIANGLE_VERTICES = 3
_TRIANGLE_TOPOLOGY = 3
_INDEX_U16 = 1
_INDEX_U32 = 2
_UV_FLOAT16 = 0x1205
_UV_FLOAT32 = 0x1705
_UV_UNORM16 = 0x1201
_UV_SNORM16 = 0x1202
_UV_UNORM8 = 0x0901
_UV_SNORM8 = 0x0902
_NORMAL_SNORM10 = 0x0E02
_SNORM10_SIGN_BIT = 512
_SHY_GUY_BAZAAR_TEXTURE_SIZE = 512
_ALBEDO_SUFFIX = re.compile(r'_Alb(?:\.\d+)?$')
_EMISSIVE_SUFFIX = re.compile(r'_Emm(?:\.\d+)?$')
_MASK_SUFFIX = re.compile(r'_Msk(?:\.\d+)?$')


def _u16(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<H', data, offset)[0])


def _u32(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<I', data, offset)[0])


def _u64(data: bytes, offset: int) -> int:
    return int(struct.unpack_from('<Q', data, offset)[0])


def _string(data: bytes, pointer: int) -> str:
    if not 0 < pointer < len(data) - 2:
        return ''
    length = _u16(data, pointer)
    if not 0 < length <= _MAX_STRING_SIZE or pointer + 2 + length > len(data):
        return ''
    return data[pointer + 2:pointer + 2 + length].decode('utf-8', 'replace')


def _prepared_image(image: bytes, source: Path, mask_name: str,
                    max_texture_size: int | None) -> bytes:
    """
    Resize a colour image and apply its separate transparency mask.

    Parameters
    ----------
    image : bytes
        Decoded colour PNG.
    source : Path
        Compressed colour texture source.
    mask_name : str
        Separate transparency mask name, or an empty string.
    max_texture_size : int | None
        Maximum width or height.

    Returns
    -------
    bytes
        PNG with the requested size and alpha channel.
    """
    with Image.open(BytesIO(image)) as source_image:
        resize = max_texture_size is not None and max(source_image.size) > max_texture_size
        if not mask_name and not resize:
            return image
        color_image = source_image.convert('RGBA')
        if resize and max_texture_size is not None:
            color_image.thumbnail((max_texture_size, max_texture_size), Image.Resampling.LANCZOS)
        if mask_name:
            mask_source = source.with_name(f'{mask_name}.bntx.zs')
            mask_raw = zstandard.ZstdDecompressor().decompress(mask_source.read_bytes())
            with Image.open(BytesIO(decode_texture(mask_raw))) as mask_image:
                alpha = mask_image.convert('RGB').getchannel('R')
                if alpha.size != color_image.size:
                    alpha = alpha.resize(color_image.size, Image.Resampling.BILINEAR)
                color_image.putalpha(ImageChops.multiply(color_image.getchannel('A'), alpha))
        with BytesIO() as output:
            color_image.save(output, format='PNG')
            return output.getvalue()


def _albedo_image(document: GLBDocument, source: Path, name: str, mask_name: str,
                  external_images: Path | None, max_texture_size: int | None) -> int:
    """
    Add a colour image to a GLB.

    Parameters
    ----------
    document : GLBDocument
        GLB under construction.
    source : Path
        Compressed BNTX source.
    name : str
        Texture name.
    mask_name : str
        Separate transparency mask name, or an empty string.
    external_images : Path | None
        Output directory for a shared PNG, or :py:obj:`None` to embed it.
    max_texture_size : int | None
        Maximum width or height of an embedded texture.

    Returns
    -------
    int
        Index into the document's textures.
    """
    filename = f'{name}-{mask_name}.png' if mask_name else f'{name}.png'
    if external_images is not None and (png := external_images / filename).exists():
        return document.add_image_uri(f'../../textures/Tex/{filename}', name)
    raw = zstandard.ZstdDecompressor().decompress(source.read_bytes())
    image = _prepared_image(decode_texture(raw), source, mask_name, max_texture_size)
    if external_images is None:
        return document.add_image(image, 'image/png', name)
    png = external_images / filename
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(image)
    return document.add_image_uri(f'../../textures/Tex/{filename}', name)


def _materials(data: bytes, model: int, document: GLBDocument, textures: Path | None,
               used: set[int], external_images: Path | None,
               max_texture_size: int | None) -> dict[int, int]:
    array = _u64(data, model + 0x38)
    indices = {}
    image_cache: dict[tuple[str, str], int] = {}
    for index in range(_u16(data, model + 0x6C)):
        if index not in used:
            continue
        entry = array + index * 0xB0
        if data[entry:entry + 4] != b'FMAT':
            message = 'Invalid BFRES material table.'
            raise ValueError(message)
        material: dict[str, object] = {
            'name': _string(data, _u64(data, entry + 8)),
            'doubleSided': True
        }
        names = _u64(data, entry + 0x20)
        texture_names = tuple(
            _string(data, _u64(data, names + offset * 8)) for offset in range(data[entry + 0xA3]))
        color = next((name for name in texture_names if _ALBEDO_SUFFIX.search(name)), '')
        if not color:
            color = next((name for name in texture_names if _EMISSIVE_SUFFIX.search(name)), '')
        mask = next((name for name in texture_names if _MASK_SUFFIX.search(name)), '')
        if color and textures is not None:
            source = textures / f'{color}.bntx.zs'
            if source.is_file():
                mask = mask if (textures / f'{mask}.bntx.zs').is_file() else ''
                key = (color, mask)
                if key not in image_cache:
                    image_cache[key] = _albedo_image(document, source, color, mask, external_images,
                                                     max_texture_size)
                material['pbrMetallicRoughness'] = {
                    'baseColorTexture': {
                        'index': image_cache[key]
                    },
                    'metallicFactor': 0.0,
                    'roughnessFactor': 1.0
                }
                if mask:
                    material['alphaMode'] = 'MASK'
                    material['alphaCutoff'] = 0.5
        indices[index] = len(document.materials)
        document.materials.append(material)
    return indices


def _vertex_data(data: bytes, vertex: int,
                 pool: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    stride = _u32(data, _u64(data, vertex + 0x38))
    count = _u32(data, vertex + 0x50)
    start = pool + _u32(data, vertex + 0x48)
    if not _MIN_STRIDE <= stride <= _MAX_STRIDE or not 0 < count <= _MAX_VERTICES:
        return None
    if start + stride * count > len(data):
        message = 'BFRES vertex buffer exceeds the file.'
        raise ValueError(message)
    flat = np.frombuffer(data, dtype='uint8', count=stride * count, offset=start)
    records = flat.reshape(count, stride)
    attribute = _u64(data, vertex + 8)
    if _string(data, _u64(data, attribute)) != '_p0':
        return None
    position_offset = _u16(data, attribute + 12)
    if position_offset + 12 > stride:
        return None
    positions = records[:, position_offset:position_offset + 12].copy().view('<f4')
    positions = positions.reshape(count, _TRIANGLE_VERTICES)
    inliers = np.isfinite(positions).all(axis=1)
    inliers &= (np.abs(positions) < _MAX_COORDINATE).all(axis=1)
    if inliers.mean() < _MIN_INLIER_RATIO:
        return None
    limit = max(10.0, 20.0 * float(np.median(np.abs(positions[inliers]))))
    valid = inliers & (np.abs(positions).max(axis=1) <= limit)
    positions[~valid] = 0.0
    return records, positions, valid


def _triangles(data: bytes, mesh: int, pool: int, positions: np.ndarray,
               valid: np.ndarray) -> list[int]:
    index_start = pool + _u32(data, mesh + 0x20)
    index_count = _u32(data, mesh + 0x2C)
    base_vertex = _u32(data, mesh + 0x30)
    if _u32(data, mesh + 0x24) != _TRIANGLE_TOPOLOGY:
        message = 'Unsupported BFRES primitive topology.'
        raise ValueError(message)
    index_format = _u32(data, mesh + 0x28)
    if index_format == _INDEX_U16:
        index_bytes, dtype = 2, '<u2'
    elif index_format == _INDEX_U32:
        index_bytes, dtype = 4, '<u4'
    else:
        message = 'Unsupported BFRES index format.'
        raise ValueError(message)
    if index_start + index_count * index_bytes > len(data):
        message = 'BFRES index buffer exceeds the file.'
        raise ValueError(message)
    indices = np.frombuffer(data, dtype=dtype, count=index_count, offset=index_start)
    if not len(indices) or int(indices.max()) + base_vertex >= len(positions):
        return []
    triangles: list[int] = []
    for offset in range(0, len(indices) - 2, _TRIANGLE_VERTICES):
        first, second, third = (int(value) + base_vertex for value in indices[offset:offset + 3])
        if len({first, second, third}) < _TRIANGLE_VERTICES:
            continue
        if not (valid[first] and valid[second] and valid[third]):
            continue
        edge_a = positions[second] - positions[first]
        edge_b = positions[third] - positions[first]
        if np.linalg.norm(np.cross(edge_a, edge_b)) > _MIN_TRIANGLE_AREA:
            triangles.extend((first, second, third))
    return triangles


def _uv_accessor(data: bytes, vertex: int, records: np.ndarray,
                 document: GLBDocument) -> int | None:
    count, stride = records.shape
    attributes = _u64(data, vertex + 8)
    for index in range(data[vertex + 0x4C]):
        attribute = attributes + index * 16
        if _string(data, _u64(data, attribute)) != '_u0':
            continue
        offset = _u16(data, attribute + 12)
        format_ = _u32(data, attribute + 8)
        width = (8 if format_ == _UV_FLOAT32 else 2 if format_ in {_UV_UNORM8, _UV_SNORM8} else 4)
        if offset + width > stride:
            return None
        if format_ == _UV_FLOAT16:
            uv = records[:, offset:offset + 4].copy().view('<f2')
            uv = uv.reshape(count, 2).astype('float32')
        elif format_ == _UV_FLOAT32:
            uv = records[:, offset:offset + 8].copy().view('<f4').reshape(count, 2)
        elif format_ == _UV_UNORM16:
            uv = records[:, offset:offset + 4].copy().view('<u2')
            uv = uv.reshape(count, 2).astype('float32') / 65535.0
        elif format_ == _UV_SNORM16:
            uv = records[:, offset:offset + 4].copy().view('<i2')
            uv = np.clip(uv.reshape(count, 2).astype('float32') / 32767.0, -1.0, 1.0)
        elif format_ == _UV_UNORM8:
            uv = records[:, offset:offset + 2].astype('float32') / 255.0
        elif format_ == _UV_SNORM8:
            signed = records[:, offset:offset + 2].copy().view('i1').reshape(count, 2)
            uv = np.clip(signed.astype('float32') / 127.0, -1.0, 1.0)
        else:
            return None
        np.nan_to_num(uv, copy=False, nan=0.0, neginf=0.0, posinf=0.0)
        return document.floats(uv.tolist(), 'VEC2', target=ARRAY_BUFFER)
    return None


def _normal_accessor(data: bytes, vertex: int, records: np.ndarray,
                     document: GLBDocument) -> int | None:
    count, stride = records.shape
    attributes = _u64(data, vertex + 8)
    for index in range(data[vertex + 0x4C]):
        attribute = attributes + index * 16
        if _string(data, _u64(data, attribute)) != '_n0':
            continue
        offset = _u16(data, attribute + 12)
        if _u32(data, attribute + 8) != _NORMAL_SNORM10 or offset + 4 > stride:
            return None
        packed = records[:, offset:offset + 4].copy().view('<u4').reshape(count)
        components = np.stack([((packed >> shift) & 0x3FF) for shift in (0, 10, 20)], axis=1)
        signed = np.where(components >= _SNORM10_SIGN_BIT,
                          components.astype('int32') - 1024, components)
        normals = np.clip(signed.astype('float32') / 511.0, -1.0, 1.0)
        lengths = np.linalg.norm(normals, axis=1)
        normals[lengths > 0] /= lengths[lengths > 0, None]
        normals[lengths == 0] = (0.0, 0.0, 1.0)
        return document.floats(normals.tolist(), 'VEC3', target=ARRAY_BUFFER)
    return None


def _shape(data: bytes, shape: int, pool: int, document: GLBDocument, index: int, lod: int,
           material_map: dict[int, int]) -> None:
    if data[shape:shape + 4] != b'FSHP':
        message = 'Invalid BFRES shape table.'
        raise ValueError(message)
    vertex = _u64(data, shape + 0x10)
    if data[vertex:vertex + 4] != b'FVTX':
        message = 'Invalid BFRES vertex table.'
        raise ValueError(message)
    if (geometry := _vertex_data(data, vertex, pool)) is None:
        return
    records, positions, valid = geometry
    mesh = _u64(data, shape + 0x18) + lod * _MESH_SIZE
    triangles = _triangles(data, mesh, pool, positions, valid)
    if not triangles:
        return
    position = document.floats(positions.tolist(), 'VEC3', target=ARRAY_BUFFER, bounds=True)
    attributes = {'POSITION': position}
    if (normal := _normal_accessor(data, vertex, records, document)) is not None:
        attributes['NORMAL'] = normal
    material_index = material_map.get(_u16(data, shape + 0x52))
    if (uv := _uv_accessor(data, vertex, records, document)) is not None:
        attributes['TEXCOORD_0'] = uv
    elif material_index is not None:
        material = document.materials[material_index]
        if 'pbrMetallicRoughness' in material:
            document.materials.append({'name': material['name'], 'doubleSided': True})
            material_index = len(document.materials) - 1
    primitive: dict[str, object] = {
        'attributes': attributes,
        'indices': document.indices(triangles),
        'mode': 4
    }
    if material_index is not None:
        primitive['material'] = material_index
    document.meshes.append({'name': f'shape-{index}', 'primitives': [primitive]})
    document.nodes.append({'mesh': len(document.meshes) - 1})


def model_lod_count(data: bytes) -> int:
    """
    Return the number of mesh detail levels in a BFRES model.

    Parameters
    ----------
    data : bytes
        Decompressed BFRES archive.

    Returns
    -------
    int
        Number of mesh detail levels, or zero for an animation-only archive.

    Raises
    ------
    ValueError
        The input is not a BFRES archive.
    """
    if data[:4] != b'FRES' or len(data) < _MIN_BFRES_SIZE:
        message = 'Invalid BFRES archive.'
        raise ValueError(message)
    model = _u32(data, 0x28)
    if data[model:model + 4] != b'FMDL':
        return 0
    shapes = _u64(data, model + 0x28)
    return max(
        (data[shapes + index * _SHAPE_SIZE + 0x5B] for index in range(_u16(data, model + 0x6A))),
        default=0)


def decode_model(data: bytes,
                 name: str,
                 textures: Path | None = None,
                 *,
                 lod: int = 0,
                 external_images: Path | None = None) -> bytes | None:
    """
    Decode meshes from a BFRES v10 archive.

    Parameters
    ----------
    data : bytes
        Decompressed BFRES file.
    name : str
        Scene name in the GLB.
    textures : Path | None
        Directory of compressed external textures.
    lod : int
        Mesh detail level, starting at zero for the highest detail.
    external_images : Path | None
        Destination for shared PNG images referenced by the GLB.

    Returns
    -------
    bytes | None
        GLB bytes, or :py:obj:`None` for an animation-only archive.

    Raises
    ------
    ValueError
        The archive has invalid geometry offsets.
    """
    if data[:4] != b'FRES' or len(data) < _MIN_BFRES_SIZE:
        message = 'Invalid BFRES archive.'
        raise ValueError(message)
    model = _u32(data, 0x28)
    if data[model:model + 4] != b'FMDL':
        return None
    pool_info = _u64(data, 0xB0)
    if not 0 < pool_info < len(data) - 12:
        message = 'Invalid BFRES GPU pool.'
        raise ValueError(message)
    pool_size = _u32(data, pool_info + 4)
    pool = _u32(data, pool_info + 8)
    if not 0 < pool < len(data) or not 0 < pool_size <= len(data) - pool:
        message = 'Invalid BFRES GPU pool.'
        raise ValueError(message)
    document = GLBDocument('dade mkw')
    shapes = _u64(data, model + 0x28)
    selected_shapes = []
    for shape_index in range(_u16(data, model + 0x6A)):
        shape = shapes + shape_index * _SHAPE_SIZE
        if lod >= data[shape + 0x5B]:
            continue
        selected_shapes.append((shape_index, shape))
    used_materials = {_u16(data, shape + 0x52) for _, shape in selected_shapes}
    max_texture_size = (_SHY_GUY_BAZAAR_TEXTURE_SIZE
                        if name.startswith('Stage_ShyGuyBazaar.') else None)
    material_map = _materials(data, model, document, textures, used_materials, external_images,
                              max_texture_size)
    for shape_index, shape in selected_shapes:
        _shape(data, shape, pool, document, shape_index, lod, material_map)
    if not document.meshes:
        return None
    return document.finish(name)
