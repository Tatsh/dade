"""
Binary glTF (GLB) building blocks shared by every converter in this package.

A GLB is one JSON document plus one binary chunk. Everything a converter has to get right about
that pairing is mechanical and identical from game to game: buffer views must start on a four-byte
boundary, accessors describe a slice of a view, images are embedded as views rather than files, and
the two chunks are padded with different filler bytes -- spaces for the JSON, NULs for the binary.

:py:class:`GLBDocument` owns that mechanism and nothing else. What a mesh means, which material a
face draws with, and how a level is laid out stay in the per-game modules, because those differ
every time. Only the container is common.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import struct

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ('ARRAY_BUFFER', 'ELEMENT_ARRAY_BUFFER', 'FLOAT', 'GLB_MAGIC', 'REPEAT', 'TRIANGLES',
           'UNLIT', 'UNSIGNED_BYTE', 'UNSIGNED_INT', 'UNSIGNED_SHORT', 'GLBDocument', 'image_mime',
           'pack_glb')

GLB_MAGIC = b'glTF'
"""Magic word starting every binary glTF file.

:meta hide-value:
"""
FLOAT = 5126
"""glTF component type for a 32-bit float.

:meta hide-value:
"""
UNSIGNED_BYTE = 5121
"""glTF component type for an 8-bit unsigned integer.

:meta hide-value:
"""
UNSIGNED_SHORT = 5123
"""glTF component type for a 16-bit unsigned integer.

:meta hide-value:
"""
UNSIGNED_INT = 5125
"""glTF component type for a 32-bit unsigned integer.

:meta hide-value:
"""
ARRAY_BUFFER = 34962
"""glTF buffer target for vertex attributes.

:meta hide-value:
"""
ELEMENT_ARRAY_BUFFER = 34963
"""glTF buffer target for indices.

:meta hide-value:
"""
TRIANGLES = 4
"""glTF primitive mode for a triangle list.

:meta hide-value:
"""
REPEAT = 10497
"""glTF sampler wrap mode that tiles a texture.

:meta hide-value:
"""
UNLIT = 'KHR_materials_unlit'
"""Extension marking a material that must not be shaded.

:meta hide-value:
"""

_VERSION = 2
_JSON_CHUNK = b'JSON'
_BIN_CHUNK = b'BIN\x00'
_HEADER_SIZE = 12
_CHUNK_HEADER_SIZE = 8
_SHORT_INDEX_LIMIT = 0xFFFF
# The first four bytes of the eight-byte PNG signature. The remaining four guard against a
# transfer that mangled line endings, which is not a risk for a payload read out of a game archive,
# and matching on them would reject the truncated headers some of these games actually store.
_PNG_MAGIC = b'\x89PNG'
_JPEG_MAGIC = b'\xff\xd8'


def image_mime(data: bytes) -> str | None:
    """
    Identify an encoded image by its magic bytes.

    glTF only allows PNG and JPEG in an embedded image, so anything else has to be re-encoded by
    the caller before it can be handed over.

    Parameters
    ----------
    data : bytes
        The encoded image.

    Returns
    -------
    str | None
        The MIME type, or :py:obj:`None` when the payload is neither PNG nor JPEG.
    """
    if data.startswith(_PNG_MAGIC):
        return 'image/png'
    if data.startswith(_JPEG_MAGIC):
        return 'image/jpeg'
    return None


def pack_glb(document: dict[str, Any], binary: bytes) -> bytes:
    """
    Wrap a glTF document and its binary payload in the GLB container.

    The two chunks take different filler: the JSON chunk is padded with spaces so it stays valid
    JSON, and the binary chunk with NULs.

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
    binary += b'\x00' * (-len(binary) % 4)
    total = _HEADER_SIZE + 2 * _CHUNK_HEADER_SIZE + len(payload) + len(binary)
    return b''.join((GLB_MAGIC, struct.pack('<II', _VERSION, total), struct.pack(
        '<I', len(payload)), _JSON_CHUNK, payload, struct.pack('<I',
                                                               len(binary)), _BIN_CHUNK, binary))


class GLBDocument:
    """
    Accumulates a glTF document and its binary chunk together.

    The lists are public because a converter fills most of them directly: a mesh, a node, or a
    material is a plain dictionary whose shape the caller decides. What this class does own is the
    binary side, where getting the alignment or an offset wrong produces a file that loads but
    renders as noise.

    Parameters
    ----------
    generator : str
        Recorded in the asset block, so a file can be traced back to the tool that wrote it.
    """
    def __init__(self, generator: str = 'dade') -> None:
        self.generator = generator
        self.blob = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []
        self.meshes: list[dict[str, Any]] = []
        self.nodes: list[dict[str, Any]] = []
        self.materials: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.textures: list[dict[str, Any]] = []
        self.samplers: list[dict[str, Any]] = []
        self.animations: list[dict[str, Any]] = []
        self.skins: list[dict[str, Any]] = []
        self.extensions_used: list[str] = []

    def add_view(self, payload: bytes, target: int | None = None) -> int:
        """
        Append a block to the binary chunk and describe it with a buffer view.

        Parameters
        ----------
        payload : bytes
            The bytes to append.
        target : int | None
            glTF buffer target hint, or :py:obj:`None` for data a vertex puller never reads, such
            as an animation's keyframes or an embedded image.

        Returns
        -------
        int
            Index of the new buffer view.
        """
        self.blob.extend(b'\x00' * (-len(self.blob) % 4))
        view: dict[str, Any] = {
            'buffer': 0,
            'byteOffset': len(self.blob),
            'byteLength': len(payload)
        }
        if target is not None:
            view['target'] = target
        self.blob.extend(payload)
        self.views.append(view)
        return len(self.views) - 1

    def accessor(self, payload: bytes, target: int | None = None, **extra: Any) -> int:
        """
        Append attribute or index data and describe it with an accessor.

        Parameters
        ----------
        payload : bytes
            The raw data.
        target : int | None
            glTF buffer target, or :py:obj:`None`.
        extra : Any
            Remaining accessor fields, such as ``componentType``, ``count`` and ``type``.

        Returns
        -------
        int
            Index into the document's accessors.
        """
        self.accessors.append({'bufferView': self.add_view(payload, target), **extra})
        return len(self.accessors) - 1

    def floats(self,
               values: Sequence[Sequence[float]],
               kind: str,
               *,
               target: int | None = None,
               bounds: bool = False) -> int:
        """
        Add a float attribute or keyframe accessor.

        Parameters
        ----------
        values : collections.abc.Sequence[collections.abc.Sequence[float]]
            One tuple per element, all the same length.
        kind : str
            glTF accessor type, such as ``VEC3`` or ``SCALAR``.
        target : int | None
            glTF buffer target. Pass :py:data:`ARRAY_BUFFER` for a vertex attribute and leave it
            out for animation keyframes, which no vertex puller reads.
        bounds : bool
            Also record the component-wise minimum and maximum, which glTF requires on the
            ``POSITION`` attribute and on an animation sampler's input.

        Returns
        -------
        int
            Index into the document's accessors.
        """
        size = len(values[0])
        extra: dict[str, Any] = {'componentType': FLOAT, 'count': len(values), 'type': kind}
        if bounds:
            columns = list(zip(*values, strict=True))
            extra['min'] = [min(column) for column in columns]
            extra['max'] = [max(column) for column in columns]
        payload = b''.join(struct.pack(f'<{size}f', *value) for value in values)
        return self.accessor(payload, target, **extra)

    def indices(self, values: Sequence[int]) -> int:
        """
        Add an index accessor, narrowing the component type to what the values need.

        Parameters
        ----------
        values : collections.abc.Sequence[int]
            Vertex indices.

        Returns
        -------
        int
            Index into the document's accessors.
        """
        largest = max(values, default=0)
        narrow = largest <= _SHORT_INDEX_LIMIT
        component, code = (UNSIGNED_SHORT, 'H') if narrow else (UNSIGNED_INT, 'I')
        return self.accessor(struct.pack(f'<{len(values)}{code}', *values),
                             ELEMENT_ARRAY_BUFFER,
                             componentType=component,
                             count=len(values),
                             type='SCALAR')

    def add_image(self, payload: bytes, mime: str, name: str) -> int:
        """
        Embed one image and give it a texture that materials can reference.

        The first call also creates the tiling sampler every texture shares, since a game texture
        that does not tile simply never has coordinates outside the unit square.

        Parameters
        ----------
        payload : bytes
            The encoded image.
        mime : str
            Its MIME type.
        name : str
            Name for the image.

        Returns
        -------
        int
            Index into the document's textures.
        """
        if not self.samplers:
            self.samplers.append({'wrapS': REPEAT, 'wrapT': REPEAT})
        self.images.append({'bufferView': self.add_view(payload), 'mimeType': mime, 'name': name})
        self.textures.append({'sampler': 0, 'source': len(self.images) - 1})
        return len(self.textures) - 1

    def use(self, extension: str) -> None:
        """
        Record that the document relies on an extension, once however often it is asked.

        Parameters
        ----------
        extension : str
            The extension name.
        """
        if extension not in self.extensions_used:
            self.extensions_used.append(extension)

    def finish(self, name: str, roots: Iterable[int] | None = None) -> bytes:
        """
        Serialise the document to a complete GLB.

        Parameters
        ----------
        name : str
            Name for the scene.
        roots : collections.abc.Iterable[int] | None
            Nodes to put in the scene. Defaults to every node, which is right only when the
            converter built a flat list rather than a hierarchy: a child listed a second time at
            the root would be drawn twice, under two different transforms.

        Returns
        -------
        bytes
            A complete binary glTF.
        """
        document: dict[str, Any] = {
            'accessors':
                self.accessors,
            'asset': {
                'generator': self.generator,
                'version': '2.0'
            },
            'bufferViews':
                self.views,
            'buffers': [{
                'byteLength': len(self.blob) + (-len(self.blob) % 4)
            }],
            'materials':
                self.materials,
            'meshes':
                self.meshes,
            'nodes':
                self.nodes,
            'scene':
                0,
            'scenes': [{
                'name': name,
                'nodes': list(range(len(self.nodes)) if roots is None else roots)
            }]
        }
        # These are all optional, and glTF requires an array it declares to be non-empty, so each
        # is written only when the converter actually filled it.
        optional = (('animations', self.animations), ('extensionsUsed', self.extensions_used),
                    ('images', self.images), ('samplers', self.samplers), ('skins', self.skins),
                    ('textures', self.textures))
        document.update({key: value for key, value in optional if value})
        return pack_glb(document, bytes(self.blob))
