"""
Model converters: Incoming Dreamcast ``*_M.BIN`` / ``*_ML.BIN`` to OBJ, MTL, and JSON.

An ``*_ML.BIN`` is a directory of ``uint32`` file offsets into the matching ``*_M.BIN``, terminated
by ``0xFFFFFFFF``. Each offset points at a 144-byte object header in the ``*_M.BIN``; the active
level-of-detail record gives face and vertex counts plus file offsets to a vertex pool (40-byte
records) and a triangle pool (16-byte records). The high 16 bits of the count word are an index into
the level's ``*_T.PVR`` texture pack.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, NamedTuple
import json
import logging
import shutil
import struct

from incoming_extractor.context import input_root
from incoming_extractor.textures import find_level_pack, place_pack_textures

from ._base import ConversionError

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('mbin_to_obj', 'mlbin_to_json')

log = logging.getLogger(__name__)

_ML_SENTINEL = 0xffffffff
_ML_MAX_ENTRIES = 510
_OBJECT_HEADER_SIZE = 0x90
_RECORD0_OFFSET = 0x10
_RECORD = struct.Struct('<5I')
_VERTEX = struct.Struct('<10f')
_VERTEX_STRIDE = 0x28
_FACE = struct.Struct('<4I')
_FACE_STRIDE = 0x10
_U32 = struct.Struct('<I')
_FACE_TRIANGLE = 3


class _Object(NamedTuple):
    texture_index: int
    vertices: tuple[tuple[float, ...], ...]
    triangles: tuple[tuple[int, int, int], ...]


def _read_ml_offsets(data: bytes) -> tuple[int, ...]:
    offsets = []
    for i in range(min(_ML_MAX_ENTRIES, len(data) // _U32.size)):
        value = _U32.unpack_from(data, i * _U32.size)[0]
        if value == _ML_SENTINEL:
            break
        offsets.append(value)
    return tuple(offsets)


def _find_ml_sibling(source: Path) -> Path:
    lowered = source.name.lower()
    index = lowered.rfind('_m.bin')
    base = source.name[:index]
    for candidate in (f'{base}_ML.BIN', f'{base}_ml.bin', f'{base}_Ml.BIN'):
        sibling = source.with_name(candidate)
        if sibling.is_file():
            return sibling
    msg = f'No matching _ML.BIN index found beside `{source.name}`.'
    raise ConversionError(msg)


def _parse_object(model: bytes, header_offset: int) -> _Object | None:
    if header_offset + _OBJECT_HEADER_SIZE > len(model):
        return None
    _, face_count, packed, vertices_ptr, faces_ptr = _RECORD.unpack_from(
        model, header_offset + _RECORD0_OFFSET)
    vertex_count = packed & 0xffff
    texture_index = packed >> 16
    if (not face_count or not vertex_count
            or vertices_ptr + vertex_count * _VERTEX_STRIDE > len(model)
            or faces_ptr + face_count * _FACE_STRIDE > len(model)):
        return None
    vertices = tuple(_iter_vertices(model, vertices_ptr, vertex_count))
    triangles = tuple(_iter_triangles(model, faces_ptr, face_count, vertex_count))
    if not triangles:
        return None
    return _Object(texture_index, vertices, triangles)


def _iter_vertices(model: bytes, offset: int, count: int) -> Iterator[tuple[float, ...]]:
    for i in range(count):
        x, y, z, _, nx, ny, nz, _, u, v = _VERTEX.unpack_from(model, offset + i * _VERTEX_STRIDE)
        yield (x, y, z, nx, ny, nz, u, v)


def _iter_triangles(model: bytes, offset: int, count: int,
                    vertex_count: int) -> Iterator[tuple[int, int, int]]:
    for i in range(count):
        marker, a, b, c = _FACE.unpack_from(model, offset + i * _FACE_STRIDE)
        if (marker & 0xffff) != _FACE_TRIANGLE or max(a, b, c) >= vertex_count:
            continue
        yield (a, b, c)


def _iter_objects(model: bytes, offsets: tuple[int, ...]) -> Iterator[_Object]:
    seen: set[int] = set()
    for offset in offsets:
        if offset in seen:
            continue
        seen.add(offset)
        if (parsed := _parse_object(model, offset)) is not None:
            yield parsed


def _object_obj_lines(obj: _Object, index: int, mtl_name: str) -> Iterator[str]:
    yield '# Incoming Dreamcast _M.BIN object.'
    yield '# Incoming is left-handed with up = -Y; OBJ is right-handed with up = +Y.'
    yield '# Negating Y alone performs that left-to-right-handed conversion and the up flip, and'
    yield '# turns the game clockwise-front winding into OBJ counter-clockwise-front (kept as-is).'
    yield '# Texture V is flipped (1 - v) from the game top-left origin to the OBJ bottom-left.'
    yield f'mtllib {mtl_name}'
    yield f'o object_{index}'
    for vert in obj.vertices:
        yield f'v {vert[0]} {-vert[1]} {vert[2]}'
    for vert in obj.vertices:
        yield f'vn {vert[3]} {-vert[4]} {vert[5]}'
    for vert in obj.vertices:
        yield f'vt {vert[6]} {1.0 - vert[7]}'
    yield f'usemtl tex_{obj.texture_index}'
    for a, b, c in obj.triangles:
        ai, bi, ci = a + 1, b + 1, c + 1
        yield f'f {ai}/{ai}/{ai} {bi}/{bi}/{bi} {ci}/{ci}/{ci}'


def _object_mtl_lines(obj: _Object, texture_name: str | None) -> Iterator[str]:
    yield f'newmtl tex_{obj.texture_index}'
    if texture_name is not None:
        yield f'map_Kd {texture_name}'
    else:
        yield f'# Sub-texture index {obj.texture_index} of the level _T.PVR pack (not resolved).'
    yield 'Kd 0.8 0.8 0.8'


def mbin_to_obj(source: Path, dest_dir: Path) -> tuple[Path, ...]:
    """
    Convert an Incoming Dreamcast ``*_M.BIN`` model pack into one OBJ + MTL per object.

    A ``*_M.BIN`` is a pack of many independent objects indexed by the matching ``*_ML.BIN``. Each
    decodable mesh object is written as its own ``<stem>_<NNN>.obj`` and ``.mtl`` in a directory
    named after the source. Non-mesh objects (sprites and placeholders) are skipped, and each
    object's texture is extracted from the level ``*_T.PVR`` pack and referenced from its material.

    Parameters
    ----------
    source : Path
        The source ``*_M.BIN`` file.
    dest_dir : Path
        The directory the per-model output directory is created in.

    Returns
    -------
    tuple[Path, ...]
        The written OBJ, MTL, and texture PNG paths.

    Raises
    ------
    ConversionError
        If the ``*_ML.BIN`` index is missing or no geometry is found.
    """
    offsets = _read_ml_offsets(_find_ml_sibling(source).read_bytes())
    objects = tuple(_iter_objects(source.read_bytes(), offsets))
    if not objects:
        msg = f'`{source.name}` contains no decodable mesh objects.'
        raise ConversionError(msg)
    model_dir = dest_dir / source.stem
    model_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    with TemporaryDirectory() as cache:
        index_pngs = _extract_textures(source, objects, Path(cache))
        for index, obj in enumerate(objects):
            stem = f'{source.stem}_{index:03d}'
            obj_path = model_dir / f'{stem}.obj'
            mtl_path = model_dir / f'{stem}.mtl'
            obj_path.write_text('\n'.join(_object_obj_lines(obj, index, mtl_path.name)) + '\n',
                                encoding='utf-8')
            texture_name = None
            if (cached := index_pngs.get(obj.texture_index)) is not None:
                texture_name = f'{stem}.png'
                shutil.copyfile(cached, model_dir / texture_name)
                outputs.append(model_dir / texture_name)
            mtl_path.write_text('\n'.join(_object_mtl_lines(obj, texture_name)) + '\n',
                                encoding='utf-8')
            outputs += (obj_path, mtl_path)
    return tuple(outputs)


def _extract_textures(source: Path, objects: tuple[_Object, ...], cache: Path) -> dict[int, Path]:
    if (root := input_root()) is None:
        return {}
    base = source.name[:source.name.lower().rfind('_m.bin')]
    if (pack := find_level_pack(root, base)) is None:
        return {}
    indices = {obj.texture_index for obj in objects}
    return {
        index: cache / name
        for index, name in place_pack_textures(pack, indices, cache, source.stem).items()
    }


def mlbin_to_json(source: Path, dest_dir: Path) -> Path:
    """
    Convert an Incoming Dreamcast ``*_ML.BIN`` model index to JSON.

    Parameters
    ----------
    source : Path
        The source ``*_ML.BIN`` file.
    dest_dir : Path
        The directory the JSON is written to.

    Returns
    -------
    Path
        The written JSON path.
    """
    offsets = _read_ml_offsets(source.read_bytes())
    obj = {'count': len(offsets), 'offsets': list(offsets)}
    destination = dest_dir / f'{source.stem}.json'
    destination.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return destination
