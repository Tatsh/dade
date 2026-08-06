Asset formats
=============

Status and notes for every asset format handled by ``destin incoming``. Two builds are covered:

- **PC** — Windows, driven by ``incoming.exe``.
- **DC** — Sega Dreamcast, driven by ``1ST_READ.BIN``.

Many formats are shared between the two builds. Each conversion is reverse-engineered to a fully
decoded, open output; where a format has no portable schema (or is already open) it is copied
verbatim instead.

.. _formats-legend:

Legend
------

- ✅ **converted** — decoded and re-written in an open format.
- 📄 **copied verbatim** — already open, or no portable schema, so the original is mirrored as-is.
- 🚧 **being decoded** — partially understood; not yet converted.

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
