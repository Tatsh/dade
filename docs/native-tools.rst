Native tools
============

Some conversions shell out to native helper programs. Each must be on ``PATH`` or supplied with the
matching ``--*-path`` option. When a helper is missing, only the conversions that need it are
skipped and the affected files are copied verbatim.

.. list-table::
   :header-rows: 1
   :widths: 20 35 45

   * - Tool
     - Used for
     - Option
   * - `7z <https://www.7-zip.org/>`_
     - Extracting ``DATA1.CAB`` from a PC ISO, when ``isodump`` is not found.
     -
   * - `gdiextract <https://github.com/MachXNU/gdiextract>`_
     - Extracting the ISO 9660 file system from a Dreamcast GDI.
     - ``--gdiextract-path``
   * - `isodump <https://sourceforge.net/projects/cdrtools/>`_
     - Extracting ``DATA1.CAB`` from a PC ISO.
     -
   * - `spvr2png <https://github.com/nextgeniuspro/spvr2png>`_
     - Converting Sega Dreamcast PVR images to PNG.
     - ``--spvr2png-path``
   * - `unshield <https://github.com/twogood/unshield>`_
     - Unpacking the InstallShield ``DATA1.CAB`` cabinet on the PC disc.
     - ``--unshield-path``

Of ``isodump`` and ``7z``, whichever is found first on ``PATH`` is used.
