Asset formats
=============

Status and notes for every asset format handled by ``dade incoming``. Two builds are covered:

- **PC** is Windows, driven by ``incoming.exe``.
- **DC** is Sega Dreamcast, driven by ``1ST_READ.BIN``.

Many formats are shared between the two builds. Each conversion is reverse-engineered to a fully
decoded, open output; where a format has no portable schema (or is already open) it is copied
verbatim instead.

.. _formats-legend:

Legend
------

- ✅ **converted** means decoded and re-written in an open format.
- 📄 **copied verbatim** means already open, or without a portable schema. The original is
  mirrored as-is.
- 🚧 **being decoded** means partially understood and not yet converted.

Format groups
-------------

The formats are grouped by subsystem:

.. toctree::
   :maxdepth: 2

   containers
   textures
   models
   audio
   data-and-state
