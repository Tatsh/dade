Textures
========

See :ref:`the legend <formats-legend>` for the status symbols.

.. list-table::
   :header-rows: 1
   :widths: 16 10 16 8 50

   * - Format
     - Platform
     - Output
     - Status
     - Notes
   * - ``.PVR``
     - DC
     - PNG
     - ✅
     - Standard Dreamcast PVR via ``spvr2png``.
   * - ``*_T.PVR``
     - DC
     - PNG (many)
     - ✅
     - Pack container; unpacked, then each texture is run through ``spvr2png``.
   * - ``.PPM``
     - PC
     - PNG
     - ✅
     - Standard NetPBM ``P6`` via Pillow.

DC: ``.PVR``
------------

A standard Sega Dreamcast PowerVR texture (a ``PVRT`` chunk, usually with a ``GBIX`` global index
header). Converted to PNG with ``spvr2png``.

DC: ``*_T.PVR`` (level texture pack)
------------------------------------

A ``*_T.PVR`` is **not** a single texture but a pack container for a whole level's textures. It
begins with a table of contents of ``(uint32 absolute offset, uint32 size)`` pairs, zero-terminated;
the table length equals the first offset. Each entry points at a standard ``PVRT`` chunk.

The last entry is short by 8 bytes (its pixel data is still complete), and the reader clamps that
final chunk to the end of the file. Each texture in the pack is unpacked and converted to PNG with
``spvr2png``.

Dreamcast ``*_M.BIN`` models reference textures by their index into this pack; see
:doc:`models`. To unpack a pack separately, use the :doc:`../utilities` ``extract-pvr-pack``
command.

PC: ``.PPM``
------------

A standard NetPBM ``P6`` portable pixmap, converted to PNG with Pillow. PC ``.ian`` models reference
these through the ``.odl`` definition files; see :doc:`models`.
