"""
Tone Sphere (bit192labs) toolkit.

``bit192`` holds the game-specific pieces that sit on top of the generic Marmalade support in
:mod:`marmalade`:

- :func:`~destin.bit192.cz.decrypt` - undo Tone Sphere's ``.cz`` XOR layer to recover a Derbh
  archive.
- :func:`~destin.bit192.extract.extract` - unpack and decode every asset from an
  ``.xapk``/``.apk``/``.obb``.
- :func:`destin.bit192.audio.wrap_wav` - wrap Tone Sphere's headerless 16-bit PCM as WAV.
- :class:`destin.bit192.save.SaveFile` - read and edit ``save.bin`` (e.g. unlock DLC).
"""
from __future__ import annotations

from .audio import wrap_wav
from .cz import decrypt
from .extract import extract
from .save import SaveFile

__all__ = ('SaveFile', 'decrypt', 'extract', 'wrap_wav')
