"""
Format converters that are not tied to any one game.

``misc`` collects readers for platform-level artefacts that turn up in more than one title:

- :func:`destin.misc.coredata.convert` - deserialise a compiled Core Data model (``.cdm``,
  ``.mom``) into plain JSON-ready values.
- :func:`destin.misc.coredata.build_sql` - emit the effective SQLite script a mapping model
  amounts to.
- :func:`destin.misc.strings.read_strings` - read an Xcode ``.strings`` localisation table in
  either the compiled or the old-style text form.
- :func:`destin.misc.sc_info.read_bundles` - read the FairPlay ``SC_Info`` bookkeeping of every
  bundle in a purchased application, and of every executable within each bundle.
- :func:`destin.misc.macho.read_macho` - read the properties of a Mach-O executable.
"""
from __future__ import annotations

from .certificate import CertificateSummary, find_certificates, load_certificate
from .coredata import build_sql, convert, load_mom_column_types
from .macho import read_macho
from .sc_info import (
    SCInfo,
    SCRecord,
    is_main_bundle,
    read_bundles,
    read_sc_info,
    render_text,
    sc_info_to_json,
)
from .strings import read_strings

__all__ = ('CertificateSummary', 'SCInfo', 'SCRecord', 'build_sql', 'convert', 'find_certificates',
           'is_main_bundle', 'load_certificate', 'load_mom_column_types', 'read_bundles',
           'read_macho', 'read_sc_info', 'read_strings', 'render_text', 'sc_info_to_json')
