Converters
==========

Each converter turns one asset format into an open output. The package root re-exports the shared
:py:class:`~dade.common.registry.Rule` type, and :mod:`~dade.incoming.converters.registry`
assembles every rule into the dispatch table.

Shared types
------------

.. automodule:: dade.incoming.converters
   :members: ConversionError, UnsupportedFormatError
   :imported-members:

``dade.incoming.converters.registry``
------------------------------------------

.. automodule:: dade.incoming.converters.registry
   :members:

``dade.incoming.converters.images``
----------------------------------------

.. automodule:: dade.incoming.converters.images
   :members:

``dade.incoming.converters.models``
----------------------------------------

.. automodule:: dade.incoming.converters.models
   :members:

``dade.incoming.converters.models_dc``
-------------------------------------------

.. automodule:: dade.incoming.converters.models_dc
   :members:

``dade.incoming.converters.audio``
---------------------------------------

.. automodule:: dade.incoming.converters.audio
   :members:

``dade.incoming.converters.sound_dc``
------------------------------------------

.. automodule:: dade.incoming.converters.sound_dc
   :members:

``dade.incoming.converters.data``
--------------------------------------

.. automodule:: dade.incoming.converters.data
   :members:

``dade.incoming.converters.state``
---------------------------------------

.. automodule:: dade.incoming.converters.state
   :members:

``dade.incoming.converters.text``
--------------------------------------

.. automodule:: dade.incoming.converters.text
   :members:
