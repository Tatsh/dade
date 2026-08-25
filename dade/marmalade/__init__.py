"""
Marmalade SDK asset toolkit.

``pymarmalade`` unpacks and decodes the proprietary containers used by games built on the Marmalade
SDK, converting their resources to open formats.

Public surface (all sans-I/O - they take ``bytes`` and return data structures):

- :func:`dade.marmalade.derbh.unpack` - read a Derbh (``.dz``) archive.
- :func:`dade.marmalade.resgroup.parse` - parse an IwResGroup (``.group.bin``).
- :func:`~dade.marmalade.texture.decode_texture` / :func:`~dade.marmalade.font.decode_font` -
  decode ``CIwTexture`` / ``CIwGxFont`` to Pillow images.
- :func:`dade.marmalade.material.decode_material` - decode ``CIwMaterial``.
- :func:`dade.marmalade.model.decode_model` - decode ``CIwModel`` geometry.
- :func:`dade.marmalade.hashstring.iw_hash_string` - Marmalade ``IwHashString``.
"""
from __future__ import annotations

from .derbh import unpack as unpack_derbh, unpack_to_dir as unpack_derbh_to_dir
from .font import decode_font
from .hashstring import iw_hash_string
from .material import decode_material
from .model import Model, decode_model
from .resgroup import parse as parse_resgroup
from .texture import decode_texture
from .typing import DerbhEntry, ResGroup, Resource

__all__ = ('DerbhEntry', 'Model', 'ResGroup', 'Resource', 'decode_font', 'decode_material',
           'decode_model', 'decode_texture', 'iw_hash_string', 'parse_resgroup', 'unpack_derbh',
           'unpack_derbh_to_dir')
