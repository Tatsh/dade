Disc containers
===============

The outermost layer of each release is a disc container that includes every other asset. The
extractor unpacks these first, then walks the resulting tree. See
:ref:`the legend <formats-legend>` for the status symbols.

.. list-table::
   :header-rows: 1
   :widths: 18 10 14 8 50

   * - Format
     - Platform
     - Output
     - Status
     - Notes
   * - ``DATA1.CAB``
     - PC
     - files
     - ✅
     - InstallShield cabinet; unpacked with ``unshield``.
   * - GDI + tracks
     - DC
     - files
     - ✅
     - GD-ROM disc image; the ISO 9660 file system is extracted with ``gdiextract``.

PC: ``DATA1.CAB``
-----------------

The PC disc ships its files inside a single InstallShield cabinet, ``DATA1.CAB``. The extractor
accepts the disc directory, the ``DATA1.CAB`` file directly, or a PC ISO that includes it. When
given an ISO, the cabinet is first extracted with ``isodump`` or ``7z`` (whichever is found on
``PATH``) and then unpacked with ``unshield``.

DC: GDI + tracks
----------------

The Dreamcast disc is distributed as a GDI: a ``.gdi`` text index alongside the raw track files. The
ISO 9660 file system on the data track is extracted with ``gdiextract``, yielding the GD-ROM
directory tree that the extractor then walks.

See :doc:`../native-tools` for where to obtain ``unshield``, ``gdiextract``, ``isodump``, and
``7z``.
