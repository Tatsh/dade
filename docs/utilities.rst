Utilities
=========

Alongside the main :doc:`dade incoming extract <usage>` command, two subcommands convert a single
Incoming asset without mirroring a whole source tree.

ian2obj
-------

Convert one model to Wavefront OBJ and MTL. Both the PC ``.ian`` mesh format and the Dreamcast
``*_M.BIN`` model pack are accepted; the format is detected from the file name. A Dreamcast pack
needs its matching ``*_ML.BIN`` index beside it and writes one OBJ and MTL per contained object.

Textures are resolved from the game root, which is auto-detected by walking up from the model (or
given explicitly with ``--game-root``): the ``.odl`` plus ``.ppm`` files for a PC model, or the
level ``*_T.PVR`` pack for a Dreamcast model. Pass ``--no-texture`` to skip texture resolution. See
:doc:`formats/models` for the underlying formats.

.. click:: dade.incoming.commands.ian2obj:ian2obj
   :prog: dade incoming ian2obj
   :nested: full

extract-pvr-pack
----------------

Unpack a Dreamcast ``*_T.PVR`` texture pack. Each contained texture is written under
``OUTDIR/<pack name>/`` as a separate ``.pvr`` file, or as a PNG with ``--png`` (which requires
``spvr2png``). See :doc:`formats/textures` for the pack layout.

.. click:: dade.incoming.commands.extract_pvr_pack:extract_pvr_pack
   :prog: dade incoming extract-pvr-pack
   :nested: full
