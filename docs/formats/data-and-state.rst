Data and state
==============

See :ref:`the legend <formats-legend>` for the status symbols.

.. list-table::
   :header-rows: 1
   :widths: 12 12 12 8 56

   * - Format
     - Platform
     - Output
     - Status
     - Notes
   * - ``.bin``
     - PC, DC
     - JSON
     - ✅
     - Terrain heightfield (513×513 ``s16``) or tile flags (128×128 ``u16``).
   * - ``.ctl``
     - PC, DC
     - JSON
     - ✅
     - Demo/replay input recording (16-byte records).
   * - ``.sav``
     - PC
     - JSON
     - ✅
     - Mission-state snapshot with named fields decoded and gaps as base64.
   * - ``.cfg``
     - PC
     - JSON
     - ✅
     - Config with named blocks split, and the build stamp and verified checksum decoded.
   * - ``.lev``
     - PC
     - JSON
     - ✅
     - Level-state snapshot sharing the mission field table minus its prefix.
   * - ``.xxx``
     - PC
     - JSON
     - ✅
     - Debug snapshot in the same format as ``.sav``.
   * - ``.TXT``
     - DC
     - UTF-8
     - ✅
     - Shift-JIS or ISO-8859-15 text re-encoded to UTF-8.

Terrain and replay
------------------

``.bin`` data files are either a terrain heightfield (a 513×513 grid of signed 16-bit samples) or a
tile-flag map (a 128×128 grid of unsigned 16-bit values); the shape is detected from the file size
and decoded to JSON. ``.ctl`` files are demo/replay input recordings of 16-byte records, decoded to
a JSON list.

Save and snapshot state
-----------------------

The save, config, level, and debug-snapshot files (``.sav``, ``.cfg``, ``.lev``, and ``.xxx``) are
``memcpy``-style images of game RAM. Their schemas were reverse-engineered from the PC executable
(``incoming.exe``), and the decoders map the real in-memory layout rather than treating the body as
opaque. Every byte is decoded into a typed value. The output is therefore both human-inspectable and
lossless, and no field remains a base64 blob.

The configuration file (``.cfg``, written by ``SaveGameConfigFile``) is a concatenation of
fixed-size blocks described by the game's internal save-descriptor table, totalling 10980 bytes.
It is split into its 21 named blocks, each decoded into a readable value:

- the build stamp and the trailing text buffers as strings;
- the keybind block as four control-config pages of ten slots, each
  ``{directInputScancode, name}`` where the name is the W3C ``KeyboardEvent.code`` for the bound
  DirectInput scancode (special input codes become ``special<n>``; an unbound slot has an empty
  name);
- the options block as the serial/modem multiplayer connection settings: COM port, baud rate, stop
  bits, parity, and flow control;
- the high-score block as a list of tables, each with its category id, sub-index, and nine
  ``{score, name}`` entries;
- the input-options, camera-state, joystick-binding, and input-state blocks as objects of named
  fields (the same field-table approach used for the snapshots);
- the saved-mission-slot table as a list of ten ``{name, missionSlot, levelValue}`` slots;
- the force-feedback flag as a boolean;
- the checksum as ``{stored, computed, valid}``, where ``computed`` is a signed-byte sum recomputed
  over the high-score block and ``valid`` reports whether the two agree.

The snapshot files share one field table derived from the contiguous run of game globals that the
engine serialises. ``.sav`` and ``.xxx`` (``SaveMissionStateSnapshot``) cover the whole region;
``.lev`` (``SaveLevelStateSnapshot``) is the same region without its 12-byte leading mission-id
prefix, and it reuses the same table shifted by that prefix. Each decoded field includes its game
variable name (mission and game-mode flags, camera and replay-camera state, the script runtime,
score statistics, frame and timer counters, lighting and fog state, the saved CD-audio track, and
more). Run-time pointer fields are decoded as unsigned 32-bit words; their saved values are not
meaningful across sessions.

The largest part of a snapshot is the world-object pool, an array of 1700 204-byte ``GameObject``
records; it is decoded as ``worldObjectPool``, a list of objects with named fields (position,
orientation vectors, type and class ids, behaviour and effect state, lifetime, and so on). The
128×128 world spatial grid (``worldGrid``) and the script process and label tables
(``scriptProcTable``, ``scriptLabelTable``) are likewise decoded. A few smaller pools that are not
yet fully reverse-engineered remain as ``unknownAt_<offset>`` arrays.

Across every decoded block and snapshot, field names are emitted as plain camelCase (the game's
Hungarian prefixes are stripped); each ``*Flags`` bitfield is expanded into an object of one boolean
per bit, using the reverse-engineered name for bits whose meaning is known (for example
``netGameFlags`` exposes ``deathmatch``, ``teamMode``, and ``timedMission``) and ``bit<n>`` for the
rest; and split ``*Lo``/``*Hi`` dword pairs are combined into a single 64-bit field.

Dreamcast ``.TXT`` text
-----------------------

Dreamcast ``.TXT`` files are re-encoded to UTF-8. The source encoding is detected in order: UTF-8,
then Shift-JIS (Japanese), then ISO-8859-15 (French, German, Spanish, and Italian). Pure-ASCII files
are already valid UTF-8 and pass through unchanged.
