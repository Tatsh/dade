Amplitude and FreQuency
=======================

*Amplitude* and *FreQuency* (Harmonix, PS2) share one engine, so ``destin amplitude`` and
``destin frequency`` are two commands over the same unpacking pipeline; only the ARK layout differs
(Amplitude is magic-less, FreQuency starts with ``ARK\0``). Point either at a disc and it writes a
tree of converted assets:

.. code-block:: shell

   destin amplitude unpack Amplitude.iso -o out
   destin frequency unpack FreQuency.cue -o out

The ``DISC`` argument may be an already-extracted directory, a PS2 ISO image, or -- for the
FreQuency CD release -- the ``.cue`` of a cue/bin pair. The disc is always opened read-only; nothing
is written back to it, and the output directory may not be, or be nested inside, an input directory.

Unpacking flow
--------------

Passing an ISO runs these stages. The disc is *mounted* (its whole file system is materialised into
a temporary directory), then every ARK on it is extracted and its assets are converted in a fixed
order:

.. code-block:: text

   Amplitude.iso  (opened read-only)
        |
        |  mount(): parse the ISO 9660 file system, extract every file to a temp directory
        v
   temp/  GEN/MAIN.ARK, AUDIO/SONG.STR, ...
        |
        |  run_game(): for each *.ark found on the disc
        v
   ark.extract()  ->  out/GEN/MAIN/...        loose files (.gz entries gunzipped)
        |
        |  then, in a fixed order, over that output:
        |    1. decompose Milo   (*.rnd  ->  <name>/ folder of objects + manifest.json)
        |    2. convert assets   (bitmap -> PNG, *.dtb -> JSON, mesh -> OBJ, ...)
        |    3. link references / materials   (the OBJ and MTL point at the PNGs)
        |    4. split sample banks   (*.bnk / *.hd  ->  per-sample WAV)
        |    5. --delete (optional): prune the raw intermediates
        v
   disc audio:  AUDIO/*.STR  ->  out/AUDIO/*.wav

A directory input skips the mount step and is walked in place; a cue/bin input is decoded to an ISO
image first. The source is never one of the things written to.

This is a fixed, ordered pipeline rather than a general "keep unpacking until no archives remain"
loop. Each stage opens one known container type and surfaces the inputs the next stage consumes, so
the order matters: Milo scenes are decomposed **before** the asset-conversion pass, which is what
lets the meshes and bitmaps inside a scene be converted. The pipeline follows Amplitude's bounded,
known container hierarchy:

.. code-block:: text

   ISO file system
     +-- ARK archive                   (ark.extract)
     |     +-- Milo .rnd scene         (decompose -> folder)
     |     |     +-- mesh          -> OBJ + MTL
     |     |     +-- bitmap        -> PNG
     |     |     +-- DataArray .dtb -> JSON
     |     +-- sample bank .bnk/.hd   -> per-sample WAV
     +-- streaming .STR                -> WAV

By default the raw intermediates are kept beside their converted form; ``--delete`` prunes them
after the reference-linking passes have made the outputs self-contained. The extracted source is
never touched.

Using the unpackers from Python
-------------------------------

The per-game unpackers are part of the developer API. Construct one over a disc and ``await`` its
:py:meth:`~destin.harmonix.unpacker.Unpacker.unpack` coroutine; the source may be a directory, an
ISO, or a cue/bin ``.cue``:

.. code-block:: python

   import asyncio
   from pathlib import Path

   from destin.amplitude import AmplitudeUnpacker
   from destin.common import InvalidFormatError


   async def main() -> None:
       unpacker = AmplitudeUnpacker(Path('Amplitude.iso'))
       try:
           summary = await unpacker.unpack(Path('out'))
       except InvalidFormatError as e:
           raise SystemExit(f'error: {e}') from e
       for step, detail in summary.items():
           print(f'{step}: {detail}')


   asyncio.run(main())

``unpack`` rejects an unusable source itself, so there is no need to guard it: it raises
:py:class:`~destin.common.exceptions.InvalidFormatError` when the disc is not readable or holds no
ARK of the game's layout, and :py:exc:`ValueError` when the output directory is inside a source
directory.

An unpacker is also iterable over its raw carve-outs, without converting or writing anything.
Asynchronous iteration (``async for``) is the primary form; keep the loop free of exception
handling and let a thin wrapper own the recovery policy:

.. code-block:: python

   async def read_assets(source: Path) -> None:
       # Core: drive the iteration; let exceptions propagate.
       async for asset in AmplitudeUnpacker(source):   # Asset(name, data)
           print(f'{asset.name}: {len(asset.data)} bytes')


   async def main(source: Path) -> None:
       # Higher level: turn a bad source into a clean failure.
       try:
           await read_assets(source)
       except InvalidFormatError as e:
           raise SystemExit(f'error: {e}') from e

``FrequencyUnpacker`` from :py:mod:`destin.frequency` has the identical interface; only the ARK
layout it reads and its acceptance of a cue/bin disc differ.
