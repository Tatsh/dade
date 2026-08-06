"""Convert milo-extracted RndMesh objects (``.mesh``) to Wavefront OBJ, and link materials."""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import re
import shutil
import struct

from destin.common.obj import encode_obj
from destin.common.utils import safe_name

from .typing import Geometry

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('EXTENSIONS', 'convert', 'link_materials', 'mesh_to_obj')

log = logging.getLogger(__name__)

EXTENSIONS = frozenset({'.mesh'})
"""File extensions handled by :py:func:`convert`."""

_MESH_VERSION = 14
_VERTEX_STRIDE = 56  # v14 stream vertex: pos@0, weights@12, normal@20, colour@32, uv@48.
_NORMAL_OFFSET = 20
_UV_OFFSET = 48
_V10_VERSION = 10  # FreQuency RndMesh.
_V10_NORMAL_OFFSET = 12  # v10 stream vertex: pos@0, normal@12, uv@28 (stride 56, same as v14).
_V10_UV_OFFSET = 28
_V10_MIN_VERTS = 3  # Below this a v10 candidate vertex vector is too small to be real geometry.
_V10_POS_SAMPLES = 30  # Positions sampled across a candidate vector to validate it is geometry.
_V10_POS_LIMIT = 1.0e7  # A real vertex position is finite and well within this magnitude.
_FACE_STRIDE = 6  # Three uint16 indices.
_MAX_VERTS = 200000
_MAX_FACES = 400000
_MATERIAL_RE = re.compile(r'^# material: (.+)$', re.MULTILINE)
_MESH_MIN_SIZE = 8  # Version plus the start of the transform header.
_TVER_FLAG_RANGE = range(2, 5)  # Transform versions 2..4 carry an extra flag byte.
_MAX_STR_LEN = 128  # Upper bound on a plausible texture-name length.
_PRINTABLE = range(32, 127)  # Printable ASCII range.


def _u32(data: bytes, off: int) -> int:
    return int(struct.unpack_from('<I', data, off)[0])


def _parse_v14_mesh(data: bytes) -> Geometry | None:
    """
    Walk a version-14 RndMesh body to locate its vertex and face vectors.

    The geometry sits behind a variable-length header (transform matrices, three name-handle
    lists, material/name strings, bounds), so it must be walked, not scanned.

    Parameters
    ----------
    data : bytes
        The ``.mesh`` object body.

    Returns
    -------
    Geometry | None
        The located geometry, or ``None`` if the body is not a parseable v14 mesh.
    """
    if len(data) < _MESH_MIN_SIZE or _u32(data, 0) != _MESH_VERSION:
        return None

    def rstr(off: int) -> int:
        return off + 4 + _u32(data, off)

    def rhl(off: int) -> int:  # Handle list: u32 count + count length-prefixed names.
        count = _u32(data, off)
        off += 4
        for _ in range(count):
            off = rstr(off)
        return off

    # A struct error anywhere in the variable-length header means this is not a v14 mesh.
    try:  # noqa: PLW0717
        tver = _u32(data, 4)
        off = rhl(4 + 4 + 96)  # version + 24 matrix floats + child handle list.
        if tver > 0:
            off += 16  # Constraint + pivot.
        if tver in _TVER_FLAG_RANGE:
            off += 1
        off = rhl(off + 4 + 1)  # RndDrawable: version, flag, handle list.
        off = rhl(off + 4)  # RndCollideable: version, handle list.
        off += 8  # field_0xe0 / field_0xe4.
        material = data[off + 4:off + 4 + _u32(data, off)].decode('latin-1')
        off = rstr(rstr(rstr(off)))  # Material name + two more name strings.
        off += 16  # Bounds (four floats).
        off = rstr(off) + 4  # field_0x150 string + field_0x14c.
        off += 1  # field_0x154.
        vertex_count = _u32(data, off)
        vertex_start = off + 4
        face_pos = vertex_start + vertex_count * _VERTEX_STRIDE
        if face_pos + 4 > len(data):
            return None
        face_count = _u32(data, face_pos)
    except struct.error:
        return None
    if not (0 < vertex_count <= _MAX_VERTS and 0 <= face_count <= _MAX_FACES):
        return None
    face_start = face_pos + 4
    if face_start + face_count * _FACE_STRIDE > len(data):
        return None
    return Geometry(vertex_count, vertex_start, face_count, face_start, material)


def _v10_positions_finite(data: bytes, vertex_start: int, count: int) -> bool:
    step = max(1, count // _V10_POS_SAMPLES)
    for k in range(0, count, step):
        pos = struct.unpack_from('<3f', data, vertex_start + k * _VERTEX_STRIDE)
        if not all(v == v and abs(v) < _V10_POS_LIMIT for v in pos):  # noqa: PLR0124
            return False
    return True


def _v10_faces_valid(data: bytes, face_start: int, count: int, vertex_count: int) -> bool:
    return all(
        max(struct.unpack_from('<3H', data, face_start + k * _FACE_STRIDE)) < vertex_count
        for k in range(count))


def _parse_v10_mesh(data: bytes) -> Geometry | None:
    """
    Locate the vertex and face vectors of a FreQuency version-10 RndMesh.

    The geometry sits behind a variable header that is not uniformly length-prefixed, so the vector
    is found by scanning for a ``u32`` count whose ``count * 56``-byte vertex block (with finite
    positions) is followed by a ``u32`` face count whose ``3 * uint16`` indices are all in range.
    The match is unambiguous in practice.

    Parameters
    ----------
    data : bytes
        The ``.mesh`` object body.

    Returns
    -------
    Geometry | None
        The located geometry (with no material name), or ``None`` if no v10 geometry is present.
    """
    n = len(data)
    if n < _MESH_MIN_SIZE or _u32(data, 0) != _V10_VERSION:
        return None
    for count_off in range(_MESH_MIN_SIZE, n - _MESH_MIN_SIZE):
        vertex_count = _u32(data, count_off)
        if not _V10_MIN_VERTS <= vertex_count <= _MAX_VERTS:
            continue
        vertex_start = count_off + 4
        face_pos = vertex_start + vertex_count * _VERTEX_STRIDE
        if face_pos + 4 > n or not _v10_positions_finite(data, vertex_start, vertex_count):
            continue
        face_count = _u32(data, face_pos)
        face_start = face_pos + 4
        if not 0 < face_count <= _MAX_FACES or face_start + face_count * _FACE_STRIDE > n:
            continue
        if _v10_faces_valid(data, face_start, face_count, vertex_count):
            return Geometry(vertex_count, vertex_start, face_count, face_start, '')
    return None


def mesh_to_obj(data: bytes) -> str | None:
    """
    Convert an Amplitude (v14) or FreQuency (v10) RndMesh body to Wavefront OBJ text.

    Parameters
    ----------
    data : bytes
        The ``.mesh`` object body.

    Returns
    -------
    str | None
        The OBJ text, or ``None`` if the body is not a parseable v14 or v10 mesh.
    """
    geo = _parse_v14_mesh(data)
    normal_off, uv_off = _NORMAL_OFFSET, _UV_OFFSET
    if geo is None:
        geo = _parse_v10_mesh(data)
        normal_off, uv_off = _V10_NORMAL_OFFSET, _V10_UV_OFFSET
    if geo is None:
        return None
    for k in range(min(geo.face_count, 8)):  # Sanity: face indices must be in range.
        if max(struct.unpack_from('<3H', data,
                                  geo.face_start + k * _FACE_STRIDE)) >= geo.vertex_count:
            return None
    header = ['# Harmonix RndMesh -> OBJ']
    if geo.material:
        header.append(f'# material: {geo.material}')
    vertices, texcoords, normals = [], [], []
    for k in range(geo.vertex_count):
        base = geo.vertex_start + k * _VERTEX_STRIDE
        x, y, z = struct.unpack_from('<3f', data, base)
        nx, ny, nz = struct.unpack_from('<3f', data, base + normal_off)
        u, v = struct.unpack_from('<2f', data, base + uv_off)
        vertices.append((x, y, z))
        texcoords.append((u, 1.0 - v))  # OBJ uses a bottom-left UV origin.
        normals.append((nx, ny, nz))
    faces = [
        struct.unpack_from('<3H', data, geo.face_start + k * _FACE_STRIDE)
        for k in range(geo.face_count)
    ]
    return encode_obj(vertices,
                      faces,
                      texcoords=texcoords,
                      normals=normals,
                      header=header,
                      coordinate_format='{:.6g}',
                      texcoord_format='{:.6g}')


def convert(path: Path) -> Path | None:
    """
    Convert a ``.mesh`` object to a sibling ``.obj`` (the ``.mesh`` is kept).

    Parameters
    ----------
    path : pathlib.Path
        The ``.mesh`` file.

    Returns
    -------
    pathlib.Path | None
        The written OBJ path, or ``None`` if the body was not a parseable v14 mesh. The
        ``.mesh`` is kept because the OBJ is a lossy view (no bone weights or LODs).
    """
    obj = mesh_to_obj(path.read_bytes())
    if obj is None:
        return None
    out = path.with_suffix('.obj')
    out.write_text(obj, encoding='utf-8')
    log.debug('Mesh `%s` -> `%s`.', path.name, out.name)
    return out


def _mat_textures(data: bytes) -> list[str]:
    found: list[str] = []
    off = 0
    while off + 4 <= len(data):
        n = struct.unpack_from('<I', data, off)[0]
        if 0 < n < _MAX_STR_LEN and off + 4 + n <= len(data):
            chunk = data[off + 4:off + 4 + n]
            if all(c in _PRINTABLE for c in chunk):
                text = chunk.decode('latin-1')
                if text.lower().endswith(('.tex', '.bmp')):
                    found.append(text)
                off += 4 + n
                continue
        off += 1
    return ([t for t in found if t.lower().endswith('.bmp')] +
            [t for t in found if t.lower().endswith('.tex')])


def link_materials(root: Path) -> int:
    """
    Link every ``.obj`` to its material's texture (post-extraction pass).

    For each ``.obj`` naming a material, finds the sibling ``.mat`` object, resolves its texture
    to a ``.png`` anywhere under ``root``, copies that ``.png`` next to the ``.obj`` as
    ``<stem>.png`` (matching the ``.mtl``) so the pair is self-contained, writes a ``.mtl``
    referencing it, and links it from the ``.obj``.

    Parameters
    ----------
    root : pathlib.Path
        The extraction root.

    Returns
    -------
    int
        The number of materials linked.
    """
    png_index: dict[str, Path] = {}
    for png in root.rglob('*.png'):
        png_index.setdefault(png.stem.lower(), png)
    linked = 0
    for obj in root.rglob('*.obj'):
        text = obj.read_text(encoding='utf-8')
        match = _MATERIAL_RE.search(text)
        if not match:
            continue
        mat_path = obj.parent / safe_name(match.group(1).strip())
        if not mat_path.is_file():
            continue
        textures = _mat_textures(mat_path.read_bytes())
        tex_png = next((png_index[t.rsplit('.', 1)[0].lower()]
                        for t in textures if t.rsplit('.', 1)[0].lower() in png_index), None)
        if tex_png is None:
            log.debug('No texture PNG found for the material of `%s`.', obj.name)
            continue
        stem = obj.stem
        texture = f'{stem}.png'.replace(' ', '_')  # Space-free so the .mtl map_Kd resolves.
        dst = obj.parent / texture
        if tex_png.resolve() != dst.resolve():  # Copy the texture in under the material's name.
            shutil.copy2(tex_png, dst)
            log.debug('Copied texture `%s` -> `%s`.', tex_png.name, texture)
        (obj.parent / f'{stem}.mtl').write_text(f'newmtl {stem}\nKd 1 1 1\nmap_Kd {texture}\n',
                                                encoding='utf-8')
        lines = text.split('\n')
        i = next((j for j, ln in enumerate(lines) if not ln.startswith('#')), 0)
        lines[i:i] = [f'mtllib {stem}.mtl', f'usemtl {stem}']
        obj.write_text('\n'.join(lines), encoding='utf-8')
        log.debug('Linked material for `%s` -> texture `%s`.', obj.name, texture)
        linked += 1
    return linked
