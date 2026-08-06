"""
Tony Hawk's Pro Skater 2 (Neversoft/Activision) PC asset toolkit.

``thps2pc`` reads the proprietary containers and scene files shipped with the PC release and
converts them to open formats:

- :func:`destin.thps2pc.pkr.parse` and :func:`destin.thps2pc.pkr.extract_all` - read a ``PKR2``
  resource pack such as ``All.pkr``.
- :class:`destin.thps2pc.psx.Scene` - parse a ``.PSX`` scene: sectors, faces, mesh-section
  descriptors, and the chunk list.
- :func:`destin.thps2pc.textures.parse_lighting` and
  :func:`destin.thps2pc.textures.decode_instance` - decode the palettes and textures embedded in
  a ``*_L.PSX`` lighting file.
- :func:`destin.thps2pc.mesh.build_batches` - group a scene's triangles by texture for export.
- :mod:`destin.thps2pc.render` - top-down and isometric software renders of a scene.

Everything above works on ``bytes`` and needs no external tools. ImageMagick is only invoked when
a command is asked to write an image format other than PPM.
"""
from __future__ import annotations

from .mesh import build_batches
from .pkr import extract_all, parse as parse_pkr
from .psx import Scene
from .textures import decode_instance, parse_lighting

__all__ = ('Scene', 'build_batches', 'decode_instance', 'extract_all', 'parse_lighting',
           'parse_pkr')
