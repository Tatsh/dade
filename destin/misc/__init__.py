"""
Format converters that are not tied to any one game.

``misc`` collects readers for platform-level artefacts that turn up in more than one title:

- :func:`destin.misc.coredata.convert` - deserialise a compiled Core Data model (``.cdm``,
  ``.mom``) into plain JSON-ready values.
- :func:`destin.misc.coredata.build_sql` - emit the effective SQLite script a mapping model
  amounts to.
- :func:`destin.misc.strings.read_strings` - read an Xcode ``.strings`` localisation table in
  either the compiled or the old-style text form.
"""
from __future__ import annotations

from .coredata import build_sql, convert, load_mom_column_types
from .strings import read_strings

__all__ = ('build_sql', 'convert', 'load_mom_column_types', 'read_strings')
