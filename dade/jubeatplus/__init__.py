"""
jubeat plus (Konami) toolkit.

``jubeatplus`` converts the shipped assets of the iOS rhythm game *jubeat plus*
(``jp.konami.jubeatplus``) to formats that open outside iOS:

- :py:mod:`dade.jubeatplus.cipher` - the seven Blowfish keys, each the MD5 of a passphrase the
  binary never spells out in one piece.
- :py:mod:`dade.jubeatplus.images` - the Apple-optimised PNGs and the enciphered ``.tex``
  textures.
- :py:mod:`dade.jubeatplus.audio` - the ``.caf`` sound effects.
- :py:mod:`dade.jubeatplus.archives` - the ``.jbt`` tune packages and the marker and share-image
  ZIPs.
- :py:mod:`dade.jubeatplus.chart` - the note charts inside a tune package.
- :py:mod:`dade.jubeatplus.plists` - the property lists, including the two settings whose data
  values are enciphered strings.
- :py:mod:`dade.jubeatplus.pipeline` - the whole download, converted in one pass.

The cipher itself is :py:mod:`dade.common.bfcodec`, shared with *pop'n rhythmin*, and the
executable is read by :py:mod:`dade.misc.macho`.
"""
from __future__ import annotations

from .archives import unpack_jbt, unpack_zip
from .audio import caf_to_wav
from .chart import parse_chart
from .cipher import bgm_key, key_for_passphrase, texture_key, tune_info_key
from .images import decipher_image, defry_png, write_defried_png
from .pipeline import StepStats, find_bundle, unpack

__all__ = ('StepStats', 'bgm_key', 'caf_to_wav', 'decipher_image', 'defry_png', 'find_bundle',
           'key_for_passphrase', 'parse_chart', 'texture_key', 'tune_info_key', 'unpack',
           'unpack_jbt', 'unpack_zip', 'write_defried_png')
