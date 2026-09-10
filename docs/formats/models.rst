Models and scenes
=================

See :ref:`the legend <formats-legend>` for the status symbols.

.. list-table::
   :header-rows: 1
   :widths: 14 12 14 8 52

   * - Format
     - Platform
     - Output
     - Status
     - Notes
   * - ``.IAN``
     - PC
     - OBJ + MTL
     - ✅
     - Highest-detail mesh; resolves its texture through the ``.odl`` files.
   * - ``*_M.BIN``
     - DC
     - OBJ + MTL
     - ✅
     - Pack of objects indexed by ``*_ML.BIN``; materials by texture index.
   * - ``*_ML.BIN``
     - DC
     - JSON
     - ✅
     - The model directory (offset table) into ``*_M.BIN``.
   * - ``.MDL``
     - PC, DC
     - (copied)
     - 📄
     - Plain-text physics/config DSL.
   * - ``.ODL``
     - PC, DC
     - (copied)
     - 📄
     - Plain-text object definition DSL.
   * - ``.WDL``
     - PC, DC
     - (copied)
     - 📄
     - Plain-text world definition DSL.

PC: ``.IAN``
------------

A single mesh stored at several levels of detail; the converter reads the highest-detail level
only. The ``.ian`` file includes no texture. The referencing ``.odl`` pairs each mesh with a
``.ppm`` texture (see :doc:`textures`). The texture is resolved, converted to PNG, written beside
the model, and referenced from the generated material.

DC: ``*_M.BIN`` and ``*_ML.BIN``
--------------------------------

A ``*_M.BIN`` is a **pack of many independent objects**, a level's models: terrain patches,
buildings, props, and vehicles. Its companion ``*_ML.BIN`` is the directory, an array of ``uint32``
file offsets into the ``*_M.BIN``, terminated by ``0xFFFFFFFF``.

Each offset points at a 144-byte object header. The active level-of-detail record (at +0x10) gives a
face count, a packed ``(texture_index << 16) | vertex_count`` word, and file offsets to a vertex
pool (40-byte records: position, normal, and UV) and a triangle pool (16-byte records). Non-mesh
objects (sprites and placeholders) are detected by out-of-range pointers and skipped.

Each decodable object is written as ``<stem>_<NNN>.obj`` and ``.mtl`` in a directory titled after
the source. The object's texture is the ``texture_index`` sub-texture of the level's ``*_T.PVR``
pack (see :doc:`textures`). It is extracted and written as a PNG beside the material.

The ``*_ML.BIN`` index itself is also converted to JSON (its offset count and offset list). The
JSON is useful for inspecting the pack.

.. _formats-coordinate-transform:

Coordinate transform
--------------------

*Incoming* uses a left-handed coordinate system with up = -Y; Wavefront OBJ is right-handed with
up = +Y. Both model converters apply the same transform when emitting OBJ:

- **Negating Y alone** performs the left-to-right-handed conversion and the up flip in one step.
  Because it is a single-axis reflection, it also turns the game's clockwise-front winding into
  OBJ's counter-clockwise-front, and the winding is retained as written.
- **Texture V is flipped** (``1 - v``) to move from the game's top-left texture origin to OBJ's
  bottom-left origin.

These transforms are recorded as comments at the top of every generated OBJ.

Copied formats
--------------

``.MDL``, ``.ODL``, and ``.WDL`` are plain-text definition DSLs (physics and configuration, object
definitions, and world definitions, respectively). They are already human-readable, and they are
copied verbatim. The ``.odl`` files are additionally *read* during conversion to resolve PC ``.ian``
textures, but the files themselves are not modified.
