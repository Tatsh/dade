Max Payne
=========

Readers for the formats Remedy Entertainment built on its ``rl`` library for *Max Payne* and *Max
Payne 2*: the RAS archives and MPM mod packages, the seeded stream cipher and LZSS block wrappers
guarding them, the tagged ``R_MemoryFile`` streams every custom asset is written as, and the levels
themselves. Both games write the same tagged stream, so :py:mod:`dade.maxpayne.ldb` and
:py:mod:`dade.maxpayne.ldb2` share their reader and their glTF exporter; the level layouts differ,
and :py:mod:`dade.maxpayne.ldb2` documents where.

``dade.maxpayne.blocks``
------------------------

.. automodule:: dade.maxpayne.blocks
   :members:

``dade.maxpayne.crypto``
------------------------

.. automodule:: dade.maxpayne.crypto
   :members:

``dade.maxpayne.decals``
------------------------

.. automodule:: dade.maxpayne.decals
   :members:

``dade.maxpayne.gltf``
----------------------

.. automodule:: dade.maxpayne.gltf
   :members:

``dade.maxpayne.ldb``
---------------------

.. automodule:: dade.maxpayne.ldb
   :members:


``dade.maxpayne.ldb2``
----------------------

.. automodule:: dade.maxpayne.ldb2
   :members:

``dade.maxpayne.memoryfile``
----------------------------

.. automodule:: dade.maxpayne.memoryfile
   :members:

``dade.maxpayne.model``
-----------------------

.. automodule:: dade.maxpayne.model
   :members:

``dade.maxpayne.ras``
---------------------

.. automodule:: dade.maxpayne.ras
   :members:

``dade.maxpayne.typing``
------------------------

.. automodule:: dade.maxpayne.typing
   :members:
