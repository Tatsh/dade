Mario Kart World
================

Use an extracted NUP directory, or its ``romfs`` directory, as input. Install
``vgmstream-cli`` for audio decoding and FFmpeg for FLAC conversion.

.. code-block:: console

   dade mkw extract '/path/to/Mario Kart World [title][version]' -o output

The command writes WAV sound effects under ``output/audio``, FLAC BGM tracks under
``output/soundtrack``, PNG textures under ``output/textures``, and GLB geometry
under ``output/models``. It does not retain source game formats. The BGM tracks
include separate intros, fast variants, and outros where the game uses them.
The command accepts ``--pattern`` and ``--limit`` for a smaller run.
Use ``--force`` to regenerate converted files after a converter update.
BARS archives are converted into individual WAV files when the embedded audio
can be decoded.

BFRES animation archives without meshes are skipped. GLB files include mesh
positions, faces, material references, UV coordinates, and colour textures.
Each mesh detail level gets its own GLB: the base filename is
level 0, followed by ``.lod1.glb``, ``.lod2.glb``, and so on. Skeletons and
animation are not yet exported.
Large ``Piece_Gridify`` GLBs reference shared PNGs under ``output/textures/Tex``.
Preserve the output directory layout when moving those GLBs. Main Shy Guy
Bazaar GLBs embed textures limited to 512 pixels per side for browser viewing.
The full-size PNGs remain under ``output/textures/Tex``.
