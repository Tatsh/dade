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

GLB files include mesh positions, faces, material references, UV coordinates,
and colour textures. Each mesh detail level gets a separate GLB. The base
filename is level 0, followed by ``.lod1.glb``, ``.lod2.glb``, and so on.

A model with more than one bone also gets its skeleton as a glTF skin. Each
bone becomes a node with its rest pose, the skin records the inverse bind
matrices, and every vertex records up to four bones with weights that sum to
one. Blender imports the skin as an armature ready to be posed. Rigidly bound
parts, such as the wheels of a vehicle, follow a single bone. The rest pose
reproduces the inverse bind matrices stored in the game files to float
precision.

Fonts are written under ``output/fonts``. The ``.bfttf`` and ``.bfotf`` files
are decrypted to ordinary ``.ttf`` and ``.otf`` files, and a font with more
than one face is written as a ``.ttc`` collection.

Skeletal animations are written as JSON under ``output/animations``, one file
for each archive. Each clip records its name, frame count, rotation mode, and,
for every bone it animates, the base scale, rotation, and translation, and the
curve of each moving channel. A curve is a cubic Hermite spline, and each key
records its frame, its value, and its slope in units per frame. Two keys at the
same frame give the incoming and the outgoing slope at the frame.

The level 0 GLB of a model with more than one bone also embeds the skeletal
clips of its animation archives as glTF animations. The clips come from the
archive that shares the model's prefix and, for a driver, from every
``DriverA_<name>_*`` archive. Each clip takes the name ``<archive>:<clip>`` and
drives the bones it shares with the skeleton, sampled at every frame and played
at 60 frames a second. Blender lists the clips as actions of the armature.

The same JSON files record the material animations under ``material_clips``. A
texture pattern swaps the texture a sampler reads (the blinking eyes of a
driver, for example), and is written as the texture shown from each key frame
on. For the eyes of a driver, the ``.00`` textures are open and the ``.03``
textures are closed, and the PNGs of both are under ``output/textures/Tex``.
The other curves of a material animation, such as the texture offsets that move
the pupils, are Hermite curves and are decoded the same way as skeletal curves.

Large ``Piece_Gridify`` GLBs reference shared PNGs under ``output/textures/Tex``.
Preserve the output directory layout when moving those GLBs. Main Shy Guy
Bazaar GLBs embed textures limited to 512 pixels per side for browser viewing.
The full-size PNGs remain under ``output/textures/Tex``.
