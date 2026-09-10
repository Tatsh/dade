Audio and sound banks
=====================

See :ref:`the legend <formats-legend>` for the status symbols.

.. list-table::
   :header-rows: 1
   :widths: 14 10 16 8 52

   * - Format
     - Platform
     - Output
     - Status
     - Notes
   * - ``.raw``
     - DC
     - WAV
     - ✅
     - Red Book CDDA wrapped in a RIFF header.
   * - ``.OSB``
     - DC
     - WAV (many)
     - ✅
     - Manatee voice bank; AICA ADPCM, one WAV per record.
   * - ``.MLT``
     - DC
     - JSON
     - ✅
     - Manatee ``SMLT`` multi-unit container table.
   * - ``.wav``
     - PC
     - (copied)
     - 📄
     - Already standard RIFF/WAVE PCM.
   * - ``Manatee.drv``
     - DC
     - (copied)
     - 📄
     - AICA sound-driver program; executable code, not an asset.

DC: ``.raw`` (CDDA audio)
-------------------------

Red Book CDDA ripped verbatim: signed 16-bit, 44100 Hz, stereo, interleaved, whole 2352-byte
sectors, native little-endian. Conversion is a straight RIFF/WAVE header wrap with **no byte-swap**;
a proper rip is not swapped.

DC: ``.OSB`` and ``.MLT`` (Manatee sound)
-----------------------------------------

``.OSB`` is a ``SOSB`` speech/SFX bank: a 16-byte header, an offset table of ``SOSP`` voice records,
and each record with packed AICA voice registers (sample start, length, 4-bit ADPCM codec, and
pitch). Every record is decoded with the Yamaha/AICA ADPCM algorithm to signed 16-bit mono PCM and
written as one WAV per record (22050 Hz in the shipped banks).

``.MLT`` is a Sega ``SMLT`` multi-unit container. Its 32-byte-per-unit table (type, bank, AICA
address and size, file offset and size) is decoded to JSON.

DC: ``Manatee.drv``
-------------------

Sega's Manatee AICA sound-driver program, uploaded to the audio chip at runtime. This is executable
driver code rather than a convertible asset, and it is copied verbatim and documented only.

PC: ``.wav``
------------

Already standard RIFF/WAVE PCM, and it is copied verbatim.
