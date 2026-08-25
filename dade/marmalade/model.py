"""
``CIwModel`` decoder.

A model is a sequence of typed blocks. The ones needed to rebuild geometry are:

- ``CIwModelBlockVerts`` - int16 ``x, y, z`` vertices (count at ``+0xa``, data at ``+0x10``).
- ``CIwModelBlockGLUVs`` - int16 ``u, v`` texture coords, fixed-point /4096.
- ``CIwModelBlockGLTriList`` - u16 triangle indices (count at ``+0x1a``, data at ``+0x12``).

Degenerate triangles (two shared indices) are dropped. :func:`decode_model` returns a
:class:`Model`; :meth:`Model.to_obj` renders Wavefront OBJ text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import struct

from dade.common import io
from dade.common.obj import encode_obj

from .hashstring import iw_hash_string

__all__ = ('Model', 'decode_model')

log = logging.getLogger(__name__)

_H_TRIS = iw_hash_string('CIwModelBlockGLTriList')
_H_UVS = iw_hash_string('CIwModelBlockGLUVs')
_H_VERTS = iw_hash_string('CIwModelBlockVerts')
_UV_FIXED = 4096.0


@dataclass
class Model:
    """Decoded geometry of a ``CIwModel``."""

    vertices: list[tuple[int, int, int]] = field(default_factory=list)
    """Integer ``x, y, z`` positions."""
    uvs: list[tuple[float, float]] = field(default_factory=list)
    """Per-vertex ``u, v`` texture coordinates (empty if the model has none)."""
    triangles: list[tuple[int, int, int]] = field(default_factory=list)
    """Zero-based vertex-index triples (degenerate triangles already removed)."""
    def to_obj(self, comment: str = '') -> str:
        """
        Render the model as Wavefront OBJ text.

        Parameters
        ----------
        comment : str, optional
            Extra text appended to the header comment line.

        Returns
        -------
        str
            OBJ document (trailing newline included).
        """
        head = f'# CIwModel -> OBJ  verts={len(self.vertices)} tris={len(self.triangles)}'
        head += f'  {comment}' if comment else ''
        return encode_obj(self.vertices,
                          self.triangles,
                          texcoords=self.uvs or None,
                          header=(head,),
                          coordinate_format='{}',
                          texcoord_format='{:.5f}')


def _find_block(body: bytes, block_hash: int) -> int | None:
    """
    Find the first block whose 4-byte hash matches.

    Parameters
    ----------
    body : bytes
        Raw serialised ``CIwModel`` body.
    block_hash : int
        IwHashString of the block class to locate.

    Returns
    -------
    int or None
        The block's offset, or ``None`` if it is not present.
    """
    pos = body.find(struct.pack('<I', block_hash))
    return pos if pos >= 0 else None


def decode_model(body: bytes) -> Model:
    """
    Decode a ``CIwModel`` body to a :class:`Model`.

    Parameters
    ----------
    body : bytes
        Raw serialised ``CIwModel`` body.

    Returns
    -------
    Model
        Decoded vertices, UVs and triangles.

    Raises
    ------
    ValueError
        If the required Verts or GLTriList block is missing.
    """
    def u16(o: int) -> int:
        return io.u16(body, o)

    def i16(o: int) -> int:
        return io.i16(body, o)

    v_block = _find_block(body, _H_VERTS)
    t_block = _find_block(body, _H_TRIS)
    if v_block is None or t_block is None:
        msg = 'Model is missing its Verts or GLTriList block.'
        raise ValueError(msg)
    n = u16(v_block + 0xA)
    vd = v_block + 0x10
    vertices = [(i16(vd + i * 6), i16(vd + i * 6 + 2), i16(vd + i * 6 + 4)) for i in range(n)]
    uvs: list[tuple[float, float]] = []
    u_block = _find_block(body, _H_UVS)
    if u_block is not None and u16(u_block + 0xA) == n:
        ud = u_block + 0x10
        uvs = [(i16(ud + i * 4) / _UV_FIXED, i16(ud + i * 4 + 2) / _UV_FIXED) for i in range(n)]
    n_idx = u16(t_block + 0x1A)
    n_idx -= n_idx % 3
    idx = [u16(t_block + 0x12 + i * 2) for i in range(n_idx)]
    triangles = []
    for i in range(0, len(idx), 3):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        if b not in {a, c} and a != c:
            triangles.append((a, b, c))
    log.debug('Decoded model with %d vertices, %d UVs and %d triangles (%d raw indices).', n,
              len(uvs), len(triangles), n_idx)
    return Model(vertices=vertices, uvs=uvs, triangles=triangles)
