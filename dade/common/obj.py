"""
Wavefront OBJ writer shared by the game model exporters.

Several games decode proprietary meshes and emit Wavefront OBJ. They differ only in cosmetic
details -- the coordinate number format, whether texture coordinates and normals are present, the
face-index base, and the header lines -- so a single parameterised encoder reproduces each one's
exact output.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ('encode_obj',)


def _face_field(index: int, *, base: int, texcoord: bool, normal: bool) -> str:
    """
    Format one face corner as ``v``, ``v/vt``, ``v//vn``, or ``v/vt/vn``.

    Parameters
    ----------
    index : int
        The vertex index as stored in the mesh.
    base : int
        Offset added to *index* (``1`` yields the one-based indices OBJ requires).
    texcoord : bool
        Whether a texture-coordinate index is emitted.
    normal : bool
        Whether a normal index is emitted.

    Returns
    -------
    str
        The formatted corner, reusing the vertex index for every component.
    """
    i = index + base
    if normal:
        return f'{i}/{i}/{i}' if texcoord else f'{i}//{i}'
    return f'{i}/{i}' if texcoord else str(i)


def encode_obj(vertices: Sequence[tuple[float, float, float]],
               faces: Iterable[tuple[int, int, int]],
               *,
               texcoords: Sequence[tuple[float, float]] | None = None,
               normals: Sequence[tuple[float, float, float]] | None = None,
               header: Sequence[str] = (),
               material: str | None = None,
               coordinate_format: str = '{:.6f}',
               texcoord_format: str = '{:.6f}',
               base: int = 1,
               normals_before_texcoords: bool = False) -> str:
    """
    Encode a mesh as Wavefront OBJ text.

    Parameters
    ----------
    vertices : Sequence[tuple[float, float, float]]
        Vertex positions, already in the desired output coordinate system.
    faces : Iterable[tuple[int, int, int]]
        Triangles as triples of vertex indices; *base* is added to each.
    texcoords : Sequence[tuple[float, float]]
        Texture coordinates, already flipped to the OBJ origin if required. When given, faces
        reference a texture-coordinate index.
    normals : Sequence[tuple[float, float, float]]
        Vertex normals. When given, faces reference a normal index.
    header : Sequence[str]
        Verbatim lines emitted before the geometry, such as ``o name``, comments, or ``mtllib``.
    material : str
        Material name emitted as a ``usemtl`` line before the faces, if given.
    coordinate_format : str
        :py:meth:`str.format` template for each ``v``/``vn`` component.
    texcoord_format : str
        :py:meth:`str.format` template for each ``vt`` component.
    base : int
        Offset added to every face index; ``1`` produces the conventional one-based indices.
    normals_before_texcoords : bool
        Emit the ``vn`` block before the ``vt`` block. The default emits ``vt`` first.

    Returns
    -------
    str
        The complete OBJ document, ending in a newline.
    """
    lines: list[str] = list(header)
    lines.extend(f'v {coordinate_format.format(x)} {coordinate_format.format(y)} '
                 f'{coordinate_format.format(z)}' for x, y, z in vertices)
    texcoord_lines = (
        [f'vt {texcoord_format.format(u)} {texcoord_format.format(v)}'
         for u, v in texcoords] if texcoords is not None else [])
    normal_lines = ([
        f'vn {coordinate_format.format(x)} {coordinate_format.format(y)} '
        f'{coordinate_format.format(z)}' for x, y, z in normals
    ] if normals is not None else [])
    if normals_before_texcoords:
        lines.extend(normal_lines)
        lines.extend(texcoord_lines)
    else:
        lines.extend(texcoord_lines)
        lines.extend(normal_lines)
    if material is not None:
        lines.append(f'usemtl {material}')
    has_texcoord = texcoords is not None
    has_normal = normals is not None
    lines.extend('f '
                 f'{_face_field(a, base=base, texcoord=has_texcoord, normal=has_normal)} '
                 f'{_face_field(b, base=base, texcoord=has_texcoord, normal=has_normal)} '
                 f'{_face_field(c, base=base, texcoord=has_texcoord, normal=has_normal)}'
                 for a, b, c in faces)
    return '\n'.join(lines) + '\n'
