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

Passing an ISO runs these stages. The source is first **materialised** into the output directory --
an image is extracted into it, a directory is copied into it -- and every ARK there is then unpacked
and its assets converted in place, in a fixed order:

.. graphviz::

   digraph unpack {
      node [shape=box];
      iso     [label="Amplitude.iso (opened read-only)"];
      out     [label="output dir: source extracted / copied in", shape=folder];
      extract [label="ark.extract -> loose files (.gz gunzipped)"];
      milo    [label="1. decompose Milo (*.rnd -> folder + manifest.json)"];
      assets  [label="2. convert assets (bitmap -> PNG, *.dtb -> JSON, mesh -> OBJ)"];
      link    [label="3. link references / materials"];
      banks   [label="4. split sample banks (*.bnk / *.hd -> WAV)"];
      audio   [label="convert disc audio (*.STR -> WAV)"];
      delete  [label="5. --delete (optional): prune ARK, STR, raw assets"];
      iso -> out [label="materialize()"];
      out -> extract [label="run_game(): per *.ark"];
      extract -> milo;
      milo -> assets;
      assets -> link;
      extract -> banks;
      out -> audio;
      link -> delete;
      banks -> delete;
      audio -> delete;
   }

A directory input is copied into the output directory rather than extracted; a cue/bin input is
decoded to an ISO image first. The source is only ever read, never written to.

This is a fixed, ordered pipeline rather than a general "keep unpacking until no archives remain"
loop. Each stage opens one known container type and surfaces the inputs the next stage consumes, so
the order matters: Milo scenes are decomposed **before** the asset-conversion pass, which is what
lets the meshes and bitmaps inside a scene be converted. The pipeline follows Amplitude's bounded,
known container hierarchy:

.. graphviz::

   digraph hierarchy {
      node [shape=box];
      iso  [label="ISO file system"];
      ark  [label="ARK archive"];
      milo [label="Milo .rnd scene"];
      mesh [label="mesh -> OBJ + MTL"];
      bmp  [label="bitmap -> PNG"];
      dtb  [label="DataArray .dtb -> JSON"];
      bank [label="sample bank .bnk/.hd -> per-sample WAV"];
      str  [label="streaming .STR -> WAV"];
      iso -> ark;
      iso -> str;
      ark -> milo;
      ark -> bank;
      milo -> mesh;
      milo -> bmp;
      milo -> dtb;
   }

By default every materialised file is kept -- the ARK archives, the disc ``.str`` files, and the raw
assets beside their converted form; ``--delete`` prunes them all once the reference-linking passes
have made the outputs self-contained. The source disc is never touched.

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
