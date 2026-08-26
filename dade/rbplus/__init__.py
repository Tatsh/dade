"""
REFLEC BEAT plus (Konami) toolkit.

``rbplus`` converts the shipped assets of the iOS rhythm game *REFLEC BEAT plus* to formats that
open outside iOS:

- :py:mod:`dade.rbplus.cipher` - the two Blowfish keys, each the MD5 of a passphrase the binary
  stores with every byte reduced by its own index.
- :py:mod:`dade.rbplus.package` - the ``.rb`` tune packages, whose every entry is enciphered.
- :py:mod:`dade.rbplus.chart` - the RBFF note charts inside a tune package.
- :py:mod:`dade.rbplus.render` - a chart drawn as a two-track time strip.
- :py:mod:`dade.rbplus.canvas` - the surfaces that strip is drawn on: a raster image, a vector one,
  or a page whose every note answers to a click.
- :py:mod:`dade.rbplus.archive` - the downloadable texture archives and their nested manifest.
- :py:mod:`dade.rbplus.pipeline` - the whole download, converted in one pass.

The cipher itself is :py:mod:`dade.common.bfcodec`, shared with *pop'n rhythmin* and *jubeat plus*;
the Apple-optimised PNGs go through :py:mod:`dade.common.apple_png` and the audio through
:py:mod:`dade.common.audio`.
"""
from __future__ import annotations

from .archive import ArchiveError, open_archive, read_manifest
from .canvas import Canvas, HTMLCanvas, PillowCanvas, SVGCanvas, canvas_for
from .chart import ChartError, parse_chart
from .cipher import chart_key, chart_keys, deobfuscate, key_for_passphrase
from .package import PackageError, TunePackage, classify_entry, open_package
from .pipeline import StepStats, extract_assets, find_bundle, unpack
from .render import render_chart_image

__all__ = ('ArchiveError', 'Canvas', 'ChartError', 'HTMLCanvas', 'PackageError', 'PillowCanvas',
           'SVGCanvas', 'StepStats', 'TunePackage', 'canvas_for', 'chart_key', 'chart_keys',
           'classify_entry', 'deobfuscate', 'extract_assets', 'find_bundle', 'key_for_passphrase',
           'open_archive', 'open_package', 'parse_chart', 'read_manifest', 'render_chart_image',
           'unpack')
