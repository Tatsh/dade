Converters
==========

Each converter turns one asset format into an open output. The package root re-exports the shared
:py:class:`~destin.common.registry.Rule` type, and :mod:`~destin.incoming.converters.registry`
assembles every rule into the dispatch table.

Shared types
------------

.. automodule:: destin.incoming.converters
   :members: ConversionError, UnsupportedFormatError
   :imported-members:

``destin.incoming.converters.registry``
------------------------------------------

.. automodule:: destin.incoming.converters.registry
   :members:

``destin.incoming.converters.images``
----------------------------------------

.. automodule:: destin.incoming.converters.images
   :members:

``destin.incoming.converters.models``
----------------------------------------

.. automodule:: destin.incoming.converters.models
   :members:

``destin.incoming.converters.models_dc``
-------------------------------------------

.. automodule:: destin.incoming.converters.models_dc
   :members:

``destin.incoming.converters.audio``
---------------------------------------

.. automodule:: destin.incoming.converters.audio
   :members:

``destin.incoming.converters.sound_dc``
------------------------------------------

.. automodule:: destin.incoming.converters.sound_dc
   :members:

``destin.incoming.converters.data``
--------------------------------------

.. automodule:: destin.incoming.converters.data
   :members:

``destin.incoming.converters.state``
---------------------------------------

.. automodule:: destin.incoming.converters.state
   :members:

``destin.incoming.converters.text``
--------------------------------------

.. automodule:: destin.incoming.converters.text
   :members:
