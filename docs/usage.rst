Usage
=====

This page documents the ``destin incoming`` sub-command (the *Incoming* extractor). Run
``destin --help`` for the full list of games and ``destin <game> --help`` for a game's subcommands.

.. code-block:: shell

   destin incoming extract --output OUTPUT_DIR SOURCE

The extractor mirrors ``SOURCE`` into ``OUTPUT_DIR``: recognised assets are converted to open
formats and every other file is copied verbatim, preserving the original directory layout. The
source is never modified. See :doc:`formats/index` for the complete list of what is converted.

Source types
------------

``SOURCE`` may be any of the following:

- A **PC disc directory** containing ``DATA1.CAB`` (an InstallShield cabinet).
- A **PC disc ISO** containing ``DATA1.CAB``. The cabinet is first extracted from the ISO with
  ``isodump`` or ``7z``, then unpacked.
- A **``DATA1.CAB`` file** on its own.
- A **Dreamcast GDI** (a ``.gdi`` file with its track files beside it), unpacked with
  ``gdiextract``.
- A **directory of already extracted** PC or GD-ROM content.

Installed copies
----------------

An installed copy works as the source too. Point at the game's directory, such as the
``Incoming 3DFX`` folder of the
`Zoom Platform Incoming Trilogy <https://www.zoom-platform.com/product/incoming-trilogy>`_
(``…/Incoming Trilogy/Incoming 3DFX``).

The *Incoming 3DFX*, *Incoming USA*, and *Incoming Subversion* (an expansion pack) titles share the
original engine and are supported. *Incoming Forces* uses a different engine and is **not**
supported.

Options
-------

Pass ``--gdiextract-path``, ``--spvr2png-path``, or ``--unshield-path`` to point at the
:doc:`native tools <native-tools>` when they are not on ``PATH``, and ``--debug`` for verbose
logging.

Command reference
-----------------

.. click:: destin.incoming.main:main
   :prog: destin incoming extract
   :nested: full
