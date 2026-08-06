"""
Export of a ``.PSX`` scene's geometry as an interleaved vertex buffer plus a manifest.

The buffer holds ``[x, y, z, u, v]`` as little-endian 32-bit floats per triangle vertex, grouped
so every batch draws with a single texture. Vertex positions are the sector-local 16-bit values
with no placement applied, and the manifest's ``scale`` converts them to the renderer's units.

Faces are split with the length-derived corner count and the fan triangulation that the original
converter used, rather than the flag-derived count the renderers used. See
:py:mod:`destin.thps2pc.psx` for why the two disagree.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
import json
import logging
import struct

if TYPE_CHECKING:
    from collections.abc import Container, Iterable, Mapping
    from pathlib import Path

    from .psx import Scene
    from .typing import CornerSource, MeshBatch, MeshManifest, Triangulation

__all__ = ('DEFAULT_SCALE', 'UNTEXTURED_KEY', 'MeshVertex', 'build_batches', 'index_bitmaps',
           'pack', 'write_manifest')

log = logging.getLogger(__name__)

DEFAULT_SCALE = 1.0 / 256.0
"""Scale factor that converts packed vertex positions to renderer units.

:meta hide-value:
"""
UNTEXTURED_KEY = 'untextured'
"""Batch key used for faces that carry no texture.

:meta hide-value:
"""


class MeshVertex(NamedTuple):
    """One triangle corner in the interleaved vertex buffer."""

    x: float
    """Position along the x axis."""
    y: float
    """Position along the y axis."""
    z: float
    """Position along the z axis."""
    u: float
    """Horizontal texture coordinate."""
    v: float
    """Vertical texture coordinate."""


def build_batches(scene: Scene,
                  checksums: Iterable[int],
                  *,
                  corner_source: CornerSource = 'length',
                  triangulation: Triangulation = 'fan') -> dict[str, tuple[MeshVertex, ...]]:
    """
    Group every triangle in a scene by the texture it draws with.

    Faces whose corner indices fall outside their sector's vertex table are skipped, as are
    faces whose texture index has no entry in the checksum table, which fall back to the
    untextured batch.

    Parameters
    ----------
    scene : Scene
        The scene to walk.
    checksums : Iterable[int]
        The scene's texture checksum table.
    corner_source : CornerSource
        How to derive a face's corner count.
    triangulation : Triangulation
        How to split a quad into triangles.

    Returns
    -------
    dict[str, tuple[MeshVertex, ...]]
        Batch key to its triangle vertices. The key is the texture checksum as eight uppercase
        hexadecimal digits, or :py:data:`UNTEXTURED_KEY`.
    """
    table = tuple(checksums)
    batches: dict[str, list[MeshVertex]] = {}
    for sector in scene.sectors:
        vertices = scene.vertices(sector)
        count = len(vertices)
        for face, slots in scene.triangles(sector,
                                           corner_source=corner_source,
                                           triangulation=triangulation):
            if any(face.corners[slot] >= count for slot in slots):
                continue
            key = UNTEXTURED_KEY
            if face.is_textured and face.texture_index < len(table):
                key = f'{table[face.texture_index]:08X}'
            corners = []
            for slot in slots:
                x, y, z = vertices[face.corners[slot]]
                u, v = face.uvs[slot] if face.is_textured else (0.0, 0.0)
                corners.append(MeshVertex(x, y, z, u, v))
            batches.setdefault(key, []).extend(corners)
    log.debug('Built %d batches from %d sectors.', len(batches), len(scene.sectors))
    return {key: tuple(value) for key, value in batches.items()}


def index_bitmaps(directories: Iterable[Path]) -> dict[str, Path]:
    """
    Index every bitmap under a set of directories by its upper-case stem.

    Parameters
    ----------
    directories : Iterable[Path]
        Directories to search recursively.

    Returns
    -------
    dict[str, Path]
        Upper-case file stem to the first matching path found.
    """
    index: dict[str, Path] = {}
    for base in directories:
        if not base.is_dir():
            log.debug('Skipping missing bitmap directory `%s`.', base)
            continue
        for path in base.rglob('*'):
            if path.is_file() and path.suffix.lower() == '.bmp':
                index.setdefault(path.stem.upper(), path)
    log.debug('Indexed %d bitmaps.', len(index))
    return index


def pack(batches: Mapping[str, tuple[MeshVertex, ...]],
         resolved: Container[str],
         scale: float = DEFAULT_SCALE) -> tuple[bytes, MeshManifest]:
    """
    Serialise batches into an interleaved vertex buffer and its manifest.

    Parameters
    ----------
    batches : Mapping[str, tuple[MeshVertex, ...]]
        Batches produced by :py:func:`build_batches`.
    resolved : Container[str]
        Batch keys whose texture was written successfully. Any other batch is recorded with a
        null texture.
    scale : float
        Uniform scale factor recorded in the manifest.

    Returns
    -------
    tuple[bytes, MeshManifest]
        The vertex buffer and the manifest describing it.
    """
    blob = bytearray()
    entries: list[MeshBatch] = []
    first = 0
    for key in sorted(batches):
        corners = batches[key]
        for corner in corners:
            blob += struct.pack('<5f', *corner)
        entries.append({
            'texture': key if key != UNTEXTURED_KEY and key in resolved else None,
            'first_vertex': first,
            'vertex_count': len(corners)
        })
        first += len(corners)
    return bytes(blob), {'scale': scale, 'batches': entries}


def write_manifest(manifest: MeshManifest, dest: Path) -> None:
    """
    Write a manifest as JSON, using the key names the renderer expects.

    Parameters
    ----------
    manifest : MeshManifest
        The manifest to serialise.
    dest : Path
        Where to write the JSON. Its parent is created if missing.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'scale':
            manifest['scale'],
        'batches': [{
            'texture': batch['texture'],
            'firstVertex': batch['first_vertex'],
            'vertexCount': batch['vertex_count']
        } for batch in manifest['batches']]
    }
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
